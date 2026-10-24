"""Bundle-build unit tests: score terms, graph build from synthetic OSM, vision downgrade-only rules."""
import copy
import json
import math

import pytest
from shapely.geometry import Polygon, box

from ember_engine import graph_build, refuges, scoring, util, vision
from ember_engine.core import geo

LAT0, LON0 = 39.75, -121.60
M_PER_DEG = geo.EARTH_R * math.pi / 180.0        # same sphere as the graph's haversine lengths
DLAT_M = 1 / M_PER_DEG
DLON_M = 1 / (M_PER_DEG * math.cos(math.radians(LAT0)))


# ---- scoring terms -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("d,want", [(10, 0.0), (15, 0.0), (30, 0.5), (45, 1.0), (60, 1.0)])
def test_f_heat(d, want):
    assert scoring.f_heat(d) == pytest.approx(want)


@pytest.mark.parametrize("a,want", [(1000, 0.0), (2000, 0.0), (6000, 0.5), (10000, 1.0), (20000, 1.0)])
def test_f_area(a, want):
    assert scoring.f_area(a) == pytest.approx(want)


def test_exclusion_below_15m():
    assert scoring.excluded(14.9)
    assert not scoring.excluded(15.0)


def test_base_score_weights():
    t = scoring.make_terms(d_fuel_m=30, a_clear_m2=6000, f_access=0.5, f_shelter=1.0, f_water=0.0)
    assert t["base_score"] == pytest.approx(40 * 0.5 + 20 * 0.5 + 20 * 0.5 + 10 * 1.0)
    assert t["vision_penalty"] == 0.0


def test_classify_thresholds():
    assert refuges.classify({"amenity": "parking"}, 3999) is None
    assert refuges.classify({"amenity": "parking"}, 4000) == "parking"
    assert refuges.classify({"landuse": "meadow"}, 9999) is None
    assert refuges.classify({"landuse": "meadow"}, 10000) == "meadow"
    assert refuges.classify({"leisure": "pitch"}, 300) == "pitch"
    assert refuges.classify({"natural": "water", "water": "pond"}, 1e5) is None
    assert refuges.classify({"natural": "water", "water": "reservoir"}, 1e5) == "water"
    assert refuges.classify({"building": "school"}, 1999) is None
    assert refuges.classify({"building": "school"}, 2000) == "building"            # material absent -> ok
    assert refuges.classify({"building": "school", "building:material": "wood"}, 5000) is None
    assert refuges.classify({"building": "school", "building:material": "brick"}, 5000) == "building"
    assert refuges.classify({"building": "house"}, 5000) is None


def test_f_access_rules():
    e = lambda **kw: dict({"steps": False, "curb_cut": True, "driveway": False}, **kw)
    assert refuges.f_access([e()], fenced=False) == 1.0
    assert refuges.f_access([e(curb_cut="unknown")], fenced=False) == 0.5
    assert refuges.f_access([e(curb_cut=False, driveway=True)], fenced=False) == 1.0
    assert refuges.f_access([e(steps=True)], fenced=False) == 0.0
    assert refuges.f_access([e()], fenced=True) == 0.0
    assert refuges.f_access([], fenced=False) == 0.0


def test_shelter_and_water():
    assert refuges.f_shelter("building", {}, 3000) == 1.0
    assert refuges.f_shelter("parking", {}, 4000) == 0.5
    assert refuges.f_shelter("pitch", {"surface": "asphalt"}, 5000) == 0.5
    assert refuges.f_shelter("pitch", {"surface": "grass"}, 5000) == 0.0
    assert refuges.f_water("water", {}) == 1.0
    assert refuges.f_water("swimming_pool", {}) == 1.0
    assert refuges.f_water("swimming_pool", {"access": "private"}) == 0.0
    assert refuges.f_water("park", {}) == 0.0


