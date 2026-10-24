"""Secondary (evidence-gated) validation checks, without any network."""
import sys
from pathlib import Path

from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import validate  # noqa: E402
from ember_engine import util  # noqa: E402

PROJ = util.Projector(-121.61, 39.77)
STORE = (-121.6118, 39.7699)


def _check():
    return {"key": "w", "label": "Walgreens lot", "expect_top": True, "kind": "parking", "secondary": True,
            "radius_m": 80.0, "pick": "nearest", "evidence_radius_m": 300.0, "how": "test",
            "point": STORE, "_store_geom_m": PROJ.geom_fwd(Point(*STORE)), "store_note": "no lot in OSM"}


def test_secondary_pending_without_evidence():
    res = validate.run_checks([_check()], [], [], PROJ, None)[0]
    assert res["status"] == "PENDING" and not res["counted"]


def test_secondary_dropped_when_evidence_never_mentions_it():
    far = [(-121.55, 39.80, {})]
    res = validate.run_checks([_check()], [], [], PROJ, far)[0]
    assert res["status"] == "DROPPED" and not res["counted"]


def test_secondary_counts_and_fails_when_evidence_confirms_but_scorer_misses():
    near = [(STORE[0] + 0.001, STORE[1], {})]          # ~85 m away
    res = validate.run_checks([_check()], [], [], PROJ, near)[0]
    assert res["status"] == "FAIL" and res["counted"]


def test_primary_checks_always_count():
    c = _check()
    c.pop("secondary")
    res = validate.run_checks([c], [], [], PROJ, None)[0]
    assert res["status"] == "FAIL" and res["counted"]
