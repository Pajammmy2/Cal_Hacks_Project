"""Seeded-random fuzz for the engine router: random origins/profiles/fire bearings/blocked sets.
Invariants checked every call: no exception, no blocked edge in a returned route, routes are
internally connected and start at the origin, non-empty results are sorted by (time_s, -score),
and a refuge on the fire side is never offered."""
import json
import random
from pathlib import Path

import pytest

from ember_engine.core import geo, router, shared

REPO = Path(__file__).resolve().parents[2]
BUNDLE = REPO / "bundles" / "fake"


@pytest.fixture(scope="module")
def bundle():
    return router.load_bundle(BUNDLE)


PROFILES = ["manual_chair", "manual_chair_pushed", "power_chair", "walker", "bedbound"]


def _assert_choice(graph, origin, c, blocked, fire_bearing, perimeter):
    route = c["route"]
    assert route["nodes"][0] == origin, "route must start at the requested origin"
    assert route["nodes"][-1] in [ep["node"] for ep in c["refuge"]["entry_points"]], "route must end at an entry point"
    assert not blocked.intersection(route["edges"]), "blocked edge routed"
    node_set = set(route["nodes"])
    for ei in route["edges"]:
        e = graph.edges[ei]
        assert e["a"] in node_set and e["b"] in node_set, "route edge detached from route nodes"
    assert route["time_s"] >= 0   # 0 is legal: the origin can already be a refuge entry point
    assert router.fire_side_ok(graph, origin, c["refuge"], fire_bearing, perimeter)


def test_choose_fuzz(bundle):
    graph, refuges = bundle
    rng = random.Random(0xE4BE2)
    nodes = list(range(len(graph.lat)))
    edges = list(range(len(graph.edges)))
    runs = 0
    for _ in range(600):
        key = rng.choice(PROFILES)
        prof = router.Profile(key, rng.choice([0, 25, 50, 75, 100]))
        origin = rng.choice(nodes)
        fire = rng.choice([None, rng.uniform(0, 360)])
        blocked = frozenset(rng.sample(edges, rng.choice([0, 0, 0, 1, 2, 5, 20, 80])))
        prefer = rng.choice([None, rng.uniform(0, 360)])
        out = router.choose(graph, refuges, prof, origin, fire, None, blocked, prefer=prefer)
        runs += 1
        if prefer is None:   # prefer_heading intentionally re-orders similar-time routes
            times = [(c["route"]["time_s"], -c["refuge"]["score"]) for c in out]
            assert times == sorted(times)
        for c in out:
            _assert_choice(graph, origin, c, blocked, fire, None)
    assert runs == 600


def test_choose_never_routes_through_single_edge_block(bundle):
    """Block each edge of route A once; the re-plan must never reuse it (pregen replan contract)."""
    graph, refuges = bundle
    prof = router.Profile("manual_chair")
    for origin in (23, 112, 60):
        base = router.choose(graph, refuges, prof, origin)
        if not base:
            continue
        a = base[0]
        for ei in a["route"]["edges"]:
            for c in router.choose(graph, refuges, prof, origin, None, None, frozenset({ei})):
                assert ei not in c["route"]["edges"], f"blocked edge {ei} still routed from {origin}"


def test_fire_side_filter_respected_for_all_bearings(bundle):
    graph, refuges = bundle
    prof = router.Profile("walker")
    for bearing in range(0, 360, 15):
        for c in router.choose(graph, refuges, prof, 112, float(bearing), None):
            assert router.fire_side_ok(graph, 112, c["refuge"], float(bearing), None)


def test_blocked_to_isolation_gives_empty_not_crash(bundle):
    """Every passable edge of every node adjacent to the origin blocked -> [] not an exception."""
    graph, refuges = bundle
    prof = router.Profile("manual_chair")
    origin = 112
    adjacent = {ei for ei, _, _ in graph.adj[origin]}
    out = router.choose(graph, refuges, prof, origin, None, None, frozenset(adjacent))
    assert out == []