def test_score_candidates_end_to_end():
    """A 120 x 120 m lot with a street along its south edge and a building 30 m north of the usable centre."""
    from ember_engine import fuel as fuelmod
    proj = util.Projector(LON0, LAT0)
    lot = box(LON0, LAT0, LON0 + 120 * DLON_M, LAT0 + 120 * DLAT_M)
    bld = box(LON0, LAT0 + 150 * DLAT_M, LON0 + 120 * DLON_M, LAT0 + 165 * DLAT_M)   # 1800 m2: below the building-candidate floor
    nodes = {1: (LAT0 - 5 * DLAT_M, LON0, {}), 2: (LAT0 - 5 * DLAT_M, LON0 + 120 * DLON_M, {})}
    ways = [{"id": 10, "nodes": [1, 2], "tags": {"highway": "residential", "name": "Clark Rd"}}]
    graph, _ = graph_build.build_graph(nodes, ways, lambda lo, la: [500.0] * len(lo))
    feats = [{"osm_type": "way", "id": 1, "tags": {"amenity": "parking"}, "geom": lot},
             {"osm_type": "way", "id": 2, "tags": {"building": "retail", "name": "Kmart"}, "geom": bld}]
    ctx = refuges.Context(proj, graph, feats)
    fuel = fuelmod.FuelIndex(proj, [(("way", 2), bld)])
    cands = refuges.candidates(feats, (LON0 - 0.01, LAT0 - 0.01, LON0 + 0.01, LAT0 + 0.01), proj)
    kept, dropped = refuges.score_candidates(cands, ctx, fuel)
    assert not dropped and len(kept) == 1
    r = kept[0]
    t = r["terms"]
    assert r["name"] == "the Kmart lot" or r["name"].startswith("the parking lot on")
    assert t["A_clear_m2"] == pytest.approx(100 * 100, rel=0.02)            # 10 m inner buffer
    assert t["f_access"] == 1.0 and r["entry_points"]
    assert t["f_shelter"] == 0.5 and t["f_water"] == 0.0
    assert t["d_fuel_m"] > 30                                                 # building is north of the lot
    assert r["score"] == t["base_score"] == scoring.base_score(t)


# ---- graph build ---------------------------------------------------------------------------------------------

def _line(n_m, step_m=10.0, tags_at=None):
    """OSM nodes along a straight east-west line, one every step_m metres."""
    tags_at = tags_at or {}
    k = int(n_m / step_m)
    return {100 + i: (LAT0, LON0 + i * step_m * DLON_M, tags_at.get(i, {})) for i in range(k + 1)}


def _elev_east_slope(lons, lats):
    # +5 m per 100 m eastward
    return [(lo - LON0) / DLON_M * 0.05 + 500.0 for lo in lons]


def test_split_every_50m_equal_pieces():
    nodes = _line(130)
    ways = [{"id": 1, "nodes": sorted(nodes), "tags": {"highway": "residential", "name": "A St"}}]
    g, _ = graph_build.build_graph(nodes, ways, _elev_east_slope)
    assert len(g["edges"]) == 3                                                # ceil(130 / 50)
    lens = [e["length_m"] for e in g["edges"]]
    assert all(L <= 50.0 for L in lens)
    assert max(lens) - min(lens) < 0.02
    assert sum(lens) == pytest.approx(130.0, rel=1e-3)
    assert [n["id"] for n in g["nodes"]] == list(range(len(g["nodes"])))


def test_intersection_is_a_node():
    nodes = _line(80)
    nodes[900] = (LAT0 + 40 * DLAT_M, LON0 + 40 * DLON_M, {})
    ways = [{"id": 1, "nodes": sorted(k for k in nodes if k < 900), "tags": {"highway": "residential"}},
            {"id": 2, "nodes": [104, 900], "tags": {"highway": "footway"}}]
    g, _ = graph_build.build_graph(nodes, ways, _elev_east_slope)
    deg = {}
    for e in g["edges"]:
        deg[e["a"]] = deg.get(e["a"], 0) + 1
        deg[e["b"]] = deg.get(e["b"], 0) + 1
    assert 3 in deg.values()                                                   # node 104 joins three edges


def _elev_canyon(lons, lats):
    # flat at 500 m with a 40 m deep gorge between 50 m and 150 m east
    out = []
    for lo in lons:
        x = (lo - LON0) / DLON_M
        out.append(460.0 if 50.0 < x < 150.0 else 500.0)
    return out


def test_bridge_deck_ignores_ground_under_it():
    nodes = _line(200)
    ways = [{"id": 1, "nodes": sorted(nodes), "tags": {"highway": "residential", "bridge": "yes"}}]
    g, stats = graph_build.build_graph(nodes, ways, _elev_canyon)
    assert stats["deck_nodes_interpolated"] > 0
    assert all(abs(e["grade_pct"]) < 0.01 for e in g["edges"])
    plain = [{"id": 1, "nodes": sorted(nodes), "tags": {"highway": "residential"}}]
    g2, _ = graph_build.build_graph(nodes, plain, _elev_canyon)
    assert max(abs(e["grade_pct"]) for e in g2["edges"]) > 10


