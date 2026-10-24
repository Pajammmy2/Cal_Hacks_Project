"""wildfire-refuge-evidence: where did civilians shelter during a wildfire and survive?

Pipeline (Ember spec, Apify track): Google News search -> article bodies + Reddit posts ->
Claude structured extraction -> privacy scrub -> Nominatim geocode -> 50 km perimeter filter ->
150 m clustering -> one GeoJSON Feature per dataset item, plus OUTPUT / evidence.geojson /
summary.json in the key-value store.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
import re
from typing import Any

import httpx

from .extract import Extractor, KINDS, truncate_quote
from .geo import Geocoder, cluster_points, clusters_to_features, find_perimeter_centroid, within_radius
from .privacy import PLACEHOLDER, ner_backend, scrub_quote
from .sources import CallActor, collect_documents

log = logging.getLogger(__name__)

DEFAULT_MAX_PAGES = 60
EXTRACT_CONCURRENCY = 5
GEOCODE_CACHE_STORE = "ember-geocode-cache"
GEOCODE_CACHE_KEY = "nominatim"


class InputError(ValueError):
    pass


def parse_input(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw or {}
    fire_name = raw.get("fire_name")
    if not isinstance(fire_name, str) or not fire_name.strip():
        raise InputError("fire_name (string) is required, e.g. \"Camp Fire\"")
    year = raw.get("year")
    if isinstance(year, str) and year.strip().isdigit():
        year = int(year)
    if not isinstance(year, int) or isinstance(year, bool) or not 1900 <= year <= dt.date.today().year + 1:
        raise InputError("year (integer) is required, e.g. 2018")
    max_pages = raw.get("max_pages", DEFAULT_MAX_PAGES)
    if max_pages is None:
        max_pages = DEFAULT_MAX_PAGES
    if not isinstance(max_pages, int) or isinstance(max_pages, bool) or max_pages < 1:
        raise InputError("max_pages must be a positive integer (default 60)")
    region_hint = raw.get("region_hint")
    region_hint = region_hint.strip() if isinstance(region_hint, str) and region_hint.strip() else None

    centroid = None
    pc = raw.get("perimeter_centroid")
    if pc:
        try:
            centroid = (float(pc["lat"]), float(pc["lon"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise InputError("perimeter_centroid must be {\"lat\": number, \"lon\": number}") from exc
        if not (-90 <= centroid[0] <= 90 and -180 <= centroid[1] <= 180):
            raise InputError("perimeter_centroid out of range")
    return {
        "fire_name": fire_name.strip(),
        "year": year,
        "region_hint": region_hint,
        "max_pages": min(max_pages, 500),
        "perimeter_centroid": centroid,
        "use_frap_perimeter": raw.get("use_frap_perimeter", True) is not False,
    }


def _us_hint(region_hint: str | None) -> bool:
    return bool(region_hint) and bool(
        re.search(r"\b(CA|California|USA|US|United States|Oregon|Washington|Colorado|Hawaii)\b", region_hint, re.I)
    )


async def run_pipeline(
    inp: dict[str, Any],
    call_actor: CallActor,
    extractor: Extractor,
    http: httpx.AsyncClient,
    geocode_cache: dict[str, Any] | None = None,
    geocode_interval_s: float = 1.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Returns (FeatureCollection, summary). No Apify platform calls besides `call_actor`."""
    fire, year = inp["fire_name"], inp["year"]

    # 1. Fire perimeter centroid for the 50 km rule (optional; skipped with a note if unavailable)
    centroid, perimeter_note = inp["perimeter_centroid"], "perimeter centroid from input; 50 km filter applied"
    if centroid is None:
        if inp["use_frap_perimeter"]:
            centroid, perimeter_note = await find_perimeter_centroid(http, fire, year)
        else:
            perimeter_note = "perimeter filter skipped (use_frap_perimeter=false)"
    log.info(perimeter_note)

    # 2. Documents (news article bodies + Reddit posts)
    docs, source_stats = await collect_documents(call_actor, fire, inp["max_pages"])
    log.info("Collected %d documents: %s", len(docs), source_stats)

    # 3. Claude extraction (bounded concurrency; one failed article never fails the run)
    sem = asyncio.Semaphore(EXTRACT_CONCURRENCY)
    extract_errors = 0

    async def one(doc: dict[str, Any]) -> list[dict[str, Any]]:
        nonlocal extract_errors
        async with sem:
            try:
                return [dict(p, doc=doc) for p in await extractor.extract(fire, year, doc.get("title"), doc["body"])]
            except Exception as exc:
                extract_errors += 1
                log.warning("Extraction failed for %s: %s", doc.get("url"), exc)
                return []

    extracted = [p for batch in await asyncio.gather(*(one(d) for d in docs)) for p in batch]

    # 4. Privacy rule: places and what happened, never who.
    mentions, private_dropped = [], 0
    for p in extracted:
        place = scrub_quote(p["place"])
        if PLACEHOLDER in place:  # e.g. "the Smith family home": a private person, not a public place
            private_dropped += 1
            continue
        doc = p["doc"]
        mentions.append({
            "place": place,
            "kind": p["kind"] if p["kind"] in KINDS else "other",
            "quote": {
                "text": truncate_quote(scrub_quote(p["quote"], place)),
                "url": doc["url"],
                "outlet": doc.get("outlet"),
                "date": doc.get("date"),
            },
        })

    # 5. Geocode (Nominatim, region_hint bias) + 50 km filter
    countrycodes = "us" if (centroid is not None or _us_hint(inp["region_hint"])) else None
    geocoder = Geocoder(http, inp["region_hint"], centroid, countrycodes, geocode_cache,
                        min_interval_s=geocode_interval_s)
    located, not_found, outside = [], 0, 0
    for m in mentions:
        hit = await geocoder.geocode(m["place"])
        if hit is None:
            not_found += 1
            continue
        if not within_radius(hit, centroid):
            outside += 1
            continue
        located.append(dict(m, lat=hit[0], lon=hit[1]))

    # 6. Dedupe: cluster within 150 m, keep every quote and URL per cluster
    features = clusters_to_features(cluster_points(located))
    fc = {"type": "FeatureCollection", "features": features}

    counts = {k: 0 for k in KINDS}
    for f in features:
        counts[f["properties"]["kind"]] += 1
    summary = {
        "fire_name": fire,
        "year": year,
        "region_hint": inp["region_hint"],
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "features": len(features),
        "counts_by_kind": counts,
        "mentions": sum(f["properties"]["mentions"] for f in features),
        "perimeter": {
            "centroid": {"lat": centroid[0], "lon": centroid[1]} if centroid else None,
            "radius_km": 50 if centroid else None,
            "note": perimeter_note,
        },
        "pipeline": {
            **{k: v for k, v in source_stats.items() if k != "errors"},
            "documents": len(docs),
            "extracted_places": len(extracted),
            "extract_errors": extract_errors,
            "dropped_private_places": private_dropped,
            "not_geocoded": not_found,
            "outside_50km": outside,
            "nominatim_requests": geocoder.requests,
            "name_stripping": ner_backend(),
            "model": extractor.model,
        },
        "errors": source_stats.get("errors", []),
    }
    return fc, summary


