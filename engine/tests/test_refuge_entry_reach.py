"""Every refuge must be reachable by arrival: the phone's final cue lands on the route's last graph node (the chosen
entry point), and `Router.arrived` needs that point within 25 m of one of the refuge's entry points. 20 of 32 Paradise
refuges have their centroid 27-97 m from every entry point, so a plan that ended on the centroid would never arrive.

Runs over bundles/fake and every directory in EMBER_BUNDLES (colon-separated), e.g. a built Paradise bundle."""
import json
import math
import os
from pathlib import Path

import pytest

ARRIVAL_RADIUS_M = 25.0
ROOT = Path(__file__).resolve().parents[2]


def _haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _bundle_dirs():
    dirs = [ROOT / "bundles" / "fake"]
    dirs += [Path(p) for p in os.environ.get("EMBER_BUNDLES", "").split(":") if p]
    return [d for d in dirs if (d / "refuges.json").exists() and (d / "graph.json").exists()]


@pytest.mark.parametrize("bundle", _bundle_dirs(), ids=lambda d: d.name)
def test_every_refuge_has_an_entry_node_within_arrival_radius(bundle):
    nodes = {n["id"]: (n["lat"], n["lon"]) for n in json.load(open(bundle / "graph.json"))["nodes"]}
    refuges = json.load(open(bundle / "refuges.json"))["refuges"]
    assert refuges
    bad = []
    for r in refuges:
        entries = r.get("entry_points") or []
        routable = [e for e in entries if e.get("node") is not None]
        if not routable:
            bad.append(f"{r['id']}: no routable entry point")
            continue
        for e in routable:
            lat, lon = nodes[e["node"]]
            d = min(_haversine_m(lat, lon, x["lat"], x["lon"]) for x in entries)
            if d > ARRIVAL_RADIUS_M:
                bad.append(f"{r['id']}: entry node {e['node']} is {d:.0f} m from every entry point")
    assert not bad, "\n".join(bad)


@pytest.mark.parametrize("bundle", _bundle_dirs(), ids=lambda d: d.name)
def test_centroid_is_not_a_safe_arrival_target(bundle):
    """Documents why the phone must never aim at the centroid: for real bundles many centroids are outside the radius."""
    refuges = json.load(open(bundle / "refuges.json"))["refuges"]
    far = 0
    for r in refuges:
        lon, lat = r["centroid"]
        if all(_haversine_m(lat, lon, e["lat"], e["lon"]) > ARRIVAL_RADIUS_M for e in r.get("entry_points") or []):
            far += 1
    # No assertion on the count (bundle-dependent); the entry-node test above is the guarantee that matters.
    print(f"{bundle.name}: {far}/{len(refuges)} refuges have the centroid > {ARRIVAL_RADIUS_M:.0f} m from every entry point")
