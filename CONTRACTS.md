# Ember integration contracts

Every lane codes against this file. If you need to change a contract, change it here first.
The spec (`docs/spec.pdf` summary in README) is the source of truth; this file pins the details
the spec leaves open so the Python engine, the staff tool, and the Swift navigator agree byte for byte.

## Repo layout

```
shared/                 JSON shared by Python and Swift (copied into every bundle and into the iOS app)
  profiles.json         routing profiles (spec "Profiles" table)
  turn_templates.json   fixed phrase templates for turn cues
  phrases.json          fixed phrase set (generic clips) + numbers 1-500
  pronunciation.json    street-name pronunciation map applied ONLY to text sent to Cartesia
  intents.json          12 on-device intents with synonyms
engine/                 Python engine (lane A)
  ember_engine/         importable package
    core/               routing + turn cues + hashing + geocode (written first; Swift ports it)
  build_bundle.py       --county <name> --bbox <w,s,e,n>
  validate.py           --county paradise
  vision_pass.py        Claude vision pass (Job 1)
  serve.py              FastAPI: POST /plan
  fixtures/make_fake_bundle.py   synthetic bundle "fake" for every lane's tests
staff/                  FastAPI + HTMX staff tool + Cartesia pre-gen + consent (lane C)
navigator/              Swift (lane B): EmberCore Swift package (pure logic, testable with `swift test`)
                        + EmberNavigator iOS app sources + project.yml (XcodeGen)
actors/wildfire-refuge-evidence/   Apify actor 1
actors/county-fire-situation/      Apify actor 2
bundles/<county>/       build output; bundles/<county>.zip is what the phone loads
notability/             build-log structure and checklist (lane D)
```

## Bundle (`bundles/<county>/`)

| file | shape |
|---|---|
| `manifest.json` | `{county, bbox:[w,s,e,n], built_at: ISO8601Z, sources:{osm, dem, fuel, perimeters, wind}, counts:{nodes,edges,refuges}, version: 1}` |
| `graph.json` | `{nodes:[{id,lat,lon,elev}], edges:[{a,b,length_m,grade_pct,surface,steps,step_count,curb_cut,road_class,sidewalk,name,driveway}]}` |
| `refuges.json` | `{generated_at, refuges:[{id,name,kind,polygon:[[lon,lat],...],centroid:[lon,lat],entry_points:[{node,lat,lon}],score,terms,claude,flag,thumb}]}` |
| `perimeters.json` | `{current:{timestamp, polygon:[[lon,lat]...] or null}, historical:[{fire, timestamp, polygon}]}` |
| `wind.json` | `{timestamp, direction_from_deg, speed_mps, source}` |
| `addresses.json` | `[{house_number, street, city, lat, lon}]` (local geocoder; from OSM addr:* tags) |
| `tiles.mbtiles` | MBTiles (SQLite) for the bbox |
| `thumbs/<refuge_id>.jpg` | satellite JPEG, zoom 18 |
| `shared/` | copy of repo `shared/` |
| `plans/<client_id>.json` | written by the staff tool (plan JSON, below) |
| `audio/<sha1>.mp3`, `audio/index.json` | written by the staff tool Cartesia step (default voice) |
| `audio/clients/<client_id>/<sha1>.mp3` + `index.json` | cloned-voice clips for that client (checked first) |

Node ids are ints, 0..N-1, equal to their index in `nodes`. Edges are undirected for travel;
`grade_pct` is signed for travel a→b (positive = uphill); traversing b→a negates it.
`surface` ∈ `paved|unpaved|unknown`; `curb_cut` ∈ `true|false|"unknown"`; `steps` bool; `step_count` int or null;
`sidewalk` bool; `driveway` bool (`service=driveway`); `name` string or null.

