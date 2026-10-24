"""Rolling graph from OSM ways (spec "Graph build"; CONTRACTS.md graph.json).

1. ways with highway in osm.HIGHWAYS (motorway/trunk never match)
2. a node at every intersection (OSM node shared by ways, repeated in a way, or a clipped way end);
   chains between intersections split into equal pieces of at most 50 m
3. DEM sampled at every node; grade_pct = 100 * (elev_b - elev_a) / length_m, signed for a->b
4. per-edge tags: length_m, grade_pct, surface, steps, step_count, curb_cut, road_class, sidewalk, name, driveway
"""
import math

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from .core import geo
from .osm import HIGHWAYS

MAX_EDGE_M = 50.0
PATH_CLASSES = {"footway", "path", "sidewalk", "pedestrian", "cycleway", "steps"}

PAVED = {"paved", "asphalt", "concrete", "concrete:plates", "concrete:lanes", "paving_stones", "sett",
         "cobblestone", "unhewn_cobblestone", "metal", "wood", "chipseal", "brick", "bricks", "tartan",
         "rubber", "acrylic", "paving_stones:30"}
UNPAVED = {"unpaved", "gravel", "fine_gravel", "dirt", "earth", "ground", "grass", "sand", "mud", "compacted",
           "pebblestone", "rock", "rocks", "woodchips", "grass_paver", "dirt/sand", "salt", "snow", "ice", "clay"}
KERB_OK = {"lowered", "flush", "no"}
SLOPED_CURB_OK = {"yes", "both", "one_side", "left", "right"}


def surface_class(tags):
    s = (tags.get("surface") or "").strip().lower()
    if s in PAVED:
        return "paved"
    if s in UNPAVED:
        return "unpaved"
    return "unknown"


def parse_int(v):
    if v is None:
        return None
    try:
        return int(str(v).strip().split(";")[0])
    except ValueError:
        return None


def is_steps(tags):
    if tags.get("highway") == "steps":
        return True
    return tags.get("incline") in ("up", "down") and (tags.get("step_count") is not None or tags.get("steps") == "yes")


def has_sidewalk(tags):
    if tags.get("highway") in ("footway", "sidewalk") or tags.get("footway") == "sidewalk":
        return True
    for k in ("sidewalk", "sidewalk:both", "sidewalk:left", "sidewalk:right"):
        v = tags.get(k)
        if v is not None and v not in ("none", "no"):
            return True
    return False


def curb_cut(way_tags, node_tags):
    """true / false / "unknown" from kerb and wheelchair tags on the way and (for paths) the nodes along this piece.

    A lowered/flush kerb (or sloped_curb) anywhere at the crossing beats a raised one there, since that is the way
    across; then raised kerb or wheelchair=no -> false; then wheelchair=yes -> true; then any other kerb evidence ->
    unknown; default true ("no kerb involved"). Crossing and kerb nodes on roads are ignored: a road passing through
    a crossing node does not climb a kerb.
    """
    kerbs, wheel, unknown, sloped = [], [], False, False
    if "kerb" in way_tags:
        kerbs.append(way_tags["kerb"])
    if "wheelchair" in way_tags:
        wheel.append(way_tags["wheelchair"])
    if "crossing" in (way_tags.get("footway"), way_tags.get("cycleway"), way_tags.get("path")):
        unknown = True
    if way_tags.get("highway") in PATH_CLASSES:
        for t in node_tags:
            if "kerb" in t:
                kerbs.append(t["kerb"])
            elif t.get("barrier") == "kerb":
                unknown = True                     # kerb node without a kerb=* value
            if t.get("highway") == "crossing":
                unknown = True
            if "wheelchair" in t:
                wheel.append(t["wheelchair"])
            if t.get("sloped_curb") in SLOPED_CURB_OK:
                sloped = True
    if sloped or any(k in KERB_OK for k in kerbs):
        return True
    if "raised" in kerbs or "no" in wheel:
        return False
    if "yes" in wheel:
        return True
    if unknown or kerbs or wheel:                  # kerb=yes/rolled/..., wheelchair=limited
        return "unknown"
    return True


