"""Builds the county situation record. Every source is isolated: a failed source yields an empty
array plus an entry in `errors`, never a failed run."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

import httpx

from . import calfire, caltrans, genasys, pge
from .common import now_utc

log = logging.getLogger(__name__)

SOURCE_TIMEOUT_S = 90

# output key -> (source name, fetcher). Build order per spec: Genasys and Caltrans first.
SOURCES: list[tuple[str, str, Callable[[httpx.AsyncClient, str], Awaitable[tuple[list, list]]]]] = [
    ("zones", "genasys", genasys.fetch_zones),
    ("closures", "caltrans", caltrans.fetch_closures),
    ("incidents", "calfire", calfire.fetch_incidents),
    ("outages", "pge", pge.fetch_outages),
]


async def _run_source(name: str, fetch: Callable, client: httpx.AsyncClient, county: str) -> tuple[list, list]:
    try:
        items, notes = await asyncio.wait_for(fetch(client, county), timeout=SOURCE_TIMEOUT_S)
        return items, [{"source": name, "level": "notice", "message": n} for n in notes]
    except genasys.NotCovered as exc:
        return [], [{"source": name, "level": "notice", "message": str(exc)}]
    except asyncio.TimeoutError:
        log.warning("%s timed out", name)
        return [], [{"source": name, "level": "error", "message": f"timed out after {SOURCE_TIMEOUT_S} s"}]
    except Exception as exc:  # isolation: never let one source fail the run
        log.warning("%s failed: %s", name, exc)
        return [], [{"source": name, "level": "error", "message": f"{type(exc).__name__}: {exc}"}]


async def build_situation(county: str, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    fetched_at = now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
    own = client is None
    client = client or httpx.AsyncClient(follow_redirects=True)
    try:
        results = await asyncio.gather(*(_run_source(name, fetch, client, county) for _, name, fetch in SOURCES))
    finally:
        if own:
            await client.aclose()
    out: dict[str, Any] = {"county": county, "fetched_at": fetched_at,
                           "incidents": [], "closures": [], "zones": [], "outages": [], "errors": []}
    for (key, _, _), (items, notes) in zip(SOURCES, results):
        out[key] = items
        out["errors"].extend(notes)
    return out