def test_signed_grade():
    nodes = _line(40)
    ways = [{"id": 1, "nodes": sorted(nodes), "tags": {"highway": "residential"}}]
    g, _ = graph_build.build_graph(nodes, ways, _elev_east_slope)
    e = g["edges"][0]
    a, b = g["nodes"][e["a"]], g["nodes"][e["b"]]
    assert b["lon"] > a["lon"]
    assert e["grade_pct"] == pytest.approx(5.0, abs=0.05)                      # uphill eastward, a->b
    rev = [{"id": 1, "nodes": sorted(nodes, reverse=True), "tags": {"highway": "residential"}}]
    g2, _ = graph_build.build_graph(nodes, rev, _elev_east_slope)
    assert g2["edges"][0]["grade_pct"] == pytest.approx(-5.0, abs=0.05)


def _one_edge(way_tags, node_tags=None):
    nodes = _line(20, tags_at={1: node_tags} if node_tags else None)
    g, _ = graph_build.build_graph(nodes, [{"id": 1, "nodes": sorted(nodes), "tags": way_tags}],
                                   lambda lo, la: [0.0] * len(lo))
    assert len(g["edges"]) == 1
    return g["edges"][0]


def test_steps_mapping():
    e = _one_edge({"highway": "steps", "step_count": "12"})
    assert e["steps"] is True and e["step_count"] == 12 and e["road_class"] == "steps"
    e = _one_edge({"highway": "footway", "incline": "up", "step_count": "3"})
    assert e["steps"] is True and e["step_count"] == 3
    e = _one_edge({"highway": "footway", "incline": "up"})
    assert e["steps"] is False and e["step_count"] is None


def test_curb_cut_mapping():
    assert _one_edge({"highway": "residential"})["curb_cut"] is True                       # no kerb involved
    assert _one_edge({"highway": "footway"}, {"kerb": "lowered"})["curb_cut"] is True
    assert _one_edge({"highway": "footway"}, {"kerb": "flush"})["curb_cut"] is True
    assert _one_edge({"highway": "footway"}, {"kerb": "no"})["curb_cut"] is True
    assert _one_edge({"highway": "footway"}, {"kerb": "raised"})["curb_cut"] is False
    assert _one_edge({"highway": "footway", "wheelchair": "no"})["curb_cut"] is False
    # a lowered/flush kerb at the crossing is the way across, even if the other side is raised
    assert _one_edge({"highway": "footway"}, {"kerb": "raised"})["curb_cut"] is False
    nodes = _line(30, tags_at={0: {"kerb": "raised"}, 3: {"kerb": "lowered"}})
    g, _ = graph_build.build_graph(nodes, [{"id": 1, "nodes": sorted(nodes), "tags": {"highway": "footway"}}],
                                   lambda lo, la: [0.0] * len(lo))
    assert g["edges"][0]["curb_cut"] is True
    nodes = _line(30, tags_at={0: {"kerb": "raised"}, 3: {"sloped_curb": "yes"}})
    g, _ = graph_build.build_graph(nodes, [{"id": 1, "nodes": sorted(nodes), "tags": {"highway": "footway"}}],
                                   lambda lo, la: [0.0] * len(lo))
    assert g["edges"][0]["curb_cut"] is True
    assert _one_edge({"highway": "footway", "footway": "crossing"})["curb_cut"] == "unknown"
    assert _one_edge({"highway": "footway"}, {"highway": "crossing"})["curb_cut"] == "unknown"
    assert _one_edge({"highway": "footway"}, {"barrier": "kerb"})["curb_cut"] == "unknown"
    assert _one_edge({"highway": "footway", "footway": "crossing", "wheelchair": "yes"})["curb_cut"] is True
    assert _one_edge({"highway": "footway"}, {"highway": "crossing", "kerb": "lowered"})["curb_cut"] is True
    # a road running through a crossing node does not climb a kerb
    assert _one_edge({"highway": "residential"}, {"highway": "crossing"})["curb_cut"] is True