async def _apify_call_actor(actor_id: str, run_input: dict[str, Any]) -> list[dict[str, Any]]:
    from apify import Actor

    run = await Actor.call(actor_id, run_input)
    status = getattr(run, "status", None)
    status = getattr(status, "value", status)
    if status != "SUCCEEDED":
        raise RuntimeError(f"{actor_id} run {getattr(run, 'id', '?')} finished with status {status}")
    page = await Actor.apify_client.dataset(run.default_dataset_id).list_items(clean=True)
    return list(page.items)


async def main() -> None:
    from apify import Actor

    async with Actor:
        raw = await Actor.get_input() or {}
        try:
            inp = parse_input(raw)
        except InputError as exc:
            await Actor.fail(status_message=f"Invalid input: {exc}")
            return
        api_key = raw.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            await Actor.fail(status_message="Set ANTHROPIC_API_KEY (secret env var) or the anthropic_api_key input")
            return

        cache_store = await Actor.open_key_value_store(name=GEOCODE_CACHE_STORE)
        cache = await cache_store.get_value(GEOCODE_CACHE_KEY) or {}

        await Actor.set_status_message(f"Searching sources for {inp['fire_name']} {inp['year']}")
        async with httpx.AsyncClient(follow_redirects=True) as http:
            fc, summary = await run_pipeline(inp, _apify_call_actor, Extractor(api_key=api_key), http, cache)

        await cache_store.set_value(GEOCODE_CACHE_KEY, cache)
        if fc["features"]:
            await Actor.push_data(fc["features"])
        await Actor.set_value("OUTPUT", fc)
        await Actor.set_value("evidence.geojson", fc, content_type="application/geo+json")
        await Actor.set_value("summary.json", summary)
        await Actor.set_status_message(
            f"{summary['features']} places, {summary['mentions']} mentions; {summary['perimeter']['note']}",
            is_terminal=True,
        )