`terms` = `{d_fuel_m, f_heat, A_clear_m2, f_area, f_access, f_shelter, f_water, base_score, vision_penalty}`.
`score = base_score - vision_penalty` (vision_penalty ≥ 0, ≤ 30). `claude` = null or
`{fuel_ring, clear_area_m2, entry, hazards, confidence, reason}`. `flag` = null | `"unsure"`.
`kind` ∈ `parking|park|pitch|stadium|sports_centre|swimming_pool|farmland|meadow|grass|water|building`.
An entry point may carry `approach: true, approach_m` when no graph edge comes within 15 m of the polygon: it is the
nearest graph node within 300 m, so the router can reach the place; `f_access` is still scored from real entry edges (0).
Refuges with `d_fuel < 15 m` are excluded from `refuges.json` (they appear only in `bundles/<county>/excluded.json`).

## Routing (identical in Python `engine/ember_engine/core/router.py` and Swift `Router.swift`)

Profiles from `shared/profiles.json`. Edge cost (seconds) = `length_m / speed(profile, grade) * penalty(profile, edge)`; impassable = +inf.
- impassable if `steps` and profile forbids steps (walker: only if `step_count` is null or > 3), surface unpaved where forbidden,
  `|grade| > max_grade_pct` on ANY profile.
- penalty ×3 (not compounded beyond ×3 per rule, but multiple rules multiply) per profile rules.
- raised kerbs (team decision, added to the spec): `curb_cut == false` is impassable for manual, pushed and power chair
  profiles (`impassable: ["curb_cut_false"]`) and ×2 for walker/cane (`penalize_x2: ["curb_cut_false"]`).
  `curb_cut == "unknown"` stays passable at ×3 for chairs. The graph build sets `curb_cut` true when a
  kerb=lowered|flush|no or sloped_curb node is at the crossing, even if a raised kerb is also tagged there.
- chairs (`uphill_slowdown: true`): uphill speed = `speed_flat * max(0.3, 1 - grade/10)`; downhill with `|grade| > 6` → `speed * 0.8`.
- power chair: path length beyond `range_m = battery_pct/100 * full_range_m` is impassable (A* prunes labels whose cumulative length exceeds range).
- A* heuristic = haversine distance / `speed_flat`.
- `choose(origin_node, fire_bearing_deg|None, perimeter|None, blocked_edges)`: fire-side filter → top 5 by score → route each →
  sort by (time asc, score desc) → return all routed (index 0 = A, 1 = B; rest are swap candidates).
- Fire-side filter: drop refuge if `angdiff(bearing(client→refuge centroid), θ) <= 60`. If perimeter known, drop refuges inside it or within 500 m of its edge.
- `blocked`: set of undirected edge indices; blocking edge i blocks both directions.
- Arrival: within 25 m of any entry point. Destination for A* = nearest entry-point node.

## Turn cues (identical algorithm in Python and Swift — pre-generated audio depends on it)

Templates in `shared/turn_templates.json`. Route → legs (consecutive edges with same `display_name`;
`display_name = name or "the path"` for footway/path/pedestrian/cycleway/sidewalk/steps else `"the street"`).
For each leg: `length_m`, `blocks` = number of nodes along the leg (excluding first, including last) with degree ≥ 3, min 1;
`descent`: if leg's net drop ≥ 4% average and length ≥ 30 m → slope cue.
Cue list:
1. leg 0: `start` → "Start on {street}. Go {direction}." (8-point word from leg bearing)
2. each later leg: bearing delta d (−180..180, positive = right) from last edge of previous leg to first edge of this leg:
   |d|<30 → `continue`; 30≤|d|<60 → `turn_slight`; 60≤|d|<150 → `turn`; ≥150 → `turn_sharp`. side = right if d>0.
3. after every turn/start cue: if blocks ≥ 2 → `keep_blocks` ("Keep going on {street} for {n} blocks."),
   else `keep_meters` with n = round(length/10)*10 clamped to [10, 500].
