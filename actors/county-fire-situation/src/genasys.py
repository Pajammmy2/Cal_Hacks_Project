"""Genasys Protect (formerly Zonehaven) evacuation zones: the data behind protect.genasys.com maps.

Two public endpoints, both used by the protect.genasys.com web app itself:
  1. GeoServer WFS  https://cdngeospatialcei.zonehaven.com/geoserver/zonehavenv2/wfs
     layer zonehavenv2:evacuation_zone -> every zone with `identifer` (sic) and `status`.
     Zone ids are US-CA-<county prefix>-<...>; we filter server-side with CQL on the prefix.
  2. Zone API  https://api-aware.zonehaven.com/v2/zone?zone_id=<id> -> zone detail incl. `updatedAt`.
     Called only for zones not in "Normal" status (to keep a 15-minute schedule polite).

Status mapping to Ember's three levels (raw text kept in `raw_status`):
  order   <- Evacuation Order, Shelter in Place (and any status containing "order"/"shelter")
  warning <- Evacuation Warning, Advisory (and any other unknown non-normal status, conservatively)
  normal  <- Normal, Lifted, Clear to Repopulate / Repopulation
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from .common import USER_AGENT, counties, iso_utc, url

MAX_DETAIL_CALLS = 150
HEADERS = {"User-Agent": USER_AGENT, "Origin": "https://protect.genasys.com", "Referer": "https://protect.genasys.com/"}


class NotCovered(Exception):
    """County has no zones in Genasys Protect (a coverage note, not a failure)."""


def map_status(raw: str | None) -> str:
    s = (raw or "").strip().lower()
    if not s or s in ("normal", "lifted", "clear to repopulate", "repopulation", "repopulated", "all clear"):
        return "normal"
    if "order" in s or "shelter" in s:
        return "order"
    if "lift" in s or "repopulat" in s:
        return "normal"
    return "warning"


def wfs_params(prefix: str) -> dict[str, str]:
    return {
        "service": "WFS",
        "version": "1.0.0",
        "request": "GetFeature",
        "typeName": "zonehavenv2:evacuation_zone",
        "outputFormat": "application/json",
        "propertyName": "identifer,status,commonly_known_as",
        "CQL_FILTER": f"identifer LIKE 'US-CA-{prefix}-%'",
    }


async def fetch_zones(client: httpx.AsyncClient, county: str) -> tuple[list, list]:
    prefix = counties()[county].get("genasys_prefix")
    if not prefix:
        raise NotCovered(f"{county} County publishes no zones in Genasys Protect")
    r = await client.get(url("EMBER_GENASYS_WFS_URL"), params=wfs_params(prefix), timeout=60, headers=HEADERS)
    r.raise_for_status()
    data = r.json()
    if "features" not in data:
        raise ValueError("WFS response has no 'features'")
    zones: dict[str, dict[str, Any]] = {}
    for f in data["features"]:
        p = f.get("properties") or {}
        zid = p.get("identifer") or p.get("identifier")
        if not zid or not str(zid).startswith(f"US-CA-{prefix}-"):
            continue
        raw = p.get("status")
        zones[zid] = {"id": zid, "status": map_status(raw), "updated": None, "raw_status": raw,
                      "name": p.get("commonly_known_as")}

    notes: list[str] = []
    active = [z for z in zones.values() if (z["raw_status"] or "").lower() != "normal"]
    if len(active) > MAX_DETAIL_CALLS:
        notes.append(f"{len(active)} non-normal zones; 'updated' fetched for the first {MAX_DETAIL_CALLS}")
    sem = asyncio.Semaphore(6)
    failures = 0

    async def detail(z: dict[str, Any]) -> None:
        nonlocal failures
        async with sem:
            try:
                d = await client.get(url("EMBER_GENASYS_ZONE_API_URL"), params={"zone_id": z["id"]},
                                     timeout=15, headers=HEADERS)
                d.raise_for_status()
                zone = d.json().get("zone") or {}
                z["updated"] = iso_utc(zone.get("updatedAt"))
                if zone.get("status") and zone["status"] != z["raw_status"]:  # API is fresher than the WFS cache
                    z["raw_status"], z["status"] = zone["status"], map_status(zone["status"])
            except Exception:
                failures += 1

    await asyncio.gather(*(detail(z) for z in active[:MAX_DETAIL_CALLS]))
    if failures:
        notes.append(f"zone detail ('updated') unavailable for {failures} zone(s)")
    order = {"order": 0, "warning": 1, "normal": 2}
    out = sorted(zones.values(), key=lambda z: (order[z["status"]], z["id"]))
    return out, notes
