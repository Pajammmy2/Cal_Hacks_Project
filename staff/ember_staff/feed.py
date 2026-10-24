"""Apify county-fire-situation feed: GET /v2/datasets/<id>/items with a 2 s timeout, last result cached on disk.

No fire-day feature depends on this; the clients list shows zone status and an outage flag, plus the feed's age.
"""
import json
import time
from datetime import datetime, timezone

import httpx

from . import config

TIMEOUT_S = 2.0
MIN_REFRESH_S = 60.0
API = "https://api.apify.com/v2/datasets/{id}/items"


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_cache():
    p = config.feed_cache_path()
    if p.exists():
        try:
            return json.loads(p.read_text())
        except (OSError, ValueError):
            return None
    return None


def _write_cache(items):
    c = {"fetched_at": _now(), "fetched_ts": time.time(), "items": items}
    config.feed_cache_path().write_text(json.dumps(c))
    return c


def get_feed(force=False, client=None):
    """Returns {state: 'none'|'live'|'cached', fetched_at, age_s, situation, error}."""
    ds = config.env("APIFY_SITUATION_DATASET_ID")
    if not ds:
        return {"state": "none", "situation": None, "fetched_at": None, "age_s": None, "error": None}
    cache = _read_cache()
    if cache and not force and time.time() - cache.get("fetched_ts", 0) < MIN_REFRESH_S:
        return _result("live", cache, None)
    params = {"clean": "true", "format": "json", "desc": "true", "limit": "20"}
    token = config.env("APIFY_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    err = None
    try:
        get = (client or httpx).get
        r = get(API.format(id=ds), params=params, headers=headers, timeout=TIMEOUT_S)
        r.raise_for_status()
        items = r.json()
        if not isinstance(items, list):
            raise ValueError("dataset items is not a list")
        return _result("live", _write_cache(items), None)
    except (httpx.HTTPError, ValueError) as e:
        err = f"{type(e).__name__}: {e}"[:200]
    if cache:
        return _result("cached", cache, err)
    return {"state": "error", "situation": None, "fetched_at": None, "age_s": None, "error": err}


def _result(state, cache, err):
    return {"state": state, "situation": pick_situation(cache.get("items") or []), "fetched_at": cache.get("fetched_at"),
            "age_s": max(0.0, time.time() - cache.get("fetched_ts", time.time())), "error": err}


def pick_situation(items):
    """Newest item for our county (actor output: {county, fetched_at, incidents, closures, zones, outages})."""
    county = config.county().lower()
    mine = [i for i in items if isinstance(i, dict) and str(i.get("county", "")).lower().replace(" county", "") == county]
    pool = mine or [i for i in items if isinstance(i, dict)]
    if not pool:
        return None
    return max(pool, key=lambda i: str(i.get("fetched_at") or ""))


def zone_status(situation, zone):
    if not situation or not zone:
        return None
    z = str(zone).strip().lower()
    for item in situation.get("zones") or []:
        if str(item.get("id", "")).strip().lower() == z:
            return item.get("status")
    return None


def outage_for(situation, profile):
    """Outage entry whose area mentions the client's ZIP (or zone), else None."""
    if not situation:
        return None
    keys = [str(profile.get("zip") or "").strip(), str(profile.get("zone") or "").strip()]
    keys = [k.lower() for k in keys if k]
    for o in situation.get("outages") or []:
        area = str(o.get("area", "")).lower()
        if any(k in area for k in keys):
            return o
    return None


def age_text(age_s):
    if age_s is None:
        return ""
    if age_s < 90:
        return "just now"
    m = age_s / 60
    if m < 90:
        return f"{int(round(m))} min ago"
    h = m / 60
    if h < 48:
        return f"{int(round(h))} h ago"
    return f"{int(round(h / 24))} days ago"