4. slope cue after keep: `downhill`/`uphill` "Downhill for {n} meters." n as above.
5. last: `arrive` → "Arrive at {refuge}."
Each cue = `{template, vars, text, distance_m (from route start to cue point), node}`. `text` = template filled.
Card steps (4–7) = `card_steps(cues)`: drop slope cues, merge each turn with its following keep cue into one sentence
("Turn left onto Clark Rd. Keep going for 4 blocks."), then if > 7 merge the shortest consecutive legs; if < 4 pad nothing (fewer is ok only when route has < 4 legs).
Minutes = ceil(time_s / 60).

## Audio hashing

`key = sha1(utf8(normalize(text))).hexdigest()` where `normalize` = trim, collapse runs of whitespace to one space.
Pronunciation map applied after hashing, only to the text sent to Cartesia.
Speaker lookup order: client clone dir → `audio/` full string → fragment composition (template fragments + number clips,
only if every fragment cached) → Cartesia streaming (online, 500 ms budget) → AVSpeechSynthesizer rate 0.45. Never silent.

## Plan JSON (`POST /plan` response; also `bundles/<county>/plans/<client_id>.json`)

```json
{
  "version": 1, "county": "paradise", "client_id": "c_…", "generated_at": "…Z",
  "origin": {"lat":…, "lon":…, "node":123, "geocode": "address|latlon", "matched": "…"},
  "fire_bearing_deg": 45.0, "fire_bearing_source": "wind|perimeter|none",
  "profile_key": "manual_chair",
  "choices": [ {"refuge": {<refuge object>}, "route": {"nodes":[…], "edges":[…], "coords":[[lat,lon]…], "length_m":…, "time_s":…, "minutes":…},
                "cues":[…], "card_steps":[…]} ],
  "shelter": {"room": "…", "steps": ["…"]},
  "devices": [{"kind":"oxygen", "hours":4.0, "sentence":"…"}],
  "no_route": false
}
```
`choices[0]` = A, `choices[1]` = B, rest = next-ranked for swap. Bedbound → `choices: []`, `no_route: true`.

## Client profile JSON (staff DB row → plan input → QR)

```json
{"id":"c_…","name":"…","address":"…","lat":null,"lon":null,"zip":"…",
 "mobility":"manual_chair|power_chair|walker|cane|bedbound",
 "transfer":"independent|slide_board|one_person_assist|two_person_lift|hoyer",
 "devices":[{"kind":"oxygen|ventilator|power_chair|cpap","hours":4.0,"battery_pct":null}],
 "vision":"normal|low_vision|blind","hearing":"normal|hard_of_hearing|deaf",
 "cognition":"none|simple_steps","language":"en|es|hmn|other","language_other":null,
 "contacts":[{"name":"…","phone":"…","accessible_vehicle":true,"distance":"…"}],
 "home":{"sleep_room":"…","entry":"…","pets":"…","chair_location":"…"},
 "zone":"…", "voice":{"kind":"default|clone","voice_id":"…","consent_name":"…","recorded_at":"…"}}
```
Profile key: manual_chair → `manual_chair` (navigator switches to `manual_chair_pushed` when caregiver mode is on);
power_chair → `power_chair` (battery_pct from the power_chair device, default 100); walker|cane → `walker`; bedbound → `bedbound`.

QR payload: `ember://p/<county>/<base64url(json)>` where json = `{v:1, id, name, mobility, transfer, devices, vision, hearing,
cognition, language, home, lat, lon, refuge_ids:[A,B], zip?, voice?:{kind:"clone", voice_id}}` (no contacts, no entry code,
no consent record — QR is printed on paper). `zip` drives the Apify outage match; `voice.voice_id` selects the live Cartesia voice.

Arrival text: `arrived_building` when the refuge `kind == "building"`, else `arrived`.
base64url keeps `=` padding (decoders must also accept it unpadded).

Device words for the `leave_now_dev` phrase template `{device}`: oxygen → "Oxygen", ventilator → "Ventilator",
power_chair → "Power chair" (CPAP has no battery deadline and never uses this template).
