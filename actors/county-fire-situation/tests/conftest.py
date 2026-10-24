"""Offline fixtures: trimmed real responses (captured 2026-10-23) served by an httpx.MockTransport."""

from __future__ import annotations

import copy
import json
import pathlib
import sys
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIX = ROOT / "tests" / "fixtures"

NOW = 1792850000  # 2026-10-24T13:53:20Z, fixed clock for closure "in effect" logic


def load(name: str) -> Any:
    return json.loads((FIX / name).read_text())


def lcs_record(template: dict, *, county="Butte", typ="Full", c1097=False, c1098=False, c1022=False,
               start=NOW - 3600, end=NOW + 3600, indefinite=False, index="X", lat="39.75", lon="-121.60"):
    r = copy.deepcopy(template)
    lcs = r["lcs"]
    lcs["index"] = index
    b, e = lcs["location"]["begin"], lcs["location"]["end"]
    b["beginCounty"] = e["endCounty"] = county
    b["beginLatitude"], b["beginLongitude"] = lat, lon
    cl = lcs["closure"]
    cl["typeOfClosure"] = typ
    cl["code1097"]["isCode1097"] = str(c1097).lower()
    cl["code1097"]["code1097Timestamp"]["code1097Epoch"] = str(start + 60) if c1097 else ""
    cl["code1098"]["isCode1098"] = str(c1098).lower()
    cl["code1022"]["isCode1022"] = str(c1022).lower()
    ts = cl["closureTimestamp"]
    ts["closureStartEpoch"], ts["closureEndEpoch"] = str(start), str(end)
    ts["isClosureEndIndefinite"] = str(indefinite).lower()
    return r


def lcs_feed() -> dict:
    """Real D03 records (none in effect at NOW) plus synthetic ones covering each closure state."""
    real = load("lcs_d03.json")["data"]
    t = real[0]
    synthetic = [
        lcs_record(t, index="A-full-1097", typ="Full", c1097=True, start=NOW - 7200),          # in effect (crew on scene)
        lcs_record(t, index="B-lane-window", typ="Lane"),                                      # in scheduled window
        lcs_record(t, index="C-cancelled", c1022=True),                                        # cancelled
        lcs_record(t, index="D-lifted", c1097=True, c1098=True),                               # lifted
        lcs_record(t, index="E-future", start=NOW + 3600, end=NOW + 7200),                     # not started
        lcs_record(t, index="F-indefinite", typ="One-Way Traffic", start=NOW - 86400, end=NOW - 1, indefinite=True),
        lcs_record(t, index="G-other-county", county="Sacramento", c1097=True),               # wrong county
        lcs_record(t, index="H-bad-coords", c1097=True, lat="", lon=""),                       # unusable
    ]
    return {"data": real + synthetic}


def make_transport(broken: set[str] | None = None, log: list | None = None) -> httpx.MockTransport:
    """broken: source names whose endpoint returns HTTP 500 / bad JSON / connection error."""
    broken = broken or set()

    def handler(request: httpx.Request) -> httpx.Response:
        if log is not None:
            log.append(request)
        u = str(request.url)
        host = request.url.host
        if host == "broken.invalid":
            raise httpx.ConnectError("simulated DNS failure", request=request)
        if "incidents.fire.ca.gov" in host:
            return httpx.Response(500) if "calfire" in broken else httpx.Response(200, json=load("calfire_list.json"))
        if "cwwp2.dot.ca.gov" in host:
            if "caltrans" in broken:
                return httpx.Response(200, text="<html>maintenance</html>")
            return httpx.Response(200, json=lcs_feed())
        if "zonehaven.com" in host and "/wfs" in u:
            if "genasys" in broken:
                return httpx.Response(503)
            return httpx.Response(200, json=load("genasys_wfs_tulare.json"))
        if "api-aware.zonehaven.com" in host:
            if "genasys_detail" in broken:
                return httpx.Response(500)
            return httpx.Response(200, json=load("genasys_zone_detail.json"))
        if "ags.pge.esriemcs.com" in host:
            if "pge" in broken:
                return httpx.Response(200, json={"error": {"code": 500, "message": "Service unavailable"}})
            layer = request.url.path.split("/")[-2]
            name = {"2": "pge_layer2_psps.json", "7": "pge_layer7_psps_poly.json",
                    "4": "pge_layer4_outages.json", "8": "pge_layer8_outage_poly.json"}[layer]
            return httpx.Response(200, json=load(name))
        if "tigerweb.geo.census.gov" in host:
            if "zcta" in broken:
                return httpx.Response(500)
            form = parse_qs(request.content.decode())
            kind = "polygon" if form["geometryType"][0] == "esriGeometryPolygon" else "point"
            return httpx.Response(200, json=load("zcta.json")[kind])
        raise AssertionError(f"unexpected request {u}")

    return httpx.MockTransport(handler)


@pytest.fixture
def fixed_now(monkeypatch):
    from src import caltrans

    monkeypatch.setattr(caltrans.time, "time", lambda: NOW)
    return NOW
