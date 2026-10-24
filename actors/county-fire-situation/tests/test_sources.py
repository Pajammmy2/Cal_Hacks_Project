import asyncio

import httpx
import pytest
from conftest import NOW, lcs_feed, load, make_transport

from src import caltrans, calfire, genasys, pge
from src.common import in_county, counties, iso_utc, resolve_county


def run(coro_fn, county, **kw):
    async def go():
        async with httpx.AsyncClient(transport=make_transport(**kw)) as c:
            return await coro_fn(c, county)
    return asyncio.run(go())


# ------------------------------------------------------------------ common

def test_resolve_county_and_table():
    assert resolve_county("butte") == "Butte" and resolve_county("Butte County") == "Butte"
    assert resolve_county(" san luis obispo ") == "San Luis Obispo"
    assert resolve_county("Gotham") is None
    assert len(counties()) == 58
    assert counties()["Butte"]["caltrans_districts"] == [3] and counties()["Kern"]["caltrans_districts"] == [6, 9]
    assert in_county(-121.62, 39.76, counties()["Butte"]) and not in_county(-122.05, 40.12, counties()["Butte"])


def test_iso_utc():
    assert iso_utc("1792813255") == "2026-10-24T03:40:55Z"  # 20:40:55 PDT on Oct 23
    assert iso_utc(1792823400000) == "2026-10-24T06:30:00Z"
    assert iso_utc("2026-10-24T01:29:33Z") == "2026-10-24T01:29:33Z"
    assert iso_utc("") is None and iso_utc(None) is None


# ------------------------------------------------------------------ CAL FIRE

def test_calfire_filters_county_and_final():
    items, notes = run(calfire.fetch_incidents, "Butte")
    assert notes == [] and len(items) == 1
    inc = items[0]
    assert inc["name"] == "Example Fire" and inc["acres"] == 1200.0 and inc["containment"] == 35.0
    assert inc["updated"] == "2026-10-23T20:00:00Z" and inc["lat"] == 39.81 and inc["lon"] == -121.43
    plumas, _ = run(calfire.fetch_incidents, "Plumas")  # multi-county "Butte, Plumas"
    assert [i["id"] for i in plumas] == ["test-butte-1"]
    real = load("calfire_list.json")[0]
    other, _ = run(calfire.fetch_incidents, real["County"].split(",")[0])
    assert any(i["id"] == real["UniqueId"] for i in other)


# ------------------------------------------------------------------ Caltrans

def test_caltrans_active_rules():
    feed = {r["lcs"]["index"]: r["lcs"]["closure"] for r in lcs_feed()["data"]}
    assert caltrans.is_active(feed["A-full-1097"], NOW)
    assert caltrans.is_active(feed["B-lane-window"], NOW)
    assert not caltrans.is_active(feed["C-cancelled"], NOW)
    assert not caltrans.is_active(feed["D-lifted"], NOW)
    assert not caltrans.is_active(feed["E-future"], NOW)
    assert caltrans.is_active(feed["F-indefinite"], NOW)


def test_caltrans_closures_for_county(fixed_now):
    items, notes = run(caltrans.fetch_closures, "Butte")
    assert notes == []
    for c in items:
        assert set(c) == {"lat", "lon", "road", "kind", "since", "description"}
        assert c["kind"] in ("full", "partial") and isinstance(c["lat"], float)
        assert c["since"] is None or c["since"].endswith("Z")
    real_active = [r for r in load("lcs_d03.json")["data"]
                   if caltrans.normalize(r, "Butte", NOW) is not None]
    assert len(items) == 3 + len(real_active)  # A, B, F + any real record in effect at NOW
    full = [c for c in items if c["kind"] == "full"]
    assert full and full[0]["since"] == iso_utc(NOW - 7200 + 60)  # 1097 time preferred
    assert items[0]["kind"] == "full"  # full closures sorted first
    assert any(c["kind"] == "partial" and "One-Way Traffic" in c["description"] for c in items)


def test_caltrans_district_urls(fixed_now, monkeypatch):
    log = []
    run(caltrans.fetch_closures, "Kern", log=log)
    assert sorted(str(r.url) for r in log) == [
        "https://cwwp2.dot.ca.gov/data/d6/lcs/lcsStatusD06.json",
        "https://cwwp2.dot.ca.gov/data/d9/lcs/lcsStatusD09.json",
    ]


def test_caltrans_bad_payload_raises():
    with pytest.raises(Exception):
        run(caltrans.fetch_closures, "Butte", broken={"caltrans"})


# ------------------------------------------------------------------ Genasys

@pytest.mark.parametrize("raw,expected", [
    ("Normal", "normal"), ("Lifted", "normal"), ("Clear to Repopulate", "normal"), (None, "normal"),
    ("Evacuation Order", "order"), ("Shelter in Place", "order"),
    ("Evacuation Warning", "warning"), ("Advisory", "warning"), ("Something New", "warning"),
])
def test_genasys_status_map(raw, expected):
    assert genasys.map_status(raw) == expected


def test_genasys_zones():
    log = []
    zones, notes = run(genasys.fetch_zones, "Tulare", log=log)
    assert notes == [] and len(zones) == 8
    wfs = log[0]
    assert wfs.url.params["CQL_FILTER"] == "identifer LIKE 'US-CA-XTU-%'"
    assert wfs.url.params["typeName"] == "zonehavenv2:evacuation_zone"
    orders = [z for z in zones if z["status"] == "order"]
    assert len(orders) == 3 and zones[:3] == orders  # orders first
    detail = load("genasys_zone_detail.json")["zone"]
    assert all(z["updated"] == iso_utc(detail["updatedAt"]) for z in orders)
    assert all(z["updated"] is None for z in zones if z["status"] == "normal")
    assert len(log) == 1 + 3  # one WFS call + detail only for non-normal zones
    for z in zones:
        assert {"id", "status", "updated"} <= set(z) and z["id"].startswith("US-CA-XTU-")


def test_genasys_not_covered():
    with pytest.raises(genasys.NotCovered):
        run(genasys.fetch_zones, "Butte")


def test_genasys_detail_failure_keeps_zones():
    zones, notes = run(genasys.fetch_zones, "Tulare", broken={"genasys_detail"})
    assert len(zones) == 8 and any("unavailable for 3" in n for n in notes)


# ------------------------------------------------------------------ PG&E

def test_pge_outages():
    outages, notes = run(pge.fetch_outages, "Butte")
    assert notes == []
    assert [o["outage_id"] for o in outages] == ["900001", "386926"]  # 900002 is outside Butte
    psps, unplanned = outages
    assert psps["kind"] == "psps" and unplanned["kind"] == "unplanned"
    assert psps["area"]["zips"] == ["95954", "95969"] and psps["area"]["geometry"]["type"] == "MultiPolygon"
    assert unplanned["area"]["zips"] == ["95926"] and unplanned["area"]["geometry"] is None
    assert psps["est_restore"] == "2026-10-24T23:01:00Z" and unplanned["est_restore"] == "2026-10-24T06:30:00Z"
    for o in outages:
        assert {"area", "kind", "est_restore"} <= set(o) and "_geom" not in o


def test_pge_zip_failure_is_a_notice():
    outages, notes = run(pge.fetch_outages, "Butte", broken={"zcta"})
    assert len(outages) == 2 and all(o["area"]["zips"] == [] for o in outages)
    assert any("ZIP lookup" in n for n in notes)


def test_pge_service_error_raises():
    with pytest.raises(RuntimeError):
        run(pge.fetch_outages, "Butte", broken={"pge"})
