"""Shared helpers: county table, time formatting, geometry, source URLs (env-overridable)."""

from __future__ import annotations

import datetime as dt
import functools
import json
import os
import pathlib
from typing import Any

USER_AGENT = "Ember-county-fire-situation/1.0 (Apify actor; public data feed)"
DATA = pathlib.Path(__file__).resolve().parent / "data" / "ca_counties.json"

# Every source URL can be overridden with an env var (used by the broken-source test and for
# pointing at mirrors). Read at call time, not import time.
DEFAULT_URLS = {
    "EMBER_CALFIRE_URL": "https://incidents.fire.ca.gov/umbraco/api/IncidentApi/List?inactive=false",
    "EMBER_CALTRANS_LCS_URL": "https://cwwp2.dot.ca.gov/data/d{district}/lcs/lcsStatusD{district:02d}.json",
    "EMBER_GENASYS_WFS_URL": "https://cdngeospatialcei.zonehaven.com/geoserver/zonehavenv2/wfs",
    "EMBER_GENASYS_ZONE_API_URL": "https://api-aware.zonehaven.com/v2/zone",
    "EMBER_PGE_OUTAGE_URL": "https://ags.pge.esriemcs.com/arcgis/rest/services/43/outages/MapServer",
    "EMBER_ZCTA_URL": "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/PUMA_TAD_TAZ_UGA_ZCTA/MapServer/1/query",
}


def url(name: str) -> str:
    return os.environ.get(name) or DEFAULT_URLS[name]


@functools.lru_cache(maxsize=1)
def counties() -> dict[str, dict[str, Any]]:
    return json.loads(DATA.read_text())


def resolve_county(name: str) -> str | None:
    """'butte', 'Butte County', ' BUTTE ' -> 'Butte'. None if not a California county."""
    key = " ".join(str(name).replace("County", "").replace("county", "").split()).lower()
    for canonical in counties():
        if canonical.lower() == key:
            return canonical
    return None


def iso_utc(value: Any) -> str | None:
    """Epoch seconds / epoch ms / ISO string -> 'YYYY-MM-DDTHH:MM:SSZ' (None if empty)."""
    if value in (None, "", 0, "0"):
        return None
    if isinstance(value, str):
        s = value.strip()
        if s.isdigit():
            value = int(s)
        else:
            try:
                d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError:
                return s
            if d.tzinfo is None:
                d = d.replace(tzinfo=dt.timezone.utc)
            return d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, (int, float)):
        secs = value / 1000 if value > 10_000_000_000 else value
        return dt.datetime.fromtimestamp(secs, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return None


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def point_in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def in_county(lon: float, lat: float, county: dict[str, Any]) -> bool:
    w, s, e, n = county["bbox"]
    if not (w <= lon <= e and s <= lat <= n):
        return False
    return any(point_in_ring(lon, lat, ring) for ring in county["polygon"])


def to_float(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN -> None
