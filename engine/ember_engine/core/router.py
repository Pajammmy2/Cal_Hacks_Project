"""Accessible router. Navigator/EmberCore/Router.swift is a line-for-line port of this file.

Cost per edge = length_m / speed(profile, grade) * penalty(profile, edge); impassable = inf.
"""
import heapq
import json
import math
from pathlib import Path

from . import geo, shared

INF = float("inf")
TOP_N = 5
FIRE_SIDE_HALF_ANGLE = 60.0
PERIMETER_BUFFER_M = 500.0
ARRIVAL_RADIUS_M = 25.0
# "Fire ahead": close every edge whose midpoint lies within WEDGE_RADIUS_M and within +-WEDGE_HALF_ANGLE of the fire bearing.
WEDGE_HALF_ANGLE = 60.0
WEDGE_RADIUS_M = 400.0
# Physical blockage: among routes within HEADING_SIMILAR_RATIO of the fastest, prefer the one whose first
# HEADING_WINDOW_M heading is closest to the previous direction of travel.
HEADING_WINDOW_M = 200.0
HEADING_SIMILAR_RATIO = 1.25


class Graph:
    def __init__(self, data):
        self.nodes = data["nodes"]
        self.edges = data["edges"]
        n = len(self.nodes)
        self.lat = [nd["lat"] for nd in self.nodes]
        self.lon = [nd["lon"] for nd in self.nodes]
        # adjacency: node -> list of (edge_index, neighbor, forward)
        self.adj = [[] for _ in range(n)]
        for i, e in enumerate(self.edges):
            self.adj[e["a"]].append((i, e["b"], True))
            self.adj[e["b"]].append((i, e["a"], False))
        self.degree = [len(a) for a in self.adj]
        self._grid = {}
        self._cell = 0.002  # ~200 m
        for i in range(n):
            self._grid.setdefault(self._key(self.lat[i], self.lon[i]), []).append(i)

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    def _key(self, lat, lon):
        return (int(math.floor(lat / self._cell)), int(math.floor(lon / self._cell)))

    def snap(self, lat, lon, usable=None):
        """Nearest node, searching outward ring by ring. `usable(node)` filters candidates (e.g. has a passable edge)."""
        ky, kx = self._key(lat, lon)
        best, best_d = None, INF
        for r in range(0, 60):
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if max(abs(dy), abs(dx)) != r:
                        continue
                    for i in self._grid.get((ky + dy, kx + dx), ()):
                        if usable is not None and not usable(i):
                            continue
                        d = geo.haversine_m(lat, lon, self.lat[i], self.lon[i])
                        if d < best_d:
                            best, best_d = i, d
            # rings 0..r cover every point within r cells (east-west cells are narrower by cos(lat))
            covered_m = r * self._cell * 111000.0 * math.cos(math.radians(lat))
            if best is not None and covered_m >= best_d:
                break
        return best, best_d

    def edge_bearing(self, edge_index, forward):
        e = self.edges[edge_index]
        a, b = (e["a"], e["b"]) if forward else (e["b"], e["a"])
        return geo.bearing_deg(self.lat[a], self.lon[a], self.lat[b], self.lon[b])


