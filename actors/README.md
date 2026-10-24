# Ember on Apify

Ember has two Apify actors. Both sit **beside** the deterministic core, never in its path: remove them and the fire-day demo still runs.

| Actor | What it does | Used by | When |
|---|---|---|---|
| [`wildfire-refuge-evidence`](wildfire-refuge-evidence/) (Best Actor submission) | Given a past fire (`{fire_name, year, region_hint?, max_pages?}`), it finds where civilians sheltered and survived. Sources are Google search results (apify/google-search-scraper; the News tab yields no parsable results, so plain web search is used), article bodies (apify/website-content-crawler) and Reddit (trudax/reddit-scraper-lite). Claude extracts the places, Nominatim geocodes them, a 50 km perimeter filter and 150 m dedupe clean them up, and they come back as GeoJSON points with quotes. Person names are stripped in code. | `engine/validate.py` (share of evidence points within 300 m of a top-tier refuge; at least 60% on Paradise), plus the demo overlay (Tubbs Fire 2017 on Santa Rosa) | Pre-season |
| [`county-fire-situation`](county-fire-situation/) | Given `{county, state: "CA"}`, returns `{county, fetched_at, incidents, closures, zones, outages, errors}`. Sources are CAL FIRE incidents, Caltrans LCS closures, Genasys Protect zone status, and PG&E outages/PSPS. Each source is isolated: a failed source yields `[]` plus an error note, never a failed run. | Staff board (zone status per client, outage flag); navigator when online (closures within 2 km become blocked edges; outage ZIP starts the device-runtime timer) | Every 15 min during the demo (`*/15 * * * *`), otherwise on demand |

## Where Apify is used

The section below can be pasted into the main README:

- **Validation (pre-season):** `wildfire-refuge-evidence` runs on "Camp Fire 2018". `engine/validate.py --county paradise` reads its dataset (`GET /v2/datasets/<id>/items`) and reports the share of survivor-evidence points within 300 m of a refuge Ember scores 70 or higher. The demo also runs it live on "Tubbs Fire 2017" and overlays the points on Santa Rosa.
- **Situation feed (when online):** `county-fire-situation` runs on an Apify schedule every 15 minutes. The staff tool and the navigator read the latest run (`GET /v2/acts/<user>~county-fire-situation/runs/last/dataset/items?status=SUCCEEDED`) with a **2 s timeout**, and **cache the last good result**. No fire-day feature depends on it.

## Layout (each folder is a standard Apify Python actor)

```
<actor>/
  .actor/actor.json          actor definition (name, title, storages, env)
  .actor/input_schema.json   input with prefill/example values
  .actor/dataset_schema.json dataset fields + Console table view
  Dockerfile                 FROM apify/actor-python:3.13
  requirements.txt
  src/__main__.py, src/main.py, …
  tests/                     offline tests; every network call is mocked
  README.md                  Store-listing README
```

## Tests

```bash
cd actors/wildfire-refuge-evidence && python -m pytest -q   # 42 tests
cd actors/county-fire-situation   && python -m pytest -q   # 34 tests
python actors/county-fire-situation/scripts/smoke_live.py Butte   # live sources, no Apify account needed
```

Publishing steps are in [PUBLISHING.md](PUBLISHING.md).

## Notes and deviations from the spec

- The spec names `apify/reddit-scraper-lite`, but that actor id does not exist in the Apify Store (checked 2026-10-23 via `GET /v2/acts/apify~reddit-scraper-lite`, which returns record-not-found). The Store's Reddit Scraper Lite is `trudax/reddit-scraper-lite`, which actor 1 uses. Override it with env `EMBER_REDDIT_ACTOR`.
- Actor 1's Claude schema is the spec's array, wrapped as `{"places": [...]}` because structured outputs need an object root. `people_count_hint` is extracted and validated, but the spec's output schema has no field for it, so it is not stored.
- Actor 1 has optional inputs beyond the spec's four (`perimeter_centroid`, `use_frap_perimeter`, `anthropic_api_key`). All are optional, and the spec's four keep their exact names, types and default.
- Actor 2 output records keep the spec's keys and add an `errors` array plus additive detail fields: `description` on closures, `raw_status`/`name` on zones, `outage_id`/`customers`/`cause` on outages. `area` is an object `{zips, lat, lon, geometry}`.
- Actor 2 `zones[].updated` is filled only for zones not in Normal status. Normal zones have `updated: null`, because the WFS carries no timestamp and per-zone calls for hundreds of zones every 15 minutes would be impolite.
- Butte County publishes no zones in Genasys Protect, so a Butte run returns `zones: []` with a `notice`. The Genasys path is tested against Tulare data and live-checked on Tulare and Mendocino.
