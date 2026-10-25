# Publishing the Ember actors

These steps need an Apify account. They were run on 2026-10-24 (account `outgoing_profiterole`); the results and the corrections found along the way are recorded inline and in the status table below. Run them from the repo root.

## Status (2026-10-24)

| Item | Value |
|---|---|
| Actor 1 `wildfire-refuge-evidence` | id `aNdgDQuJJuzSzuCco`, Console https://console.apify.com/actors/aNdgDQuJJuzSzuCco, build 1.0.5 (spaCy `en_core_web_sm` load verified in the build log). Store page https://apify.com/outgoing_profiterole/wildfire-refuge-evidence goes live after §2e. |
| Actor 2 `county-fire-situation` | id `CVITtkQDbvOELcp4m`, Console https://console.apify.com/actors/CVITtkQDbvOELcp4m, build 1.0.3, actor path `outgoing_profiterole~county-fire-situation` |
| Camp Fire 2018 dataset (public, "anyone with the link") | `AOGDPLjePpApuEBcB` (run `oi76gflOxTtjwW3cH`, 5 places / 6 mentions) → `EMBER_EVIDENCE_DATASET_ID=AOGDPLjePpApuEBcB` |
| Tubbs Fire 2017 dataset (public) | `H5utA5ArDenr0skxE` (run `SadbZPndq6dwzoDfy`, 0 places kept: 2 extracted, 1 dropped as a private residence, 1 outside 50 km) |
| §3a check | passed: run `R9ataMwriYQ2u1TWy` succeeded with `closures: []` and a `caltrans` error note; variable removed, rebuilt as 1.0.3 |
| Schedule (§3b) | `G9XTwRV8dLJgbcB67`, `*/15 * * * *` America/Los_Angeles, Butte CA, **disabled** |
| Still manual (§2e) | enable the account's public profile and upload the icon in Console, then **Publish to Store** |

## 0. Prerequisites

```bash
npm install -g apify-cli          # or: brew install apify-cli
apify --version
```

Get your API token from Apify Console → **Settings → API & Integrations**.

## 1. Log in

```bash
apify login                       # paste the token when prompted
apify login -t "$APIFY_TOKEN"     # non-interactive (token in an env var; never on the command line as a literal)
```

## 2. Actor 1: `wildfire-refuge-evidence` (must be public)

### 2a. Store the Claude key as an Apify secret

`.actor/actor.json` maps the env var `ANTHROPIC_API_KEY` to the secret `@anthropicApiKey`. Push fails if that secret is missing.

```bash
apify secrets add anthropicApiKey "$ANTHROPIC_API_KEY"
```

Trade-off: with this secret set, **every** run of the public actor uses your Anthropic key. Put a spend limit on that key in the Anthropic Console. If you would rather users bring their own key, delete the `environmentVariables` block from `.actor/actor.json`; users then fill the secret input `anthropic_api_key`.

### 2b. Optional local check

`apify run` needs `APIFY_TOKEN` (the CLI provides it after login) and `ANTHROPIC_API_KEY` in your shell:

```bash
cd actors/wildfire-refuge-evidence
ANTHROPIC_API_KEY=sk-ant-… apify run --input '{"fire_name":"Camp Fire","year":2018,"region_hint":"Butte County, California","max_pages":10}'
cat storage/key_value_stores/default/summary.json
```

### 2c. Push (uploads and builds on the platform)

```bash
cd actors/wildfire-refuge-evidence
apify push
```

Open the build log in Console (**Actor → Builds**) or `GET /v2/acts/<id>/builds` and confirm `python -c "import spacy; spacy.load('en_core_web_sm')"` succeeded.

Fixes found on the first pushes (already in the repo): spaCy's CLI imports `click`, which the newer `typer` no longer pulls in, so `click>=8,<9` is pinned in `requirements.txt`; and `Actor.set_value("evidence.geojson", ...)` must receive a JSON string, not a dict, when the content type is `application/geo+json`. Also, `apify/google-search-scraper` returns zero organic results for the Google **News** tab (`tbm=nws`), so the search runs on plain Google web search with the same query.

### 2d. Store listing (Console → Actor → Publication)

