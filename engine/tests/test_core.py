import math
from pathlib import Path

import pytest

from ember_engine.core import cues, geo, hashing, plan, router

ROOT = Path(__file__).resolve().parents[2]
FAKE = ROOT / "bundles" / "fake"


@pytest.fixture(scope="module")
def bundle():
    if not FAKE.exists():
        import subprocess, sys
        subprocess.check_call([sys.executable, str(ROOT / "engine" / "fixtures" / "make_fake_bundle.py")])
    return plan.Bundle(FAKE)


def _refuge_at_bearing(graph, origin, bearing, dist_m=1000):
    lat0, lon0 = graph.lat[origin], graph.lon[origin]
    dlat = dist_m * math.cos(math.radians(bearing)) / 111320.0
    dlon = dist_m * math.sin(math.radians(bearing)) / (111320.0 * math.cos(math.radians(lat0)))
    return {"centroid": [lon0 + dlon, lat0 + dlat]}


def test_fire_side_filter_30_excluded_90_kept(bundle):
    g = bundle.graph
    o = 0
    fire = 45.0
    assert not router.fire_side_ok(g, o, _refuge_at_bearing(g, o, fire + 30), fire, None)
    assert not router.fire_side_ok(g, o, _refuge_at_bearing(g, o, fire - 30), fire, None)
    assert router.fire_side_ok(g, o, _refuge_at_bearing(g, o, fire + 90), fire, None)
    assert router.fire_side_ok(g, o, _refuge_at_bearing(g, o, fire - 90), fire, None)


def test_perimeter_buffer(bundle):
    g = bundle.graph
    r = _refuge_at_bearing(g, 0, 180, 1000)
    lon, lat = r["centroid"]
    d = 0.003  # ~330 m box around the refuge -> inside
    poly = [[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat + d]]
    assert not router.fire_side_ok(g, 0, r, None, poly)
    far = [[p[0] + 0.05, p[1]] for p in poly]
    assert router.fire_side_ok(g, 0, r, None, far)


@pytest.mark.parametrize("key", ["manual_chair", "manual_chair_pushed", "power_chair"])
def test_chairs_never_use_steps_unpaved_or_steep(bundle, key):
    g = bundle.graph
    prof = router.Profile(key)
    for origin in range(0, 225, 17):
        for c in router.choose(g, bundle.refuges, prof, origin):
            for ei, fwd in zip(c["route"]["edges"], c["route"]["forward"]):
                e = g.edges[ei]
                grade = e["grade_pct"] if fwd else -e["grade_pct"]
                assert not e["steps"]
                assert e["surface"] != "unpaved"
                assert abs(grade) <= prof.max_grade


def test_choose_sorted_by_time(bundle):
    prof = router.Profile("manual_chair")
    out = router.choose(bundle.graph, bundle.refuges, prof, 50)
    times = [c["route"]["time_s"] for c in out]
    assert times == sorted(times)
    assert len(out) <= router.TOP_N


def test_blocked_replan_changes_route_or_no_route(bundle):
    g = bundle.graph
    prof = router.Profile("manual_chair")
    origin = 60
    first = router.choose(g, bundle.refuges, prof, origin)[0]
    blocked = {first["route"]["edges"][0]}
    again = router.choose(g, bundle.refuges, prof, origin, blocked=frozenset(blocked))
    assert not again or again[0]["route"]["edges"] != first["route"]["edges"]
    for c in again:
        assert first["route"]["edges"][0] not in c["route"]["edges"]


def test_bedbound_is_shelter_only(bundle):
    p = plan.make_plan(bundle, "1500 Pearson Rd", {"mobility": "bedbound"})
    assert p["no_route"] and p["choices"] == []
    assert any("911" in s for s in p["shelter"]["steps"])


def test_power_chair_battery_range(bundle):
    full = router.choose(bundle.graph, bundle.refuges, router.Profile("power_chair", 100), 0)
    empty = router.choose(bundle.graph, bundle.refuges, router.Profile("power_chair", 0.5), 0)  # 100 m range
    assert full and all(c["route"]["length_m"] <= 100 for c in empty)