class Profile:
    def __init__(self, key, battery_pct=100.0):
        spec = shared.profiles()[key]
        self.key = key
        self.max_grade = float(spec["max_grade_pct"])
        self.speed_flat = float(spec["speed_flat_mps"])
        self.uphill_slowdown = bool(spec["uphill_slowdown"])
        self.forbid_steps = spec["forbid_steps"]
        self.forbid_unpaved = bool(spec["forbid_unpaved"])
        self.penalize = list(spec["penalize_x3"])
        self.penalize_x2 = list(spec.get("penalize_x2", []))
        self.impassable = list(spec.get("impassable", []))
        self.shelter_only = bool(spec["shelter_only"])
        self.range_m = INF
        if spec.get("battery_range"):
            self.range_m = max(0.0, battery_pct) / 100.0 * float(spec["full_range_m"])

    def edge_cost(self, e, forward):
        """Seconds to traverse edge e in the given direction, or inf if impassable."""
        if self.shelter_only:
            return INF
        grade = e["grade_pct"] if forward else -e["grade_pct"]
        if e.get("steps"):
            if self.forbid_steps == "all":
                return INF
            if self.forbid_steps == "gt3":
                sc = e.get("step_count")
                if sc is None or sc > 3:
                    return INF
        if self.forbid_unpaved and e.get("surface") == "unpaved":
            return INF
        if abs(grade) > self.max_grade:
            return INF
        # raised kerb with no lowered/flush kerb at the crossing (graph build resolves that into curb_cut false)
        if "curb_cut_false" in self.impassable and e.get("curb_cut") is False:
            return INF
        speed = self.speed_flat
        if self.uphill_slowdown:
            if grade > 0:
                speed *= max(0.3, 1.0 - grade / 10.0)
            elif grade < -6.0:
                speed *= 0.8
        penalty = 1.0
        for rule in self.penalize:
            if rule == "curb_cut_unknown" and e.get("curb_cut") == "unknown":
                penalty *= 3.0
            elif rule == "no_sidewalk_primary_secondary" and e.get("road_class") in ("primary", "secondary") and not e.get("sidewalk"):
                penalty *= 3.0
            elif rule == "grade_gt_6" and abs(grade) > 6.0:
                penalty *= 3.0
        for rule in self.penalize_x2:
            if rule == "curb_cut_false" and e.get("curb_cut") is False:
                penalty *= 2.0
        return e["length_m"] / speed * penalty


def astar(graph, profile, start, goals, blocked=frozenset()):
    """Fastest route from start to the nearest (by cost) node in `goals`. Returns route dict or None.

    Battery range (power chair): if the fastest route is longer than the range, fall back to the shortest
    passable route, which is within range whenever any route is; a reachable refuge is never missed.
    """
    route = _search(graph, profile, start, goals, blocked, by_length=False)
    if route is not None and route["length_m"] > profile.range_m:
        route = _search(graph, profile, start, goals, blocked, by_length=True)
    return route


def _search(graph, profile, start, goals, blocked, by_length):
    goals = set(goals)
    if not goals or start is None or profile.shelter_only:
        return None
    glat = [graph.lat[g] for g in goals]
    glon = [graph.lon[g] for g in goals]
    h_div = 1.0 if by_length else profile.speed_flat

    def h(n):
        d = min(geo.haversine_m(graph.lat[n], graph.lon[n], la, lo) for la, lo in zip(glat, glon))
        return d / h_div

    g_key = {start: 0.0}
    g_time = {start: 0.0}
    g_len = {start: 0.0}
    prev = {start: None}
    heap = [(h(start), 0.0, start)]
    closed = set()
    while heap:
        _, gk, n = heapq.heappop(heap)
        if n in closed:
            continue
        closed.add(n)
        if n in goals:
            return _build_route(graph, prev, g_time, g_len, n)
        for ei, nb, fwd in graph.adj[n]:
            if ei in blocked or nb in closed:
                continue
            e = graph.edges[ei]
            c = profile.edge_cost(e, fwd)
            if c == INF:
                continue
            nl = g_len[n] + e["length_m"]
            if by_length and nl > profile.range_m:
                continue
            ng = gk + (e["length_m"] if by_length else c)
            if ng < g_key.get(nb, INF):
                g_key[nb] = ng
                g_time[nb] = g_time[n] + c
                g_len[nb] = nl
                prev[nb] = (n, ei, fwd)
                heapq.heappush(heap, (ng + h(nb), ng, nb))
    return None


def _build_route(graph, prev, g_cost, g_len, end):
    nodes, edges, dirs = [end], [], []
    cur = end
    while prev[cur] is not None:
        p, ei, fwd = prev[cur]
        edges.append(ei)
        dirs.append(fwd)
        nodes.append(p)
        cur = p
    nodes.reverse()
    edges.reverse()
    dirs.reverse()
    time_s = g_cost[end]
    return {
        "nodes": nodes,
        "edges": edges,
        "forward": dirs,
        "coords": [[graph.lat[n], graph.lon[n]] for n in nodes],
        "length_m": round(g_len[end], 1),
        "time_s": round(time_s, 1),
        "minutes": int(math.ceil(time_s / 60.0)) if time_s > 0 else 0,
    }