def test_sidewalk_surface_driveway_mapping():
    assert _one_edge({"highway": "footway"})["sidewalk"] is True
    assert _one_edge({"highway": "residential", "sidewalk": "both"})["sidewalk"] is True
    assert _one_edge({"highway": "residential", "sidewalk": "no"})["sidewalk"] is False
    assert _one_edge({"highway": "residential", "sidewalk": "none"})["sidewalk"] is False
    assert _one_edge({"highway": "primary"})["sidewalk"] is False
    assert _one_edge({"highway": "residential", "surface": "asphalt"})["surface"] == "paved"
    assert _one_edge({"highway": "residential", "surface": "gravel"})["surface"] == "unpaved"
    assert _one_edge({"highway": "residential"})["surface"] == "unknown"
    assert _one_edge({"highway": "service", "service": "driveway"})["driveway"] is True
    assert _one_edge({"highway": "service"})["driveway"] is False


def test_motorway_and_trunk_dropped():
    nodes = _line(20)
    ways = [{"id": 1, "nodes": sorted(nodes), "tags": {"highway": "motorway"}},
            {"id": 2, "nodes": sorted(nodes), "tags": {"highway": "trunk"}}]
    g, _ = graph_build.build_graph(nodes, ways, lambda lo, la: [0.0] * len(lo))
    assert g["edges"] == [] and g["nodes"] == []


def test_edge_fields_match_contract():
    e = _one_edge({"highway": "residential", "name": "Clark Rd"})
    assert set(e) == {"a", "b", "length_m", "grade_pct", "surface", "steps", "step_count", "curb_cut", "road_class",
                      "sidewalk", "name", "driveway"}


# ---- vision pass: downgrade only -----------------------------------------------------------------------------

def _refuge(score_terms):
    t = scoring.make_terms(**score_terms)
    return {"id": "r_x", "name": "the lot", "kind": "parking", "score": t["base_score"], "terms": t,
            "claude": None, "flag": None, "thumb": "thumbs/r_x.jpg", "entry_points": []}


ANSWERS = [
    {"fuel_ring": 0, "clear_area_m2_est": 99999, "entry_wheelchair": "yes", "hazards": [], "confidence": 1.0,
     "reason": "Open lot."},
    {"fuel_ring": 3, "clear_area_m2_est": 100, "entry_wheelchair": "no", "hazards": ["trees"], "confidence": 0.2,
     "reason": "x" * 500},
    {"fuel_ring": 2, "clear_area_m2_est": 3000, "entry_wheelchair": "unsure", "hazards": [], "confidence": 0.7,
     "reason": "Trees on two sides."},
    {"fuel_ring": 1, "clear_area_m2_est": 5000, "entry_wheelchair": "no", "hazards": [], "confidence": 0.49,
     "reason": "Kerb at the only entrance."},
]


@pytest.mark.parametrize("raw", ANSWERS)
@pytest.mark.parametrize("terms", [dict(d_fuel_m=60, a_clear_m2=12000, f_access=1.0, f_shelter=0.5, f_water=0.0),
                                   dict(d_fuel_m=20, a_clear_m2=2500, f_access=0.0, f_shelter=0.0, f_water=1.0)])
def test_vision_never_raises(raw, terms):
    r = _refuge(terms)
    before = r["score"]
    v = vision.validate(raw)
    vision.apply(r, v)
    assert r["score"] <= before
    assert 0.0 <= r["terms"]["vision_penalty"] <= 30.0
    assert r["score"] == pytest.approx(r["terms"]["base_score"] - r["terms"]["vision_penalty"], abs=0.051)
    assert len(r["claude"]["reason"]) <= 200
    assert set(r["claude"]) == {"fuel_ring", "clear_area_m2", "entry", "hazards", "confidence", "reason"}
    if raw["entry_wheelchair"] == "no":
        assert r["terms"]["f_access"] == 0.0
    assert (r["flag"] == "unsure") == (raw["confidence"] < 0.5)
    # applying again (a re-run) never raises either
    again = r["score"]
    vision.apply(r, vision.validate(ANSWERS[0]))
    assert r["score"] <= again


def test_vision_penalty_rule():
    r = _refuge(dict(d_fuel_m=60, a_clear_m2=12000, f_access=1.0, f_shelter=0.5, f_water=0.0))   # 85
    vision.apply(r, vision.validate(dict(ANSWERS[2])))
    assert r["terms"]["vision_penalty"] == 20.0 and r["score"] == 65.0
    r = _refuge(dict(d_fuel_m=60, a_clear_m2=12000, f_access=1.0, f_shelter=0.5, f_water=0.0))
    vision.apply(r, vision.validate(dict(ANSWERS[1])))
    assert r["terms"]["f_access"] == 0.0 and r["terms"]["base_score"] == 65.0
    assert r["terms"]["vision_penalty"] == 30.0 and r["score"] == 35.0 and r["flag"] == "unsure"


