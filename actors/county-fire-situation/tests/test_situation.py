"""Run-level behaviour: exact output shape, and per-source isolation (a broken source never fails the run)."""

import asyncio
import json

import httpx
import pytest
from conftest import make_transport

from src import situation
from src.main import InputError, parse_input
from src.situation import build_situation

KEYS = ["county", "fetched_at", "incidents", "closures", "zones", "outages", "errors"]


def build(county, **kw):
    async def go():
        async with httpx.AsyncClient(transport=make_transport(**kw)) as c:
            return await build_situation(county, c)
    return asyncio.run(go())


def test_parse_input():
    assert parse_input({"county": "butte", "state": "CA"}) == "Butte"
    assert parse_input({"county": "Butte"}) == "Butte"  # state defaults to CA
    for bad in ({"county": "Butte", "state": "OR"}, {"state": "CA"}, {"county": "Gotham", "state": "CA"}):
        with pytest.raises(InputError):
            parse_input(bad)


def test_output_shape_butte(fixed_now):
    s = build("Butte")
    assert list(s) == KEYS
    assert s["county"] == "Butte" and s["fetched_at"].endswith("Z")
    assert len(s["incidents"]) == 1 and len(s["closures"]) >= 3 and len(s["outages"]) == 2
    assert s["zones"] == []
    assert s["errors"] == [{"source": "genasys", "level": "notice",
                            "message": "Butte County publishes no zones in Genasys Protect"}]
    for c in s["closures"]:
        assert {"lat", "lon", "road", "kind", "since"} <= set(c)
    for o in s["outages"]:
        assert {"area", "kind", "est_restore"} <= set(o) and o["kind"] in ("psps", "unplanned")
    json.dumps(s)


def test_output_shape_tulare_zones(fixed_now):
    s = build("Tulare")
    assert len(s["zones"]) == 8 and s["errors"] == []
    for z in s["zones"]:
        assert {"id", "status", "updated"} <= set(z) and z["status"] in ("normal", "warning", "order")


@pytest.mark.parametrize("source,key,county", [
    ("genasys", "zones", "Tulare"),
    ("caltrans", "closures", "Butte"),
    ("calfire", "incidents", "Butte"),
    ("pge", "outages", "Butte"),
])
def test_one_broken_source_yields_empty_array_and_error_note(fixed_now, source, key, county):
    healthy = build(county)
    broken = build(county, broken={source})
    assert healthy[key] and broken[key] == []
    errs = [e for e in broken["errors"] if e["level"] == "error"]
    assert [e["source"] for e in errs] == [source]
    for other in ("incidents", "closures", "zones", "outages"):
        if other != key:
            assert broken[other] == healthy[other]  # other sources unaffected


def test_broken_source_url_via_env(fixed_now, monkeypatch):
    """The DoD check: run with one source URL broken on purpose."""
    monkeypatch.setenv("EMBER_CALTRANS_LCS_URL", "https://broken.invalid/d{district}/lcs.json")
    s = build("Butte")
    assert s["closures"] == []
    assert any(e["source"] == "caltrans" and e["level"] == "error" and "ConnectError" in e["message"]
               for e in s["errors"])
    assert len(s["incidents"]) == 1 and len(s["outages"]) == 2


def test_all_sources_broken_still_returns_record(fixed_now):
    s = build("Tulare", broken={"genasys", "caltrans", "calfire", "pge"})
    assert list(s) == KEYS and all(s[k] == [] for k in ("incidents", "closures", "zones", "outages"))
    assert sorted(e["source"] for e in s["errors"]) == ["calfire", "caltrans", "genasys", "pge"]


def test_hanging_source_times_out(fixed_now, monkeypatch):
    async def hang(client, county):
        await asyncio.sleep(10)

    monkeypatch.setattr(situation, "SOURCE_TIMEOUT_S", 0.05)
    monkeypatch.setattr(situation, "SOURCES", [("incidents", "calfire", hang)] + situation.SOURCES[:2])
    s = build("Butte")
    assert s["incidents"] == [] and any("timed out" in e["message"] for e in s["errors"])


DRIVER = """
import asyncio, sys, httpx
sys.path[:0] = [{root!r}, {tests!r}]
import conftest
import src.main as m
from src import caltrans, situation
caltrans.time.time = lambda: conftest.NOW
real_build = situation.build_situation
async def build_with_mock(county):
    async with httpx.AsyncClient(transport=conftest.make_transport()) as c:
        return await real_build(county, c)
m.build_situation = build_with_mock
asyncio.run(m.main())
"""


def _actor_run(tmp_path, monkeypatch, inp, env=None):
    """Runs the real Actor entry point in a fresh process (like the platform) on local storage."""
    import os
    import subprocess
    import sys

    from conftest import ROOT

    storage = tmp_path / "storage"
    kv = storage / "key_value_stores" / "default"
    kv.mkdir(parents=True)
    (kv / "INPUT.json").write_text(json.dumps(inp))
    driver = tmp_path / "driver.py"
    driver.write_text(DRIVER.format(root=str(ROOT), tests=str(ROOT / "tests")))
    proc = subprocess.run([sys.executable, str(driver)], cwd=tmp_path, capture_output=True, text=True, timeout=120,
                          env={**os.environ, "CRAWLEE_STORAGE_DIR": str(storage), **(env or {})})
    return proc.returncode, storage, kv


def test_main_pushes_one_item_and_output(tmp_path, monkeypatch):
    code, storage, kv = _actor_run(tmp_path, monkeypatch, {"county": "Butte", "state": "CA"},
                                   env={"EMBER_PGE_OUTAGE_URL": "https://broken.invalid/arcgis"})  # one source broken
    assert code == 0  # run succeeds
    items = sorted((storage / "datasets" / "default").glob("0*.json"))
    assert len(items) == 1
    item = json.loads(items[0].read_text())
    out = json.loads((kv / "OUTPUT").read_text())
    assert item == out and list(out) == KEYS
    assert out["outages"] == [] and any(e["source"] == "pge" and e["level"] == "error" for e in out["errors"])
    assert out["incidents"] and out["closures"]


def test_main_bad_input_fails(tmp_path, monkeypatch):
    code, _, _ = _actor_run(tmp_path, monkeypatch, {"county": "Gotham", "state": "CA"})
    assert code == 1
