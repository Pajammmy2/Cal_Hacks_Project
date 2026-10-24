# Publishing the Ember actors

These steps need an Apify account and were **not** run while building this project (no credentials were available). Run them from the repo root.

## 0. Prerequisites

```bash
npm install -g apify-cli          # or: brew install apify-cli
apify --version
```

Get your API token from Apify Console → **Settings → API & Integrations**.

## 1. Log in

```bash
apify login                       # paste the token when prompted
```

## 2. Actor 1: `wildfire-refuge-evidence` (must be public)

### 2a. Store the Claude key as an Apify secret

`.actor/actor.json` maps the env var `ANTHROPIC_API_KEY` to the secret `@anthropicApiKey`. Push fails if that secret is missing.

```bash
apify secrets add anthropicApiKey "sk-ant-…"
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

Open the build log in Console (**Actor → Builds**) and confirm `python -c "import spacy; spacy.load('en_core_web_sm')"` succeeded.

### 2d. Store listing (Console → Actor → Publication)

| Field | Value |
|---|---|
| Title | Wildfire Refuge Evidence |
| Short description | Find where people sheltered and survived during a wildfire. News articles and Reddit become geocoded GeoJSON points with quotes and sources. Person names are stripped. |
| Categories | AI; News; Developer tools (or the closest available) |
| SEO title | Wildfire Refuge Evidence: where survivors sheltered, as GeoJSON |
| SEO description | Give a wildfire name and year. Get named parking lots, lakes, fields and buildings where civilians sheltered and survived, with quotes, source links and coordinates. Privacy-first: no person names. |
| README | Taken from `README.md` (it includes the privacy rule, both input examples, an output example, and how Ember's validate.py uses it). |
| Input schema / examples | Taken from `.actor/input_schema.json` (prefill: Camp Fire 2018; examples: Tubbs Fire 2017) |
| Icon | Any flame or map-pin image, 512×512 |
| Pricing | Free. Users pay their own platform usage, including the three Store actors it calls. |

### 2e. Make it public

Console → Actor → **Publication** → complete the checklist → **Publish to Store**. The actor page should read "Public".

### 2f. Camp Fire example run (about 30 seconds of extraction)

1. Console → Actor → **Input**: `{"fire_name": "Camp Fire", "year": 2018, "region_hint": "Butte County, California", "max_pages": 10}` → **Start**.
2. When it succeeds, open the run → **Storage → Dataset** and set the dataset's access to **Anyone with the link** (or open **Share**).
3. Attach it to the listing. If the Publication tab has an example-run or output-example field, pick this run. Otherwise add the public dataset link under "Output example" in `README.md` and push again.
4. Record the dataset id for Ember: `EMBER_EVIDENCE_DATASET_ID=<id>` (used by `engine/validate.py`).

For the demo, also start a run on `{"fire_name": "Tubbs Fire", "year": 2017, "region_hint": "Sonoma County, California"}` and keep its dataset id for the Santa Rosa overlay.

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

### 3b. Schedule every 15 minutes

Console → **Schedules → Create new**:
- Cron: `*/15 * * * *`; timezone America/Los_Angeles
- Action: Run actor `county-fire-situation`, input `{"county": "Butte", "state": "CA"}`; add more actions for more counties
- Enable during the demo, disable afterwards

The API equivalent is in `county-fire-situation/README.md`.

### 3c. Wire Ember to it

Ember reads the latest successful run with a 2 s timeout and caches the last good result:

```
GET https://api.apify.com/v2/acts/<username>~county-fire-situation/runs/last/dataset/items?status=SUCCEEDED&clean=true&token=<APIFY_TOKEN>
```

Put `APIFY_TOKEN` and the actor path in the staff tool and navigator config (`.env`). Never commit the token.