def test_vision_run_with_mocked_claude(tmp_path):
    """run() over a tiny bundle with a fake Claude: only the top N are touched, nothing goes up."""
    refs = []
    for i in range(45):
        r = _refuge(dict(d_fuel_m=15 + i, a_clear_m2=2000 + 200 * i, f_access=1.0, f_shelter=0.5, f_water=0.0))
        r["id"] = f"r_{i}"
        r["thumb"] = f"thumbs/r_{i}.jpg"
        refs.append(r)
    (tmp_path / "thumbs").mkdir()
    for r in refs:
        (tmp_path / r["thumb"]).write_bytes(b"\xff\xd8fakejpeg")
    util.write_json(tmp_path / "refuges.json", {"generated_at": "x", "refuges": refs})
    util.write_json(tmp_path / "manifest.json", {"sources": {"thumbs": "usgs-imagery: 45"}})
    before = {r["id"]: r["score"] for r in refs}
    calls = []

    def fake_ask(client, refuge, thumb, street=None):
        calls.append(refuge["id"])
        return vision.validate(ANSWERS[len(calls) % len(ANSWERS)])

    summary = vision.run(tmp_path, client=object(), ask=fake_ask)
    assert len(calls) == vision.TOP_N and summary["annotated"] == vision.TOP_N
    after = util.read_json(tmp_path / "refuges.json")["refuges"]
    for r in after:
        assert r["score"] <= before[r["id"]]
    untouched = [r for r in after if r["claude"] is None]
    assert len(untouched) == 5
    scores = [r["score"] for r in after]
    assert scores == sorted(scores, reverse=True)


def test_vision_schema_is_exact():
    assert vision.SYSTEM_PROMPT == ("You assess wildfire refuge candidates for people in wheelchairs. Report only "
                                    "what is visible. Never say a place is safe. Output JSON matching the schema.")
    assert set(vision.SCHEMA["required"]) == {"fuel_ring", "clear_area_m2_est", "entry_wheelchair", "hazards",
                                              "confidence", "reason"}
    assert vision.SCHEMA["properties"]["fuel_ring"]["enum"] == [0, 1, 2, 3]


def test_ask_claude_request_shape():
    """ask_claude sends the exact system prompt + JSON schema and validates/clamps the reply (no network)."""
    import json as _json
    from types import SimpleNamespace
    seen = {}

    class FakeMessages:
        def create(self, **kw):
            seen.update(kw)
            reply = dict(ANSWERS[1], confidence=7, fuel_ring=3)
            return SimpleNamespace(stop_reason="end_turn",
                                   content=[SimpleNamespace(type="text", text=_json.dumps(reply))])

    r = _refuge(dict(d_fuel_m=60, a_clear_m2=12000, f_access=1.0, f_shelter=0.5, f_water=0.0))
    v = vision.ask_claude(SimpleNamespace(messages=FakeMessages()), r, b"\xff\xd8jpeg")
    assert seen["system"] == vision.SYSTEM_PROMPT
    assert seen["model"] == vision.model_name()
    assert seen["output_config"]["format"] == {"type": "json_schema", "schema": vision.SCHEMA}
    assert seen["messages"][0]["content"][0]["type"] == "image"
    assert v["confidence"] == 1.0 and len(v["reason"]) == 200


def test_extra_candidates_require_review_and_polygons(tmp_path):
    from ember_engine import osm
    poly = {"type": "Polygon", "coordinates": [[[0, 0], [0.001, 0], [0.001, 0.001], [0, 0.001], [0, 0]]]}
    ok = tmp_path / "ok.geojson"
    ok.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"amenity": "parking", "name": "Lot", "reviewed_by": "A", "note": "x"},
         "geometry": poly}]}))
    feats = osm.load_extra_candidates(ok)
    assert feats[0]["tags"] == {"amenity": "parking", "name": "Lot"} and feats[0]["osm_type"] == "local"
    unreviewed = tmp_path / "bad.geojson"
    unreviewed.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"amenity": "parking"}, "geometry": poly}]}))
    with pytest.raises(ValueError, match="reviewed_by"):
        osm.load_extra_candidates(unreviewed)
    point = tmp_path / "pt.geojson"
    point.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"amenity": "parking", "reviewed_by": "A"},
         "geometry": {"type": "Point", "coordinates": [0, 0]}}]}))
    with pytest.raises(ValueError, match="polygons"):
        osm.load_extra_candidates(point)
