# California County Fire Situation

**One call, one JSON record: what is happening in this county right now.** Give it a California county. It returns active CAL FIRE incidents, Caltrans road closures, Genasys Protect evacuation-zone status, and PG&E outages and Public Safety Power Shutoffs (PSPS), all normalised to one small shape. Schedule it every 15 minutes during an incident and read the latest result from the Apify API.

Built for [Ember](../README.md). Ember's staff board shows zone status and an outage flag per client. Its phone navigator, when online, turns closures within 2 km into blocked road edges before routing, and starts a device-battery timer when the client's ZIP code is in an outage. No fire-day feature depends on this feed. It only adds information when there is signal.

**Each source is isolated.** A source that is down, slow, or returns garbage yields an empty array plus a note in `errors`. It never fails the run.

## Input

```json
{ "county": "Butte", "state": "CA" }
```

| Field | Type | Notes |
|---|---|---|
| `county` | string | Any of California's 58 counties. `"Butte"`, `"butte"` and `"Butte County"` all work. An unknown name fails the run with the list of valid names. |
| `state` | `"CA"` | Only California is supported. |

## Output

One dataset item per run, also stored as `OUTPUT` in the key-value store:

```json
{
  "county": "Butte",
  "fetched_at": "2026-10-24T05:06:08Z",
  "incidents": [
    { "id": "…", "name": "Example Fire", "type": "Wildfire", "lat": 39.81, "lon": -121.43,
      "acres": 1200.0, "containment": 35.0, "updated": "2026-10-23T20:00:00Z",
      "started": "2026-10-16T18:33:00Z", "location": "…", "admin_unit": "…", "url": "https://www.fire.ca.gov/incidents/…" }
  ],
  "closures": [
    { "lat": 39.75, "lon": -121.6, "road": "SR-32", "kind": "full", "since": "2026-10-24T11:54:20Z",
      "description": "Full closure, Conventional Hwy, direction: East / West, (County Rd), Utility Work, lanes closed: RShoulder" }
  ],
  "zones": [
    { "id": "US-CA-XTU-PVL-E032", "status": "order", "updated": "2023-09-20T22:33:08Z", "raw_status": "Evacuation Order", "name": null },
    { "id": "US-CA-XTU-VSA-5010A", "status": "normal", "updated": null, "raw_status": "Normal", "name": null }
  ],
  "outages": [
    { "area": { "zips": ["95954", "95969"], "lat": 39.76, "lon": -121.62,
                "geometry": { "type": "MultiPolygon", "coordinates": [[[[-121.64, 39.75], [-121.6, 39.75], [-121.6, 39.78], [-121.64, 39.78], [-121.64, 39.75]]]] } },
      "kind": "psps", "est_restore": "2026-10-24T23:01:00Z", "outage_id": "900001", "customers": 412, "cause": "PUBLIC SAFETY" },
    { "area": { "zips": ["95926"], "lat": 39.73, "lon": -121.84, "geometry": null },
      "kind": "unplanned", "est_restore": "2026-10-24T06:30:00Z", "outage_id": "386926", "customers": 6, "cause": "PATROLLING" }
  ],
  "errors": [
    { "source": "genasys", "level": "notice", "message": "Butte County publishes no zones in Genasys Protect" }
  ]
}
```