| Field | Value |
|---|---|
| Title | Wildfire Refuge Evidence |
| Short description | Find where people sheltered and survived during a wildfire. News articles and Reddit become geocoded GeoJSON points with quotes and sources. Person names are stripped. |
| Categories | AI; News; Developer tools (or the closest available) |
| SEO title | Wildfire Refuge Evidence: where survivors sheltered (the platform caps SEO titles at 60 characters, so the ", as GeoJSON" suffix was dropped) |
| SEO description | Give a wildfire name and year. Get the parking lots, lakes, fields and buildings where civilians sheltered and survived, with quotes, sources and coordinates. No person names. |
| README | Taken from `README.md` (it includes the privacy rule, both input examples, an output example, and how Ember's validate.py uses it). |
| Input schema / examples | Taken from `.actor/input_schema.json` (prefill: Camp Fire 2018; examples: Tubbs Fire 2017) |
| Icon | Any flame or map-pin image, 512×512. Must be uploaded in Console; the API rejects external `pictureUrl` values ("Invalid picture URL"). |
| Pricing | Free. Users pay their own platform usage, including the three Store actors it calls. |

### 2e. Make it public

Title, description, SEO fields and categories (`AI`, `NEWS`, `DEVELOPER_TOOLS`) are already set via `PUT /v2/acts/<id>`. Two steps need the Console (the API has no endpoint for either; `PUT /v2/acts/<id> {"isPublic": true}` answers `username-required`: "Actor owner needs to have a public profile"):

1. Console → **Settings → Account → Public profile**: turn the public profile on (username `outgoing_profiterole`, display name as you like).
2. Console → Actor → **Publication**: upload the icon, confirm the checklist, click **Publish to Store**. The actor page should read "Public".

### 2f. Camp Fire example run (about 30 seconds of extraction)

1. Console → Actor → **Input**: `{"fire_name": "Camp Fire", "year": 2018, "region_hint": "Butte County, California", "max_pages": 10}` → **Start**.
2. When it succeeds, open the run → **Storage → Dataset** and set the dataset's access to **Anyone with the link** (or open **Share**). API equivalent: `PUT /v2/datasets/<id>` with body `{"generalAccess": "ANYONE_WITH_ID_CAN_READ"}`.
3. Attach it to the listing. If the Publication tab has an example-run or output-example field, pick this run. Otherwise add the public dataset link under "Output example" in `README.md` and push again.
4. Record the dataset id for Ember: `EMBER_EVIDENCE_DATASET_ID=<id>` (used by `engine/validate.py`). Camp Fire 2018: `AOGDPLjePpApuEBcB` (public).

For the demo, also start a run on `{"fire_name": "Tubbs Fire", "year": 2017, "region_hint": "Sonoma County, California"}` and keep its dataset id for the Santa Rosa overlay. Tubbs Fire 2017: `H5utA5ArDenr0skxE` (public; 0 places kept, see Status).

Runs used `max_pages: 10`; each cost well under $0.10 of platform usage plus a few Claude calls.

## 3. Actor 2: `county-fire-situation`

```bash
cd actors/county-fire-situation
apify push
```

There are no secrets. Making it public is optional; the spec requires only actor 1 to be public. To publish anyway, use title "California County Fire Situation" with the short description from `.actor/actor.json`.

### 3a. Definition-of-done check (one source broken on purpose)

1. Console → Actor → Settings → **Environment variables**: add `EMBER_CALTRANS_LCS_URL` = `https://broken.invalid/d{district}.json`.
2. Run with `{"county":"Butte","state":"CA"}`. The run **succeeds**, `OUTPUT.closures` is `[]`, and `OUTPUT.errors` contains `{"source":"caltrans","level":"error",...}`.
3. Remove the variable and rebuild.

Result (2026-10-24): run `R9ataMwriYQ2u1TWy` succeeded with `closures: []` and `{"source": "caltrans", "level": "error", "message": "ConnectError: ..."}` in `errors`; variable removed, rebuilt as 1.0.3.

### 3b. Schedule every 15 minutes

Console → **Schedules → Create new**:
- Cron: `*/15 * * * *`; timezone America/Los_Angeles
- Action: Run actor `county-fire-situation`, input `{"county": "Butte", "state": "CA"}`; add more actions for more counties
- Enable during the demo, disable afterwards

Created as schedule `G9XTwRV8dLJgbcB67` (name `ember-butte-situation`), currently **disabled**; enable it in Console → Schedules before the demo.

The API equivalent is in `county-fire-situation/README.md`.

### 3c. Wire Ember to it

Ember reads the latest successful run with a 2 s timeout and caches the last good result:

```
GET https://api.apify.com/v2/acts/outgoing_profiterole~county-fire-situation/runs/last/dataset/items?status=SUCCEEDED&clean=true&token=<APIFY_TOKEN>
```

Put `APIFY_TOKEN` and the actor path in the staff tool and navigator config (`.env`). Never commit the token.
