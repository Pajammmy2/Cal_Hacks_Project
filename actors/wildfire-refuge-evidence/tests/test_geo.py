import asyncio
import time

import httpx
from conftest import load, make_transport

from src.geo import (
    USER_AGENT,
    Geocoder,
    cluster_points,
    clusters_to_features,
    find_perimeter_centroid,
    haversine_m,
    normalize_fire_name,
    rings_centroid,
    within_radius,
)


def test_haversine():
    # 0.001 deg latitude ~ 111 m
    assert 110 < haversine_m(39.0, -121.0, 39.001, -121.0) < 112


def test_normalize_fire_name():
    assert normalize_fire_name("Camp Fire") == "CAMP"
    assert normalize_fire_name("Tubbs fire") == "TUBBS"
    assert normalize_fire_name("August Complex") == "AUGUST COMPLEX"


def test_rings_centroid_square():
    lat, lon = rings_centroid([[[-121.7, 39.65], [-121.4, 39.65], [-121.4, 39.85], [-121.7, 39.85], [-121.7, 39.65]]])
    assert abs(lat - 39.75) < 1e-9 and abs(lon + 121.55) < 1e-9


def _pt(lat, lon, place="P", kind="parking lot", text="t", url="u"):
    return {"lat": lat, "lon": lon, "place": place, "kind": kind,
            "quote": {"text": text, "url": url, "outlet": "o", "date": None}}


def test_cluster_150m():
    a = _pt(39.0, -121.0, "Kmart lot", text="a", url="u1")
    b = _pt(39.0009, -121.0, "Kmart parking lot", text="b", url="u2")  # ~100 m from a
    c = _pt(39.0027, -121.0, "Far", text="c", url="u3")  # ~200 m from b, 300 m from a
    clusters = cluster_points([a, b, c])
    assert sorted(len(x) for x in clusters) == [1, 2]
    feats = clusters_to_features(clusters)
    top = feats[0]
    assert top["properties"]["mentions"] == 2
    assert [q["url"] for q in top["properties"]["quotes"]] == ["u1", "u2"]  # all quotes and URLs kept
    assert top["geometry"]["type"] == "Point" and len(top["geometry"]["coordinates"]) == 2


def test_cluster_duplicate_quotes_deduped():
    a = _pt(39.0, -121.0, text="same", url="u")
    b = _pt(39.0, -121.0, text="same", url="u")
    f = clusters_to_features(cluster_points([a, b]))[0]
    assert f["properties"]["mentions"] == 1 and len(f["properties"]["quotes"]) == 1


def test_within_radius():
    assert within_radius((39.76, -121.62), (39.75, -121.55))
    assert not within_radius((38.58, -121.49), (39.75, -121.55))
    assert within_radius((0, 0), None)  # no perimeter -> filter skipped


def test_perimeter_frap_largest_feature():
    async def go():
        async with httpx.AsyncClient(transport=make_transport()) as c:
            return await find_perimeter_centroid(c, "Camp Fire", 2018)

    (lat, lon), note = asyncio.run(go())
    assert abs(lat - 39.75) < 1e-6 and abs(lon + 121.55) < 1e-6  # the 153k-acre polygon, not the 13-acre one
    assert "CAL FIRE FRAP" in note and "applied" in note


def test_perimeter_falls_back_to_nifc_then_skips():
    nifc = load("frap_camp.json")

    async def go(transport):
        async with httpx.AsyncClient(transport=transport) as c:
            return await find_perimeter_centroid(c, "Camp Fire", 2018)

    c1, note1 = asyncio.run(go(make_transport(frap=503, nifc=nifc)))
    assert c1 is not None and "NIFC" in note1
    c2, note2 = asyncio.run(go(make_transport(frap=503)))
    assert c2 is None and note2.startswith("perimeter filter skipped") and "503" in note2


def test_geocoder_bias_rate_limit_cache():
    log = []

    async def go():
        async with httpx.AsyncClient(transport=make_transport(log=log)) as c:
            g = Geocoder(c, "Butte County, California", (39.75, -121.55), "us", min_interval_s=0.3)
            t0 = time.monotonic()
            a = await g.geocode("Lake Concow")
            b = await g.geocode("Sacramento Convention Center")  # region query misses -> bare query
            again = await g.geocode("Lake Concow")  # cached, no request
            return a, b, again, time.monotonic() - t0, g

    a, b, again, elapsed, g = asyncio.run(go())
    assert a == (39.7765, -121.5039) and again == a and b == (38.5776, -121.4944)
    assert g.requests == 3 and len(log) == 3
    assert elapsed >= 0.6  # 3 requests, >= interval apart
    req = log[0]
    assert req.headers["User-Agent"] == USER_AGENT
    assert req.url.params["q"] == "Lake Concow, Butte County, California"
    assert req.url.params["countrycodes"] == "us" and req.url.params["bounded"] == "0"
    left, top, right, bottom = map(float, req.url.params["viewbox"].split(","))
    assert left < -121.55 < right and bottom < 39.75 < top
    assert g.cache["lake concow, butte county, california"] == [39.7765, -121.5039]


def test_query_variants():
    from src.geo import query_variants

    assert query_variants("Kmart parking lot on Clark Road") == [
        "Kmart parking lot on Clark Road", "Kmart on Clark Road", "Kmart"]
    assert query_variants("Lake Concow") == ["Lake Concow", "Concow Reservoir", "Concow Lake"]
    v = query_variants("the field behind Ponderosa Elementary School")
    assert "field" not in v and "Ponderosa Elementary School" not in v  # no generic / coarse fallbacks
    assert query_variants("Kmart lot in Paradise")[-1] == "Kmart" and "Paradise" not in query_variants("Kmart lot in Paradise")


def test_settlement_results_rejected():
    from src.geo import is_specific_result

    assert not is_specific_result({"category": "boundary", "addresstype": "city"})
    assert not is_specific_result({"category": "place", "addresstype": "hamlet"})
    assert is_specific_result({"category": "water", "addresstype": "reservoir"})
    assert is_specific_result({"category": "shop", "addresstype": "shop"})