def test_uphill_slower_than_downhill():
    p = router.Profile("manual_chair")
    e = {"length_m": 50, "grade_pct": 5.0, "surface": "paved", "steps": False, "curb_cut": True, "road_class": "residential", "sidewalk": True}
    assert p.edge_cost(e, True) > p.edge_cost(e, False)
    assert math.isclose(p.edge_cost(e, True), 50 / (1.2 * 0.5))
    steep_down = dict(e, grade_pct=-7.0)
    assert math.isclose(p.edge_cost(steep_down, True), 50 / (1.2 * 0.8))


def test_penalty_x3():
    p = router.Profile("manual_chair")
    base = {"length_m": 12, "grade_pct": 0, "surface": "paved", "steps": False, "curb_cut": True, "road_class": "residential", "sidewalk": True}
    assert math.isclose(p.edge_cost(dict(base, curb_cut="unknown"), True), 30.0)
    assert math.isclose(p.edge_cost(dict(base, road_class="primary", sidewalk=False), True), 30.0)
    w = router.Profile("walker")
    assert math.isclose(w.edge_cost(dict(base, grade_pct=7), True), 12 / 0.6 * 3)
    assert w.edge_cost(dict(base, steps=True, step_count=3), True) < math.inf
    assert w.edge_cost(dict(base, steps=True, step_count=4), True) == math.inf
    assert w.edge_cost(dict(base, steps=True, step_count=None), True) == math.inf


def test_cues_use_templates_and_card_steps_bounded(bundle):
    p = plan.make_plan(bundle, "1500 Pearson Rd", {"mobility": "manual_chair"})
    c = p["choices"][0]
    assert c["cues"][0]["template"] == "start"
    assert c["cues"][-1]["template"] == "arrive"
    assert 1 <= len(c["card_steps"]) <= 7


def test_hash_normalizes_whitespace():
    assert hashing.clip_key("Turn left onto  Clark Rd. ") == hashing.clip_key("Turn left onto Clark Rd.")
    assert hashing.for_cartesia("Turn left onto Skyway.") == "Turn left onto sky way."


def test_geo_helpers():
    assert geo.angdiff(350, 10) == 20
    assert geo.signed_turn(0, 90) == 90
    assert geo.signed_turn(0, 270) == -90