def _interp(coords, cum, d):
    """Point at along-distance d on a polyline with cumulative distances cum."""
    i = int(np.searchsorted(cum, d, side="right")) - 1
    i = max(0, min(i, len(coords) - 2))
    seg = cum[i + 1] - cum[i]
    t = 0.0 if seg <= 0 else (d - cum[i]) / seg
    (la0, lo0), (la1, lo1) = coords[i], coords[i + 1]
    return la0 + (la1 - la0) * t, lo0 + (lo1 - lo0) * t


def _runs(way, nodes, clip):
    """Split a way's node list into runs of consecutive nodes that exist and fall inside the clip bbox."""
    runs, cur = [], []
    for nid in way["nodes"]:
        nd = nodes.get(nid)
        ok = nd is not None and (clip is None or (clip[0] <= nd[1] <= clip[2] and clip[1] <= nd[0] <= clip[3]))
        if ok:
            cur.append(nid)
        else:
            if len(cur) >= 2:
                runs.append(cur)
            cur = []
    if len(cur) >= 2:
        runs.append(cur)
    return runs


def is_deck(tags):
    """Bridges and tunnels: the DEM is the ground under/over them, not the deck."""
    return tags.get("bridge", "no") != "no" or tags.get("tunnel", "no") != "no"


def _flatten_decks(z, decks, remap):
    """Replace DEM samples along each bridge/tunnel run by a straight line between its two ends."""
    n = 0
    for deck in decks:
        pts = [(int(remap[i]), d) for i, d in deck if remap[i] >= 0]
        if len(pts) < 3:
            continue
        (i0, d0), (i1, d1) = pts[0], pts[-1]
        if np.isnan(z[i0]) or np.isnan(z[i1]) or d1 <= d0:
            continue
        for i, d in pts[1:-1]:
            z[i] = z[i0] + (z[i1] - z[i0]) * (d - d0) / (d1 - d0)
            n += 1
    return n


