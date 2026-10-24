import asyncio
import functools
import json

import httpx
import pytest
from conftest import FakeAnthropic, FakeApify, make_transport

import src.main as m
from src.extract import Extractor
from src.main import InputError, parse_input, run_pipeline

INPUT = {"fire_name": "Camp Fire", "year": 2018, "region_hint": "Butte County, California", "max_pages": 60}


def run(inp=INPUT, apify=None, anthropic=None, transport=None):
    async def go():
        async with httpx.AsyncClient(transport=transport or make_transport()) as http:
            return await run_pipeline(parse_input(inp), apify or FakeApify(),
                                      Extractor(client=anthropic or FakeAnthropic()), http, {}, 0)
    return asyncio.run(go())


def test_parse_input():
    p = parse_input({"fire_name": " Tubbs Fire ", "year": 2017})
    assert p["fire_name"] == "Tubbs Fire" and p["max_pages"] == 60 and p["region_hint"] is None
    assert parse_input({**INPUT, "perimeter_centroid": {"lat": 39.7, "lon": -121.5}})["perimeter_centroid"] == (39.7, -121.5)
    for bad in ({}, {"fire_name": "X"}, {"fire_name": "X", "year": 1700}, {"fire_name": "X", "year": 2018, "max_pages": 0},
                {"fire_name": "X", "year": 2018, "perimeter_centroid": {"lat": "a"}}):
        with pytest.raises(InputError):
            parse_input(bad)


def test_end_to_end_camp_fire():
    fc, summary = run()
    assert fc["type"] == "FeatureCollection"
    places = {f["properties"]["place"]: f for f in fc["features"]}
    # Kmart lot (article) and Kmart lot (reddit) are ~60 m apart -> one cluster with both sources
    assert len(fc["features"]) == 3
    kmart = next(f for f in fc["features"] if "Kmart" in f["properties"]["place"])
    assert kmart["properties"]["mentions"] == 2
    assert {q["url"] for q in kmart["properties"]["quotes"]} == {
        "https://www.example-news.com/2018/11/12/camp-fire-kmart-lot",
        "https://www.reddit.com/r/chico/comments/abc/camp_fire_kmart/",
    }
    assert "Lake Concow" in places and "Walgreens parking lot on Clark Road" in places
    # 50 km rule: Sacramento (~130 km from the Camp Fire centroid) is dropped
    assert all("Sacramento" not in p for p in places)
    assert summary["pipeline"]["outside_50km"] == 1
    # private residence named after a person is dropped
    assert summary["pipeline"]["dropped_private_places"] == 1

    for f in fc["features"]:
        assert set(f) == {"type", "geometry", "properties"} and f["type"] == "Feature"
        assert f["geometry"]["type"] == "Point"
        lon, lat = f["geometry"]["coordinates"]
        assert 39 < lat < 40.5 and -122 < lon < -121
        assert set(f["properties"]) == {"place", "kind", "quotes", "mentions"}
        assert f["properties"]["kind"] in ("parking lot", "lake", "field", "building", "road", "other")
        for q in f["properties"]["quotes"]:
            assert set(q) == {"text", "url", "outlet", "date"} and len(q["text"]) <= 240

    blob = json.dumps(fc)
    for name in ("Kennedy", "Lopez", "Gonzalez", "Maria", "throwaway_user_123", "Reporter Name"):
        assert name not in blob, name  # privacy rule: never who
    assert kmart["properties"]["kind"] == "parking lot"  # article kind wins; reddit typo kind became "other"

    assert summary["counts_by_kind"] == {"parking lot": 2, "lake": 1, "field": 0, "building": 0, "road": 0, "other": 0}
    assert summary["features"] == 3 and summary["mentions"] == 4
    assert summary["perimeter"]["centroid"] == {"lat": pytest.approx(39.75), "lon": pytest.approx(-121.55)}
    assert summary["pipeline"]["name_stripping"] == "spacy" and summary["errors"] == []


def test_perimeter_unavailable_skips_filter_and_notes_it():
    fc, summary = run(transport=make_transport(frap=500))
    assert summary["perimeter"]["centroid"] is None
    assert summary["perimeter"]["note"].startswith("perimeter filter skipped")
    assert any("Sacramento" in f["properties"]["place"] for f in fc["features"])  # no filter applied


def test_failures_never_fail_the_run():
    fc, summary = run(apify=FakeApify(fail={"website-content-crawler"}),
                      anthropic=FakeAnthropic(fail_marker="REDDIT-KMART"))
    assert fc == {"type": "FeatureCollection", "features": []}
    assert summary["pipeline"]["extract_errors"] == 1 and len(summary["errors"]) == 1


def test_main_writes_dataset_and_kv_store(tmp_path, monkeypatch):
    """Runs the real Actor glue against Apify local storage (no platform, no network)."""
    storage = tmp_path / "storage"
    kv = storage / "key_value_stores" / "default"
    kv.mkdir(parents=True)
    (kv / "INPUT.json").write_text(json.dumps(INPUT))
    monkeypatch.setenv("CRAWLEE_STORAGE_DIR", str(storage))
    monkeypatch.setenv("APIFY_LOCAL_STORAGE_DIR", str(storage))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(m, "_apify_call_actor", FakeApify())
    monkeypatch.setattr(m, "Extractor", lambda api_key=None: Extractor(client=FakeAnthropic()))
    monkeypatch.setattr(m, "run_pipeline", functools.partial(m.run_pipeline, geocode_interval_s=0))
    real_client = httpx.AsyncClient
    monkeypatch.setattr(m.httpx, "AsyncClient", lambda **kw: real_client(transport=make_transport(), **kw))

    with pytest.raises(SystemExit) as exc:  # Actor exits the process when the run ends
        asyncio.run(m.main())
    assert exc.value.code == 0

    out = json.loads((kv / "OUTPUT").read_text())
    assert out["type"] == "FeatureCollection" and len(out["features"]) == 3
    summary = json.loads(next(kv.glob("summary.json*")).read_text())
    assert summary["features"] == 3
    assert list(kv.glob("evidence.geojson*"))
    items = sorted((storage / "datasets" / "default").glob("0*.json"))
    assert len(items) == 3
    first = json.loads(items[0].read_text())
    assert first["type"] == "Feature" and "quotes" in first["properties"]
    cache_files = list((storage / "key_value_stores").glob("*geocode*/*"))
    assert cache_files, "geocode cache persisted in the named store"