def test_power_chair_falls_back_to_shortest_route_within_range():
    # 0 -> 1 -> 3 is short (200 m) but uphill and slow; 0 -> 2 -> 3 is fast but 600 m. Range 300 m.
    def e(a, b, length, grade):
        return {"a": a, "b": b, "length_m": length, "grade_pct": grade, "surface": "paved", "steps": False,
                "step_count": None, "curb_cut": True, "road_class": "residential", "sidewalk": True, "name": "X",
                "driveway": False}
    nodes = [{"id": i, "lat": 39.75 + 0.0005 * (i % 2), "lon": -121.6 + 0.0005 * (i // 2), "elev": 0} for i in range(4)]
    g = router.Graph({"nodes": nodes, "edges": [e(0, 1, 100, 9.5), e(1, 3, 100, 9.5), e(0, 2, 300, 0), e(2, 3, 300, 0)]})
    prof = router.Profile("power_chair", battery_pct=1.5)   # 300 m
    fast = router._search(g, prof, 0, [3], frozenset(), by_length=False)
    assert fast["length_m"] == 600
    r = router.astar(g, prof, 0, [3])
    assert r is not None and r["length_m"] == 200 and r["edges"] == [0, 1]
    assert router.astar(g, router.Profile("power_chair", battery_pct=0.5), 0, [3]) is None


def test_raised_kerb_rules():
    base = {"length_m": 12, "grade_pct": 0, "surface": "paved", "steps": False, "curb_cut": False,
            "road_class": "residential", "sidewalk": True}
    for key in ("manual_chair", "manual_chair_pushed", "power_chair"):
        assert router.Profile(key).edge_cost(base, True) == math.inf
        assert router.Profile(key).edge_cost(dict(base, curb_cut=True), True) < math.inf
        assert math.isclose(router.Profile(key).edge_cost(dict(base, curb_cut="unknown"), True),
                            3 * router.Profile(key).edge_cost(dict(base, curb_cut=True), True))
    w = router.Profile("walker")
    assert math.isclose(w.edge_cost(base, True), 12 / 0.6 * 2)
    assert math.isclose(w.edge_cost(dict(base, curb_cut="unknown"), True), 12 / 0.6)


def test_chairs_never_cross_a_raised_kerb(bundle):
    g = bundle.graph
    assert any(e["curb_cut"] is False for e in g.edges)
    for key in ("manual_chair", "manual_chair_pushed", "power_chair"):
        prof = router.Profile(key)
        for origin in range(0, 225, 7):
            for c in router.choose(g, bundle.refuges, prof, origin):
                assert all(g.edges[ei]["curb_cut"] is not False for ei in c["route"]["edges"])


def _midpoint(g, ei):
    e = g.edges[ei]
    return (g.lat[e["a"]] + g.lat[e["b"]]) / 2.0, (g.lon[e["a"]] + g.lon[e["b"]]) / 2.0


def test_wedge_blocks_edges_toward_the_fire_only(bundle):
    g = bundle.graph
    o = 112
    lat, lon = g.lat[o], g.lon[o]
    for fire in (0.0, 90.0, 180.0, 270.0):
        w = router.wedge_blocked_edges(g, lat, lon, fire)
        assert w
        for ei in w:
            mlat, mlon = _midpoint(g, ei)
            assert geo.haversine_m(lat, lon, mlat, mlon) <= router.WEDGE_RADIUS_M
            assert geo.angdiff(geo.bearing_deg(lat, lon, mlat, mlon), fire) <= router.WEDGE_HALF_ANGLE
        # the adjacent edge that leaves toward the fire is closed; the three others stay open
        for ei, _, fwd in g.adj[o]:
            assert (ei in w) == (geo.angdiff(g.edge_bearing(ei, fwd), fire) <= router.WEDGE_HALF_ANGLE)
        # nothing beyond the radius or on the far side
        for ei in range(len(g.edges)):
            mlat, mlon = _midpoint(g, ei)
            if geo.haversine_m(lat, lon, mlat, mlon) <= router.WEDGE_RADIUS_M and \
                    geo.angdiff(geo.bearing_deg(lat, lon, mlat, mlon), fire) <= router.WEDGE_HALF_ANGLE:
                assert ei in w
            else:
                assert ei not in w


def test_fire_reroute_picks_a_refuge_away_from_the_bearing(bundle):
    g = bundle.graph
    prof = router.Profile("manual_chair")
    o = 112
    lat, lon = g.lat[o], g.lon[o]
    for fire in (0.0, 90.0, 180.0, 270.0):
        w = router.wedge_blocked_edges(g, lat, lon, fire)
        out = router.choose(g, bundle.refuges, prof, o, fire, None, frozenset(w))
        assert out
        for c in out:
            clon, clat = c["refuge"]["centroid"]
            assert geo.angdiff(geo.bearing_deg(lat, lon, clat, clon), fire) > router.FIRE_SIDE_HALF_ANGLE
            assert not (w & set(c["route"]["edges"]))
            # the first edge does not head into the wedge
            assert geo.angdiff(g.edge_bearing(c["route"]["edges"][0], c["route"]["forward"][0]), fire) > router.WEDGE_HALF_ANGLE


def test_initial_heading_uses_the_first_200_m(bundle):
    g = bundle.graph
    prof = router.Profile("manual_chair")
    r = router.choose(g, bundle.refuges, prof, 0)[0]["route"]
    h = router.initial_heading(g, r)
    cum, end = 0.0, r["nodes"][-1]
    for i, ei in enumerate(r["edges"]):
        cum += g.edges[ei]["length_m"]
        if cum >= router.HEADING_WINDOW_M:
            end = r["nodes"][i + 1]
            break
    assert h == geo.bearing_deg(g.lat[r["nodes"][0]], g.lon[r["nodes"][0]], g.lat[end], g.lon[end])
    assert router.initial_heading(g, {"nodes": [0], "edges": []}) is None


def test_prefer_heading_reorders_only_similar_routes():
    g = None
    fast = {"refuge": {"id": "a"}, "route": {"time_s": 100.0, "nodes": [0, 1], "edges": [0]}}
    near = {"refuge": {"id": "b"}, "route": {"time_s": 120.0, "nodes": [0, 2], "edges": [1]}}
    slow = {"refuge": {"id": "c"}, "route": {"time_s": 400.0, "nodes": [0, 3], "edges": [2]}}

    class G:   # three edges from node 0: north, east, south
        lat = [0.0, 0.01, 0.0, -0.01]
        lon = [0.0, 0.0, 0.01, 0.0]
        edges = [{"a": 0, "b": 1, "length_m": 1000.0}, {"a": 0, "b": 2, "length_m": 1000.0}, {"a": 0, "b": 3, "length_m": 1000.0}]
    g = G()
    assert [c["refuge"]["id"] for c in router.prefer_heading(g, [fast, near, slow], None)] == ["a", "b", "c"]
    # travelling east: b (east) wins over a (north); c is too slow to be promoted even though it is also 90 deg off
    assert [c["refuge"]["id"] for c in router.prefer_heading(g, [fast, near, slow], 90.0)] == ["b", "a", "c"]
    assert [c["refuge"]["id"] for c in router.prefer_heading(g, [fast, near, slow], 180.0)] == ["b", "a", "c"]
    assert [c["refuge"]["id"] for c in router.prefer_heading(g, [fast, near, slow], 45.0)] == ["a", "b", "c"]   # tie -> time order
    assert [c["refuge"]["id"] for c in router.prefer_heading(g, [fast, near, slow], 0.0)] == ["a", "b", "c"]


def test_physical_block_keeps_direction(bundle):
    g = bundle.graph
    prof = router.Profile("manual_chair")
    changed = 0
    for origin in range(0, len(g.nodes), 5):
        base = router.choose(g, bundle.refuges, prof, origin)
        if not base:
            continue
        first = base[0]["route"]
        heading = g.edge_bearing(first["edges"][0], first["forward"][0])
        blocked = frozenset({first["edges"][0]})
        plain = router.choose(g, bundle.refuges, prof, origin, blocked=blocked)
        pref = router.choose(g, bundle.refuges, prof, origin, blocked=blocked, prefer=heading)
        assert [c["refuge"]["id"] for c in pref] != [] or not plain
        assert sorted(c["refuge"]["id"] for c in pref) == sorted(c["refuge"]["id"] for c in plain)
        if not plain:
            continue
        limit = plain[0]["route"]["time_s"] * router.HEADING_SIMILAR_RATIO
        assert pref[0]["route"]["time_s"] <= limit
        turn = lambda c: geo.angdiff(router.initial_heading(g, c["route"]), heading)
        assert turn(pref[0]) <= min(turn(c) for c in plain if c["route"]["time_s"] <= limit)
        if pref[0]["refuge"]["id"] != plain[0]["refuge"]["id"]:
            changed += 1
    assert changed > 0, "the fixture has at least one blockage where the direction rule changes the pick"


def test_fire_intent_synonyms_are_not_physical():
    from ember_engine.core import shared
    intents = shared.intents()["intents"]
    assert "fire" in intents
    for s in ("fire ahead", "fire", "smoke ahead", "smoke", "flames", "i see fire", "there's a fire"):
        assert s in intents["fire"]
        assert s not in intents["blocked"]
    for s in ("tree down", "road closed", "car blocking", "gate locked"):
        assert s in intents["blocked"]


def test_card_steps_hold_a_word_budget_for_long_osm_routes():
    from ember_engine.core import cues as cm
    t = cm.shared.templates()
    cl = [{"template": "start", "text": t["start"].format(street="the side road", direction="northeast"), "vars": {}},
          {"template": "keep_blocks", "text": "", "vars": {"n": 2}}]
    for k in range(14):
        cl.append({"template": "turn", "text": t["turn"].format(side="left" if k % 2 else "right", street=f"Oak {k} Lane"), "vars": {}})
        cl.append({"template": "keep_meters", "text": "", "vars": {"n": 20 + 10 * k}})
    cl.append({"template": "arrive", "text": t["arrive"].format(refuge="the Save Mart Supermarket lot"), "vars": {}})
    steps = cm.card_steps(cl)
    assert 4 <= len(steps) <= 7
    assert sum(len(s.split()) for s in steps) <= cm.CARD_MAX_WORDS
    assert steps[0].startswith("Start on the side road") and steps[-1].startswith("Arrive at")
    assert "Keep going for 20 meters" not in " ".join(steps)       # short hop folded away
    assert "Oak 13 Lane" in " ".join(steps)              # every turn still named
    short = cm.card_steps(cl[:4] + cl[-1:])
    assert short == cm.card_steps(cl[:4] + cl[-1:], max_words=None)  # short routes untouched


def test_legs_fold_short_unnamed_pingpong_into_the_named_street():
    from ember_engine.core import cues as cm
    t = cm.shared.templates()
    legs = [
        {"street": "Skyway", "edges": [0], "fwd": [True], "nodes": [0, 1], "length_m": 300.0, "rise_m": 0.0},
        {"street": t["unnamed_street"], "edges": [1], "fwd": [True], "nodes": [1, 2], "length_m": 40.0, "rise_m": 1.0},
        {"street": "Skyway", "edges": [2], "fwd": [True], "nodes": [2, 3], "length_m": 200.0, "rise_m": 0.0},
        {"street": t["unnamed_street"], "edges": [3], "fwd": [True], "nodes": [3, 4], "length_m": 400.0, "rise_m": 0.0},
        {"street": "Skyway", "edges": [4], "fwd": [True], "nodes": [4, 5], "length_m": 100.0, "rise_m": 0.0},
    ]
    out = cm._merge_pingpong([dict(l) for l in legs], t)
    assert [l["street"] for l in out] == ["Skyway", t["unnamed_street"], "Skyway"]   # the 400 m side road stays
    assert out[0]["edges"] == [0, 1, 2] and out[0]["nodes"] == [0, 1, 2, 3] and out[0]["length_m"] == 540.0 and out[0]["rise_m"] == 1.0


def test_route_b_card_steps_reuse_the_shared_start(bundle):
    from ember_engine.core import cues as cm, plan as pm
    t = cm.shared.templates()
    assert "same_way" in t
    # two routes that share start + Pearson Rd, then split
    def cue(tpl, text, node, **v):
        return {"template": tpl, "text": text, "vars": v, "node": node}
    shared_part = [cue("start", t["start"].format(street="Bille Rd", direction="west"), 1, street="Bille Rd", direction="west"),
                   cue("keep_blocks", "", 1, street="Bille Rd", n=3),
                   cue("turn", t["turn"].format(side="left", street="Pearson Rd"), 2, side="left", street="Pearson Rd"),
                   cue("keep_blocks", "", 2, street="Pearson Rd", n=4)]
    a = shared_part + [cue("turn", t["turn"].format(side="right", street="Clark Rd"), 3, side="right", street="Clark Rd"),
                       cue("keep_blocks", "", 3, street="Clark Rd", n=2), cue("arrive", t["arrive"].format(refuge="the Walgreens lot"), 4, refuge="the Walgreens lot")]
    b = shared_part + [cue("turn", t["turn"].format(side="left", street="Elliott Rd"), 3, side="left", street="Elliott Rd"),
                       cue("keep_blocks", "", 3, street="Elliott Rd", n=5), cue("arrive", t["arrive"].format(refuge="the park"), 5, refuge="the park")]
    steps = cm.card_steps_after(a, b)
    assert steps[0] == "Same way as A until Pearson Rd."
    assert steps[1].startswith("Turn left onto Elliott Rd") and steps[-1] == "Arrive at the park."
    # nothing shared beyond the start: B printed in full
    assert cm.card_steps_after(a, [a[0], a[1]] + b[4:]) == cm.card_steps([a[0], a[1]] + b[4:])