def build_graph(nodes, ways, elev_fn, clip=None, min_component_nodes=0):
    """nodes {osm_id: (lat, lon, tags)}, ways [{id, nodes, tags}], elev_fn(lons, lats) -> array.

    Returns (graph dict per CONTRACTS.md, stats dict).
    """
    runs = []
    for w in ways:
        if w["tags"].get("highway") not in HIGHWAYS:
            continue
        for r in _runs(w, nodes, clip):
            runs.append((w, r))

    use = {}
    for _, r in runs:
        for nid in r:
            use[nid] = use.get(nid, 0) + 1
        use[r[0]] += 1                              # run ends are always graph nodes
        use[r[-1]] += 1

    out_nodes = []                                  # [lat, lon]
    osm_to_idx = {}

    def vertex(nid):
        i = osm_to_idx.get(nid)
        if i is None:
            lat, lon, _ = nodes[nid]
            i = len(out_nodes)
            out_nodes.append([lat, lon])
            osm_to_idx[nid] = i
        return i

    edges = []
    decks = []                                      # bridges/tunnels: [(out_idx, distance along the run)]
    for w, r in runs:
        tags = w["tags"]
        deck = [] if is_deck(tags) else None
        offset = 0.0
        base = {
            "surface": surface_class(tags),
            "steps": is_steps(tags),
            "step_count": parse_int(tags.get("step_count")),
            "road_class": tags.get("highway"),
            "sidewalk": has_sidewalk(tags),
            "name": tags.get("name") or None,
            "driveway": tags.get("service") == "driveway",
        }
        # split the run into chains at intersections
        chain = [r[0]]
        chains = []
        for nid in r[1:]:
            chain.append(nid)
            if use[nid] >= 2:
                chains.append(chain)
                chain = [nid]
        for ch in chains:
            coords = [(nodes[n][0], nodes[n][1]) for n in ch]
            cum = [0.0]
            for (la0, lo0), (la1, lo1) in zip(coords, coords[1:]):
                cum.append(cum[-1] + geo.haversine_m(la0, lo0, la1, lo1))
            L = cum[-1]
            if L < 0.05:
                offset += L
                continue
            k = max(1, math.ceil(L / MAX_EDGE_M - 1e-9))
            if ch[0] == ch[-1]:
                k = max(k, 2)                       # never emit a self-loop
            piece = L / k
            ids = [vertex(ch[0])]
            for j in range(1, k):
                ids.append(len(out_nodes))
                out_nodes.append(list(_interp(coords, cum, j * piece)))
            ids.append(vertex(ch[-1]))
            for j in range(k):
                d0, d1 = j * piece - 1e-6, (j + 1) * piece + 1e-6
                ntags = [nodes[n][2] for n, d in zip(ch, cum) if d0 <= d <= d1 and nodes[n][2]]
                e = {"a": ids[j], "b": ids[j + 1], "length_m": piece}
                e.update(base)
                e["curb_cut"] = curb_cut(tags, ntags)
                edges.append(e)
            if deck is not None:
                deck.extend((ids[j], offset + j * piece) for j in range(k + 1))
            offset += L
        if deck:
            decks.append(deck)

    stats = {"osm_ways": sum(1 for w in ways if w["tags"].get("highway") in HIGHWAYS), "runs": len(runs)}
    keep = np.ones(len(out_nodes), dtype=bool)
    if min_component_nodes and edges:
        a = np.array([e["a"] for e in edges])
        b = np.array([e["b"] for e in edges])
        m = coo_matrix((np.ones(len(edges)), (a, b)), shape=(len(out_nodes), len(out_nodes)))
        ncomp, labels = connected_components(m, directed=False)
        sizes = np.bincount(labels)
        keep = sizes[labels] >= min_component_nodes
        stats["components"] = int(ncomp)
        stats["components_dropped"] = int((sizes < min_component_nodes).sum())
        stats["nodes_dropped_small_components"] = int((~keep).sum())

    # used nodes only, renumbered 0..N-1 in creation order
    used = np.zeros(len(out_nodes), dtype=bool)
    for e in edges:
        used[e["a"]] = used[e["b"]] = True
    used &= keep
    remap = -np.ones(len(out_nodes), dtype=int)
    remap[used] = np.arange(int(used.sum()))
    lat = np.array([p[0] for p in out_nodes])[used]
    lon = np.array([p[1] for p in out_nodes])[used]
    z = np.asarray(elev_fn(lon, lat), dtype="float64")
    stats["nodes_without_elevation"] = int(np.isnan(z).sum())
    stats["deck_nodes_interpolated"] = _flatten_decks(z, decks, remap)

    g_nodes = [{"id": i, "lat": round(float(lat[i]), 7), "lon": round(float(lon[i]), 7),
                "elev": 0.0 if math.isnan(z[i]) else round(float(z[i]), 2)} for i in range(len(lat))]
    noz = np.isnan(z)                              # outside the DEM: elev 0.0, grade 0 (counted in stats)
    g_edges = []
    for e in edges:
        a, b = int(remap[e["a"]]), int(remap[e["b"]])
        if a < 0 or b < 0:
            continue
        za, zb = g_nodes[a]["elev"], g_nodes[b]["elev"]
        grade = 0.0 if noz[a] or noz[b] else (zb - za) / e["length_m"] * 100.0
        g_edges.append({
            "a": a, "b": b, "length_m": round(e["length_m"], 2), "grade_pct": round(grade, 2),
            "surface": e["surface"], "steps": e["steps"], "step_count": e["step_count"], "curb_cut": e["curb_cut"],
            "road_class": e["road_class"], "sidewalk": e["sidewalk"], "name": e["name"], "driveway": e["driveway"],
        })
    stats["nodes"] = len(g_nodes)
    stats["edges"] = len(g_edges)
    return {"nodes": g_nodes, "edges": g_edges}, stats