(This example comes from the offline test fixtures, so some values are synthetic. The zones are Tulare's, because Butte has none in Genasys.)

The contract fields are:
- `closures[]`: `{lat, lon, road, kind: "full"|"partial", since}`
- `zones[]`: `{id, status: "normal"|"warning"|"order", updated}`
- `outages[]`: `{area, kind: "psps"|"unplanned", est_restore}`

The other fields (`description`, `raw_status`, `name`, `outage_id`, `customers`, `cause`, and everything inside `area` and `incidents`) are additive detail. All times are ISO 8601 UTC (`…Z`). `errors[]` items are `{source, level: "error"|"notice", message}`. `error` means the source failed and its array is empty because of that; `notice` means the source worked but has something worth knowing, such as no coverage for the county.

## Sources: what each returns and how reliable it is

Endpoints were investigated with live requests on 2026-10-23. Every URL can be overridden with an environment variable (last column), which is also how the broken-source test works.

| Output | Source | Endpoint | What it returns | Reliability | Env override |
|---|---|---|---|---|---|
| `zones` | **Genasys Protect** (formerly Zonehaven), the data behind protect.genasys.com | GeoServer WFS `https://cdngeospatialcei.zonehaven.com/geoserver/zonehavenv2/wfs`, layer `zonehavenv2:evacuation_zone`, filtered with `CQL_FILTER=identifer LIKE 'US-CA-<prefix>-%'` | Every zone with `identifer` (sic), `status` (`Normal`, `Evacuation Warning`, `Evacuation Order`, `Advisory`, `Shelter in Place`, `Lifted`…), and polygon geometry. Geometry is always included even when not requested: about 2.6 MB for a county with 500 zones. | Good. It is a public CDN that the Genasys web app itself uses. Statewide on 2026-10-23: 22,056 zones in 41 California counties (8 Evacuation Order, 1 Advisory, 44 Lifted). | `EMBER_GENASYS_WFS_URL` |
| `zones[].updated` | Genasys zone API | `https://api-aware.zonehaven.com/v2/zone?zone_id=<id>` | Zone detail including `updatedAt` and `status`. It is fresher than the WFS, so when the two differ the API status wins. | Good. Called **only for zones not in Normal status** (at most 150 per run) to keep a 15-minute schedule polite, so Normal zones have `updated: null`. Note that some orders are stale on Genasys's side: Tulare's 8 "Evacuation Order" zones were last updated 2023-09-20, which `updated` exposes. | `EMBER_GENASYS_ZONE_API_URL` |
| `closures` | **Caltrans** Lane Closure System (LCS), what QuickMap shows | `https://cwwp2.dot.ca.gov/data/d<N>/lcs/lcsStatusD<NN>.json`, one file per district (0.5–3 MB) | Planned and emergency closures with begin and end lat/lon, route, closure type (`Full`, `Lane`, `One-Way Traffic`, `Alternating Lanes`, `Moving`), and status codes 1097 (in place), 1098 (lifted) and 1022 (cancelled). | Very good: an official open-data feed refreshed every few minutes. Most records are *scheduled* work. We keep only those in effect now: not cancelled, not lifted, and either code 1097 or inside the scheduled window (or open-ended). `kind` is `full` for `Full` and `partial` for everything else. The county is matched on the begin or end county. Districts per county are bundled; Kern reads D6 and D9. | `EMBER_CALTRANS_LCS_URL` (template with `{district}`) |
| `incidents` | **CAL FIRE** incidents, the JSON behind fire.ca.gov/incidents | `https://incidents.fire.ca.gov/umbraco/api/IncidentApi/List?inactive=false` | Active incidents statewide: name, county (can be `"Butte, Plumas"`), lat/lon, acres, percent contained, updated, started, URL. | Good. The `www.fire.ca.gov` host returns an Akamai "Access Denied" to non-browser clients, but the `incidents.` subdomain serves the same API without blocking. It lists only incidents CAL FIRE publishes (3 statewide on 2026-10-23). Final and inactive incidents are dropped. | `EMBER_CALFIRE_URL` |
| `outages` | **PG&E** outage map and PSPS | ArcGIS `https://ags.pge.esriemcs.com/arcgis/rest/services/43/outages/MapServer`: layer 2 PSPS points with 7 PSPS polygons; layer 4 outage points with 8 outage polygons; joined on `OUTAGE_ID` | Outage id, estimated restoration (`CURRENT_ETOR`), customers, cause, start, polygons. **No county or ZIP field.** | Good: the service behind PG&E's public outage map. We query by the county bounding box, keep points inside the county polygon (bundled Census TIGERweb county shapes), then look up the 2020 Census ZIP Code Tabulation Areas each outage polygon (or point) touches, via TIGERweb. `kind` is `psps` for PSPS layers and cause `PUBLIC SAFETY`; everything else is `unplanned`, including PG&E planned maintenance (cause `PLNND SHUTDOWN`), which `cause` lets you tell apart. Counties outside PG&E territory (for example Los Angeles) simply return `[]`. | `EMBER_PGE_OUTAGE_URL`, `EMBER_ZCTA_URL` |

Coverage gaps:
- **Genasys:** 17 counties publish no zones in Genasys Protect, including **Butte**, Sacramento, Sonoma, Placer, El Dorado, Glenn, Colusa and others. For those, `zones` is `[]` with a `notice`, not an `error`. The county-to-prefix table in `src/data/ca_counties.json` was discovered from the live WFS. Rerun the discovery described in `scripts/build_counties.py` if a county joins Genasys.
- **Status mapping:** `order` covers Evacuation Order and Shelter in Place; `warning` covers Evacuation Warning, Advisory, and any unknown non-normal status (kept conservative); `normal` covers Normal, Lifted, and Clear to Repopulate. The original text is kept in `raw_status`.

### Live smoke run (real network, no Apify platform), 2026-10-24 05:05 UTC

Run with `python scripts/smoke_live.py <county>`:

| County | incidents | closures | zones | outages | notes | time |
|---|---|---|---|---|---|---|
| Butte | 0 | 0 | 0 | 1 (unplanned, ZIP 95965, 6 customers) | genasys notice: not covered | 6.4 s |
| Tulare | 0 | 12 | 636 (8 order) | 1 | none | 3.1 s |
| Mendocino | 1 (Cooley Fire, 1,365 ac, 86%) | 14 | 189 | 0 | none | 3.5 s |
| Sacramento | 0 | 24 | 0 | 0 | genasys notice: not covered | 1.1 s |

Butte's 0 closures is correct at that hour. The D3 feed had 44 Butte records, none in effect; the next one started 2026-10-26.

## Failure isolation (and how it is tested)

Each source runs in its own task with a 90 s timeout. Any exception or timeout becomes `[]` plus `{"source": …, "level": "error", "message": …}`. Within a source, partial failures are notices: a missing district feed, failed zone detail calls, failed ZIP lookups, or a missing polygon layer.

`tests/test_situation.py` checks:
- each of the four sources broken in turn (HTTP 500/503, HTML instead of JSON, an ArcGIS error body): only that array is empty and the other three are unchanged;
- a source URL broken on purpose through its env var (`EMBER_CALTRANS_LCS_URL=https://broken.invalid/…`, a DNS failure);
- all four broken at once;
- a hanging source (timeout);
- the real Actor entry point, run in a fresh process with `EMBER_PGE_OUTAGE_URL` broken: exit code 0, one dataset item, an identical `OUTPUT` record, and `outages: []` with a `pge` error.

To reproduce the definition-of-done check by hand:

```bash
EMBER_CALTRANS_LCS_URL="https://broken.invalid/d{district}.json" apify run --input '{"county":"Butte","state":"CA"}'
# run SUCCEEDS; OUTPUT.closures == [] and OUTPUT.errors has {"source":"caltrans","level":"error",...}
```

On the platform, set the same variable under the actor's **Settings → Environment variables** for one run.

## Schedule: every 15 minutes during an incident

Create an Apify **Schedule** (Console → Schedules → Create new):
- **Cron expression:** `*/15 * * * *`
- **Timezone:** America/Los_Angeles (any timezone works for a 15-minute cadence)
- **Action:** run actor `<your-username>/county-fire-situation` with input `{"county": "Butte", "state": "CA"}`; add one action per county you watch
- Enable it during the demo or an incident. Otherwise run on demand.

The same through the API:

```bash
curl -X POST "https://api.apify.com/v2/schedules?token=$APIFY_TOKEN" -H 'Content-Type: application/json' -d '{
  "name": "ember-butte-situation", "cronExpression": "*/15 * * * *", "timezone": "America/Los_Angeles",
  "isEnabled": true, "isExclusive": true,
  "actions": [{ "type": "RUN_ACTOR", "actorId": "<actorId>",
                "runInput": { "body": "{\"county\":\"Butte\",\"state\":\"CA\"}", "contentType": "application/json" } }]
}'
```

A run takes 1–10 s, so a 15-minute cadence uses very little compute. `isExclusive` stops a new run from starting while the previous one is still running.

## Reading the latest result (how Ember consumes it)

Each scheduled run writes a new default dataset. Read the latest successful one:

```
GET https://api.apify.com/v2/acts/<username>~county-fire-situation/runs/last/dataset/items?status=SUCCEEDED&clean=true&token=…
```

You can also use `GET /v2/datasets/<datasetId>/items` for a known run. Ember's staff tool and navigator call this with a **2 s timeout** and **cache the last good result**. Fire-day features never wait on it.

## Development

```bash
pip install -r requirements.txt pytest
python -m pytest -q                 # offline; fixtures are trimmed real responses captured 2026-10-23
python scripts/smoke_live.py Butte  # live fetch + normalise, no Apify platform or keys needed
python scripts/build_counties.py    # regenerate src/data/ca_counties.json (county shapes, districts, Genasys prefixes)
```

County shapes are from US Census TIGERweb (2020 vintage, generalised to about 500 m). Each is used only to decide whether an outage point lies inside the county.