def fire_side_ok(graph, origin, refuge, fire_bearing, perimeter):
    clon, clat = refuge["centroid"]
    if fire_bearing is not None:
        b = geo.bearing_deg(graph.lat[origin], graph.lon[origin], clat, clon)
        if geo.angdiff(b, fire_bearing) <= FIRE_SIDE_HALF_ANGLE:
            return False
    if perimeter:
        if geo.point_in_polygon(clat, clon, perimeter):
            return False
        if geo.distance_to_polygon_edge_m(clat, clon, perimeter) <= PERIMETER_BUFFER_M:
            return False
    return True


def wedge_blocked_edges(graph, lat, lon, bearing, half_angle=WEDGE_HALF_ANGLE, radius_m=WEDGE_RADIUS_M):
    """Edges whose midpoint is within radius_m of (lat, lon) and within +-half_angle of `bearing` (the fire side)."""
    out = set()
    for i, e in enumerate(graph.edges):
        mlat = (graph.lat[e["a"]] + graph.lat[e["b"]]) / 2.0
        mlon = (graph.lon[e["a"]] + graph.lon[e["b"]]) / 2.0
        if geo.haversine_m(lat, lon, mlat, mlon) > radius_m:
            continue
        if geo.angdiff(geo.bearing_deg(lat, lon, mlat, mlon), bearing) <= half_angle:
            out.add(i)
    return out


def initial_heading(graph, route, window_m=HEADING_WINDOW_M):
    """Bearing from the route start to the first node at or beyond window_m along it (the last node if shorter)."""
    nodes = route["nodes"]
    if len(nodes) < 2:
        return None
    cum = 0.0
    end = nodes[-1]
    for i, ei in enumerate(route["edges"]):
        cum += graph.edges[ei]["length_m"]
        if cum >= window_m:
            end = nodes[i + 1]
            break
    return geo.bearing_deg(graph.lat[nodes[0]], graph.lon[nodes[0]], graph.lat[end], graph.lon[end])


def prefer_heading(graph, candidates, heading):
    """Stable re-order: candidates within HEADING_SIMILAR_RATIO of the fastest time come first, sorted by how close
    their initial heading is to `heading`; the rest keep their (time, -score) order."""
    if heading is None or not candidates:
        return list(candidates)
    limit = candidates[0]["route"]["time_s"] * HEADING_SIMILAR_RATIO
    similar = [c for c in candidates if c["route"]["time_s"] <= limit]
    rest = [c for c in candidates if c["route"]["time_s"] > limit]

    def turn(c):
        h = initial_heading(graph, c["route"])
        return geo.angdiff(h, heading) if h is not None else 180.0
    similar.sort(key=turn)
    return similar + rest


def choose(graph, refuges, profile, origin, fire_bearing=None, perimeter=None, blocked=frozenset(), top_n=TOP_N,
           prefer=None):
    """Fire-side filter -> top N by score -> route each -> sort by (time, -score). Index 0 = A, 1 = B.
    `prefer` (a heading in degrees) applies prefer_heading() to the sorted list (physical blockage re-plan)."""
    if profile.shelter_only:
        return []
    allowed = [r for r in refuges if fire_side_ok(graph, origin, r, fire_bearing, perimeter)]
    allowed.sort(key=lambda r: -r["score"])
    out = []
    for r in allowed[:top_n]:
        goals = [ep["node"] for ep in r.get("entry_points", []) if ep.get("node") is not None]
        route = astar(graph, profile, origin, goals, blocked)
        if route is not None:
            out.append({"refuge": r, "route": route})
    out.sort(key=lambda c: (c["route"]["time_s"], -c["refuge"]["score"]))
    return prefer_heading(graph, out, prefer)


def arrived(lat, lon, refuge):
    return any(geo.haversine_m(lat, lon, ep["lat"], ep["lon"]) <= ARRIVAL_RADIUS_M for ep in refuge.get("entry_points", []))


def usable_origin(graph, profile):
    """Snap filter: only nodes with at least one passable edge for this profile."""
    def ok(n):
        return any(profile.edge_cost(graph.edges[ei], fwd) < INF for ei, _, fwd in graph.adj[n])
    return ok


def load_bundle(bundle_dir):
    bundle_dir = Path(bundle_dir)
    graph = Graph.load(bundle_dir / "graph.json")
    with open(bundle_dir / "refuges.json", encoding="utf-8") as f:
        refuges = json.load(f)["refuges"]
    return graph, refuges
