"""Caltrans Lane Closure System (LCS): the closures QuickMap shows, from the public per-district JSON.

Feed: https://cwwp2.dot.ca.gov/data/d<N>/lcs/lcsStatusD<NN>.json (one file per district, refreshed
by Caltrans every few minutes, 0.5-3 MB). Each record is a planned or emergency closure with begin
and end points. We keep records in the county that are in effect now:
  not cancelled (code 1022), not lifted (code 1098), and either confirmed in place (code 1097)
  or inside their scheduled start..end window (or indefinite).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from .common import USER_AGENT, counties, iso_utc, to_float, url


def _true(v: Any) -> bool:
    return str(v).lower() == "true"


def _epoch(v: Any) -> int | None:
    try:
        return int(str(v))
    except (TypeError, ValueError):
        return None


def is_active(closure: dict[str, Any], now: float) -> bool:
    if _true((closure.get("code1022") or {}).get("isCode1022")):
        return False  # cancelled
    if _true((closure.get("code1098") or {}).get("isCode1098")):
        return False  # closure picked up / lifted
    if _true((closure.get("code1097") or {}).get("isCode1097")):
        return True  # crew on scene, closure in effect
    ts = closure.get("closureTimestamp") or {}
    start, end = _epoch(ts.get("closureStartEpoch")), _epoch(ts.get("closureEndEpoch"))
    if start is None or start > now:
        return False
    return _true(ts.get("isClosureEndIndefinite")) or (end is not None and now <= end)


def normalize(record: dict[str, Any], county: str, now: float) -> dict[str, Any] | None:
    lcs = record.get("lcs") or {}
    loc, cl = lcs.get("location") or {}, lcs.get("closure") or {}
    begin, end = loc.get("begin") or {}, loc.get("end") or {}
    c = county.lower()
    if (begin.get("beginCounty") or "").lower() != c and (end.get("endCounty") or "").lower() != c:
        return None
    if not is_active(cl, now):
        return None
    in_begin = (begin.get("beginCounty") or "").lower() == c
    lat = to_float(begin.get("beginLatitude") if in_begin else end.get("endLatitude"))
    lon = to_float(begin.get("beginLongitude") if in_begin else end.get("endLongitude"))
    if lat is None or lon is None or (lat == 0 and lon == 0):
        return None
    ts = cl.get("closureTimestamp") or {}
    since = iso_utc(((cl.get("code1097") or {}).get("code1097Timestamp") or {}).get("code1097Epoch")) \
        or iso_utc(ts.get("closureStartEpoch"))
    road = begin.get("beginRoute") or end.get("endRoute") or "unknown"
    direction = loc.get("travelFlowDirection")
    frm, to = begin.get("beginLocationName"), end.get("endLocationName")
    span = f"{frm} to {to}" if frm and to and frm != to else (frm or to or "")
    description = ", ".join(x for x in (
        f"{cl.get('typeOfClosure') or 'Unknown'} closure",
        cl.get("facility"),
        f"direction: {direction}" if direction and direction not in ("Both", "N/A", "Unknown") else None,
        span or None,
        cl.get("typeOfWork"),
        f"lanes closed: {cl['lanesClosed']}" if cl.get("lanesClosed") else None,
    ) if x)
    return {
        "lat": lat,
        "lon": lon,
        "road": road,
        "kind": "full" if (cl.get("typeOfClosure") or "").lower() == "full" else "partial",
        "since": since,
        "description": description,
    }


async def fetch_closures(client: httpx.AsyncClient, county: str, now: float | None = None) -> tuple[list, list]:
    now = time.time() if now is None else now
    districts = counties()[county]["caltrans_districts"]

    async def one(d: int) -> list[dict[str, Any]]:
        r = await client.get(url("EMBER_CALTRANS_LCS_URL").format(district=d), timeout=45,
                             headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        return r.json().get("data") or []

    results = await asyncio.gather(*(one(d) for d in districts), return_exceptions=True)
    closures, notes, seen = [], [], set()
    for d, res in zip(districts, results):
        if isinstance(res, BaseException):
            if len(districts) == 1:
                raise res
            notes.append(f"district {d} feed failed: {type(res).__name__}: {res}")
            continue
        for rec in res:
            item = normalize(rec, county, now)
            key = (rec.get("lcs") or {}).get("index")
            if item and key not in seen:
                seen.add(key)
                closures.append(item)
    if len(notes) == len(districts):
        raise RuntimeError("; ".join(notes))
    closures.sort(key=lambda c: (c["kind"] != "full", c["road"], c["since"] or ""))
    return closures, notes
