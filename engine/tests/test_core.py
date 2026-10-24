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
