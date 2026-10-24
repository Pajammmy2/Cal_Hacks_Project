# Ember Project Spec: Offline Last-Resort Evacuation (transcribed)

Oct 23, 2026 · Vijaya Sri Kodavali. Transcribed from the PDF so every lane can read it. CONTRACTS.md pins the details this leaves open.

Ember gives people who cannot evacuate a wildfire on their own, and the people who move them, a plan for the hour when no one comes: where they can survive, how to get there in their chair, in words and a voice they can follow, on paper and on a phone with no network. Scoped to a 50-hour build for Cal Hacks and the Anthropic, Cartesia, Apify, and Notability tracks.

## Scope
**Definition of done:** a nonprofit staff member enters a client's address and profile and prints a reviewed plan card; the same plan opens on an iPhone in airplane mode, speaks the route to a refuge, and re-plans when a judge says "blocked"; the refuge scorer's top tier matches where people actually survived the Camp Fire.

| Component | What it does | Must work |
|---|---|---|
| Engine (Python) | Builds a rolling graph with grades, finds and scores refuges, emits one bundle per county | Offline, precomputed |
| Staff tool (web) | Address + profile in, printed plan card out, with Claude plan text and a review stamp | On a laptop with signal |
| Navigator (iOS) | Opens the plan, picks the refuge on the safe side, speaks turn by turn, re-plans on "blocked", switches to survive-in-place | Airplane mode |
| Claude layer | Vision pass on refuges, plan writer, voice agent with tool use | Only when online; product works without it |
| Cartesia layer | All spoken audio, pre-generated and cached; familiar-voice option | Cached audio offline; live when online |
| Apify layer | Two actors: survivor-evidence for validation, county situation feed for closures and outages | Pre-season and when online |
| Notability | The build log, start to finish | Export on submission |

Does not ship (next steps): BLE responder beacon, buddy pairing and alerts, live fire detection, a sync server, responder triage, a second county, LoRa, multi-language beyond one.
County: the one the nonprofit serves. Paradise (Butte County) is the validation run. Both bundles come from the same script with a different bounding box.

## Users
- **Client**: older adult / mobility disability at home (manual or power chair, walker, bedbound; oxygen, CPAP, power chair dies with the grid; low vision, hearing loss, mild cognitive impairment; may have no smartphone). Constraints: paper first; large type (18 pt min on card, 28 pt on phone); one instruction at a time; spoken slowly, familiar voice if possible; no login, no setup on fire day; nothing that requires reading a map.
- **Caregiver / family / neighbor**: pushes the chair or drives. Holds the phone, so the app routes for the person they are moving. Hands busy: voice in, voice out. Needs the client's transfer method and equipment on screen without asking.
- **Nonprofit staff**: 2–5 people, registry of 100–500 clients. Batch: run the whole registry in minutes. Every card reviewed and stamped by a human before it prints. See Claude's reasoning so they can overrule it. Nothing uploaded anywhere they do not control.

**Design rules**
1. Every fire-day feature works in airplane mode. Network is a bonus, never a dependency.
2. The card is the product; the app is the card that talks and re-plans.
3. One screen, one sentence, one button, at all times on the phone.
4. Speech always, text always, never one without the other.
5. The caregiver is a first-class user; profiles are per client, not per phone.
6. A human stamps every plan. Claude can lower a safety score and write words, never raise a score or decide a refuge.
7. Device runtime is a deadline: oxygen hours and chair battery are inputs to "leave now," not footnotes.
8. Prefer refuges you can shelter inside (large masonry buildings) over open lots when both score; older adults tolerate heat and smoke worse.

## System overview
Deterministic core; sponsors sit beside it, never in the path. Apify actors (evidence + county feed) → Engine (refuge scorer + accessible router) ← Claude vision pass (can only downgrade a refuge). Engine → Staff planning tool (web, run across the registry) → Printed plan card (18 pt, works unpowered); Claude plan writer (plain words, stamped) → staff tool. Engine → Fire-day navigator (iPhone, airplane mode) ← Cartesia audio (cached on the phone), ← Claude voice agent (confirms, then acts). Remove every sponsor box and the demo still runs.

## Offline design
Phone is loaded while there is signal; after that every fire-day feature runs from cache. Rule: define what it does with no network first, then what it adds with one.
Cached per county bundle (~40–120 MB): graph.json (or SQLite); refuges.json (scored, entry points, Claude vision annotations, reasons); perimeters.json (last known perimeter + timestamp, historical perimeters for the demo slider); wind.json (last NWS wind vector + timestamp); offline vector tiles (MBTiles); satellite thumbnails per refuge (JPEG, zoom 18); client profiles entered on this phone; Cartesia audio for every spoken string of each profile's plan plus the generic phrase set.

| Feature | No network (must work) | With network (adds) |
|---|---|---|
| Which side is the fire | Cached perimeter + wind if under 6 h old, else user points the phone at the smoke and the compass bearing is used | Pulls the Apify county feed for latest perimeter and closures |
| Refuge choice | From cached refuges.json, filtered by bearing, ranked by route time | Same |
| Routing and re-planning | On-device A*, all profiles | Same, plus closures from the feed pre-marked as blocked |
| Turn cues (text) | Always from the on-device router | Same |
| Turn cues (speech) | Cached Cartesia audio for known strings; Apple on-device speech synthesis for anything not cached | Cartesia streams new strings live |
| Voice commands | Apple on-device speech recognition + 12-phrase intent matcher (blocked, repeat, slower, louder, I'm pushing, can't move, where am I, how long, which way, stop, yes, no) | Claude handles free speech with tool use; falls back to intents after 2 s without a reply |
| Survive-in-place | Cached text and audio | Same |
| Device-runtime warning | Computed from profile and time since user marked "power out" | Apify feed supplies outage status automatically |
| Plan card | Paper | |
| Staff tool | Not needed on fire day | Full |

Implementation notes: bundle in app's Documents; graph loaded into memory at launch (30–80k edges, < 50 MB). Every network call has a 2 s timeout and a cached answer; no spinner ever blocks a turn cue. Stamp every cached artifact with its timestamp and show the age on screen ("fire data from 3 h ago"); staleness shown, never hidden. Demo in airplane mode with Bluetooth off.

## Engine spec
`build_bundle.py --county <name> --bbox <w,s,e,n>`, once per county on a laptop, target < 20 min.
Inputs: OSM extract (Geofabrik California .pbf via osmnx or pyrosm) → graph, candidate refuges, building footprints, tags. 10 m DEM (USGS 3DEP GeoTIFF) → grade per edge. Fuel model (LANDFIRE FBFM40 GeoTIFF, clipped) → fuel distance. Fire perimeters (CAL FIRE FRAP shapefile) → validation (Paradise) and demo slider. Wind (api.weather.gov gridpoint forecast) → prevailing direction for pre-season ranking. Survivor evidence (Apify actor 1 GeoJSON) → validation overlay.

Graph build:
1. Ways tagged highway in {footway, path, sidewalk, residential, living_street, service, tertiary, secondary, primary, unclassified, pedestrian, cycleway} in bbox. Drop motorways and trunks.
2. Node every intersection; split long edges every 50 m so grade is local.
3. Sample the DEM at each node; grade = |dz| / length per edge, stored signed in the travel direction.
4. Per edge: length_m, grade_pct, surface (paved/unpaved/unknown from surface tag), steps (true if highway=steps or incline=up/down with steps), curb_cut (true/false/unknown from kerb and wheelchair tags), road_class, sidewalk (true if a footway or sidewalk=* present).
5. Emit graph.json: `{nodes:[{id,lat,lon,elev}], edges:[{a,b,length_m,grade_pct,surface,steps,curb_cut,road_class,sidewalk,name}]}`.

Refuge candidates (OSM, in bbox): amenity=parking with area ≥ 4,000 m²; leisure in {pitch, park, stadium, sports_centre, swimming_pool}; landuse in {farmland, meadow, grass} ≥ 1 ha; natural=water and water=lake|reservoir; building in {retail, supermarket, warehouse, school, civic, hospital, industrial} with footprint ≥ 2,000 m² and building:material in {concrete, masonry, brick} when present.

Scoring (0–100, stored with each term): `score = 40 f_heat(d_fuel) + 20 f_area(A_clear) + 20 f_access + 10 f_shelter + 10 f_water`.
- d_fuel: distance from the usable centroid to the nearest LANDFIRE burnable cell or building footprint. f_heat = 0 below 15 m, linear to 1 at 45 m (~150 ft), capped. Radiant-heat floor: any refuge with d_fuel < 15 m is excluded outright.
- A_clear: polygon area minus a 10 m inner buffer. f_area = 0 below 2,000 m², 1 at 10,000 m².
- f_access: 1 if an entry edge from the graph touches the polygon with curb_cut true or a driveway, 0.5 if unknown, 0 if only steps or a fence (barrier=* on every boundary).
- f_shelter: 1 for a qualifying masonry building, 0.5 for a large open paved area, 0 otherwise.
- f_water: 1 for a lake or pool you can enter, else 0.
- Claude vision annotations may subtract up to 30 points or set flag=unsure; never add. Final score and each term print on the card.

Fire-side filter (per query, on the phone): given bearing θ to the fire, drop refuges whose bearing from the client is within ±60° of θ. If perimeter known, also drop refuges inside it or within 500 m of its edge.

Validation (`validate.py --county paradise`): top tier = score ≥ 70; check the Kmart lot (6600 Clark Rd) and Lake Concow are in it, and, as a secondary check, the Walgreens lot (Paradise's only Walgreens per OSM is at 7576 Skyway; the original spec said "Clark Rd" in error; the lot is located live from Overpass and only counts once the evidence actor confirms people sheltered there), and the Feather River Hospital campus is not (tree-ringed, downwind on Nov 8). Overlay Apify actor 1 points and report the share within 300 m of a top-tier refuge. Output a PNG for the slide.

Bundle (`bundles/<county>/`): graph.json, refuges.json (`{id,name,polygon,entry_points,score,terms,claude:{fuel_ring,clear_area_m2,entry,hazards,confidence,reason},thumb}`), perimeters.json, wind.json, tiles.mbtiles, thumbs/, audio/ (added by the Cartesia step). Zip it; the app loads it from Documents.

## Staff planning tool spec
Single-page web app (Next.js or FastAPI + HTMX) on the nonprofit's laptop. No accounts; a passphrase on the page is enough. Data in a local SQLite file the nonprofit controls.
Screens:
1. Clients list. Table: name, address, mobility, devices, card status (none / draft / stamped / printed), last reviewed. Buttons: add client, import CSV (registry columns), run all.
2. Client profile. Form with the fields below. Save runs the engine for this address and opens the review screen.
3. Review. Left: the generated card as it will print. Right: the engine's two refuge choices with score terms, satellite thumbnail, Claude's vision reason, the route drawn on the tile, and the plan-writer text in English and the second language side by side with the back-translation check. Controls: swap a refuge for the next-ranked, edit any sentence, regenerate text, set the stamp. Print is disabled until the stamp is set.
4. Print. HTML to PDF via headless Chromium (Playwright). Letter size, 18 pt body, 28 pt headings, black on white, one sheet front and back.

Profile fields: Mobility (manual chair, power chair, walker, cane, bedbound → routing profile and speed); Transfer (independent, slide board, one-person assist, two-person lift, Hoyer → caregiver instructions on card and app); Devices (oxygen concentrator (battery hours), ventilator (hours), power chair (battery %), CPAP, none → device-runtime deadline); Vision/hearing (normal, low vision, blind, hard of hearing, deaf → card type size, audio vs text emphasis); Cognition (none noted, needs simple steps → reading level target; forces staff review); Language (English, Spanish, Hmong, other → plan writer target language); Contacts (up to 3: name, phone, has accessible vehicle y/n, distance → "Leave early" section); Home (which room they sleep in, entry method (keypad code, key location, unlocked), pets → survive-in-place and responder note).

Card layout (front and back of one sheet). Front: name and address; "1. Leave early" with zone name, the county alert line, and the contacts in order; "2. If no one comes" with refuge A: name, photo thumbnail, 4–7 steps in plain words, minutes at this client's speed, and the route drawn on the satellite image; refuge B the same, smaller. Back: "3. If you cannot move": room, windows and vents, wet towels, tub, phone on and visible, call 911 and say the room; "4. Your devices": runtime sentence per device; "5. For whoever comes": transfer method, chair location, pets; "Reviewed by ____ on ____" box, plus a QR code that opens the same plan in the navigator.

Engine call (POST /plan): {address, profile} → geocode (Nominatim on the local OSM extract, no external call), snap to graph, fire-side filter for the prevailing wind, route to the top five refuges, return the best two with routes, step lists, times, score terms, thumbnails.
Claude calls from this tool: plan writer. Optional; if the API is down the card prints with the engine's templated steps and the stamp still required.
Cartesia calls from this tool: generate the audio set for this client's plan and write it into the bundle folder the app will sync.

## Navigator iOS spec
Native Swift + SwiftUI, iOS 16+, portrait only, always-on screen while navigating. One screen, one sentence, one button.

| State | Screen shows | Buttons | Transitions |
|---|---|---|---|
| Home | Profiles on this phone (name, mobility icon), bundle age ("fire data from 3 h ago") | Start, Add profile (QR from card) | Start → WhichWay |
| WhichWay | If cached perimeter+wind < 6 h: "Fire is to the [NE]. OK?" Else: "Point the phone at the smoke and tap." Big compass arrow | OK / Point | → Choose |
| Choose | Refuge A (name, minutes, photo) in 28 pt; "or B" smaller | Go / Other / Can't move | Go → Navigate; Can't move → Shelter |
| Navigate | One instruction in 28 pt ("Downhill on Clark Rd. 4 blocks."), distance to next turn, countdown vs. fire ETA, map thumbnail with route | Blocked, Repeat, Can't move, mic | Blocked → re-plan, stay; arrival → Arrived |
| Shelter | Survive-in-place steps one at a time, 28 pt, spoken; room name in 60 pt for a window | Next, Repeat, Back | |
| Arrived | "You are at the Safeway lot. Stay in the middle, away from the cars. Keep the phone on." | Done | |

Profiles: Manual chair 8%, 1.2 m/s, impassable steps, surface=unpaved, grade > 8%; penalized ×3 curb_cut=unknown, no sidewalk on primary/secondary. Manual chair pushed 10%, 1.4 m/s, steps, unpaved; same. Power chair 10%, 2.0 m/s, steps, unpaved, edges beyond battery range; same. Walker/cane 12%, 0.6 m/s, steps > 3; penalized grade > 6%. Bedbound: always Shelter.

**Raised curbs (team decision, 2026-10-23):** kerb=raised is impassable for manual, pushed and power chair profiles unless a curb cut / kerb=lowered|flush node is at the crossing; kerb=lowered|flush is passable; unknown (most of the map) is passable at ×3 cost for chairs, not blocked. Walker and cane: raised curb passable at ×2.

Routing (Router.swift): load graph.json into adjacency arrays at launch (≤ 2 s for 80k edges). Cost = length_m / speed(profile, grade) × penalty(profile, edge); impassable = Double.infinity. Uphill speed: speed_flat × max(0.3, 1 − grade_pct/10) for chairs; downhill above 6% also slowed ×0.8. A* with straight-line / max-speed heuristic; < 300 ms to the farthest refuge on an iPhone 12. choose(): fire-side filter, route to top five by score, return the two with the lowest time, ties by score. blocked(at: currentEdge): set that edge and its reverse to infinity, re-run from current GPS snap; keep a session list of blocked edges. Arrival: within 25 m of an entry point. Turn instructions from edge name changes and bearing deltas; fixed phrase templates so every string is pre-generable for Cartesia ("Turn left onto {street}.", "Keep going on {street} for {n} blocks.", "Downhill for {n} meters.").

Voice in (VoiceController.swift): SFSpeechRecognizer with requiresOnDeviceRecognition = true. Mic opens on button ("Hey Ember" out of scope). Intent matcher: 12 phrases with synonyms, keyword match after lowercasing ("blocked", "can't get through", "tree down" → blocked). Confidence below threshold → "Say again?". With signal: transcript goes to Claude. Any tool call that changes the route is read back and waits for "yes".

Voice out (Speaker.swift): look up cached Cartesia clip by string hash; play. Miss → AVSpeechSynthesizer at rate 0.45. Never silent. Haptic on every new instruction; repeat instruction automatically every 45 s in Navigate.

Caregiver mode: profiles per client; Home makes the caregiver pick who they are moving; the "pushed" variant applies automatically when the caregiver profile is selected alongside a manual-chair client.
Device-runtime deadline: on Home, a "Power is out" toggle starts a timer per device from the profile; when remaining hours drop below route time plus 1 h, the app says "Leave now" at the top of every screen.
Accessibility: Dynamic Type up to largest size; VoiceOver labels on every control; contrast 7:1; no color-only meaning; buttons ≥ 64 pt tall.

## Anthropic track: Claude for Public Benefit
Criteria: named community, lived problem, one thing that works Monday, thoughtful use of Claude including where it could go wrong.

Job 1: refuge vision pass (pipeline, pre-season). Model claude-sonnet-4-5 (vision). Batch over top 40 refuges per county. Input: satellite JPEG zoom 18 (Mapbox Static or Google Static Maps, 640×640), optional Street View frame of the entry point, engine's score terms as text. System prompt: "You assess wildfire refuge candidates for people in wheelchairs. Report only what is visible. Never say a place is safe. Output JSON matching the schema." Output schema (structured outputs): `{fuel_ring: 0|1|2|3, clear_area_m2_est: int, entry_wheelchair: "yes"|"no"|"unsure", hazards: [string], confidence: 0–1, reason: string ≤ 200 chars}`. Rule in code: score -= 10 × fuel_ring; entry_wheelchair == "no" sets f_access = 0; confidence < 0.5 sets flag = "unsure". No path raises a score. reason prints on the card and the review screen. Guards against a tree-ringed lot the geometry liked. Demo: show one.

Job 2: plan writer (staff tool, pre-season). claude-sonnet-4-5. One call per card, plus one back-translation call when a second language is set. Input: engine's step list with street names and distances as structured data, the profile (mobility, transfer, devices, cognition flag, language), reading-level target (grade 4 if cognition flag, else grade 6). System prompt: "Write evacuation instructions for an older adult or person with a mobility disability. Short sentences. One action per sentence. Use only the street names, refuge names, and numbers provided; never invent a place or a number. Keep the step order." Output schema: `{steps_en: [string], shelter_en: [string], devices_en: [string], steps_l2?: [string], ...}`. Street names, refuge names, minutes, and phone numbers are injected by code into {placeholders} after generation, so the model never types a number the card prints. Back-translation: a second call translates steps_l2 back to English; code diffs for dropped negations ("not", "never", "don't"), changed digits, missing placeholders. Any diff marks the card "needs review" in red. Human gate: print disabled until reviewed_by and reviewed_at set. Cognition-flagged clients require the reviewer to tick "I read every sentence."

Job 3: voice agent (navigator, fire day, only with signal). claude-sonnet-4-5 with tool use, 2 s timeout, no streaming. Tools: block_edge(street: string, cross_street?: string), set_profile(variant: "pushed"|"solo"), set_status(status: "ok"|"cannot_move"|"at_refuge"), reroute(), repeat_instruction(), report_position(). System prompt: "You help a person evacuating a wildfire in a wheelchair, or the person pushing them. Map what they say to one tool call. Never give directions yourself; the router does that. If unsure, ask one short question." Confirmation rule in code: any block_edge, set_profile, or reroute result is spoken back ("Blocking Clark at Pearson. Say yes to reroute.") and executes only on a yes intent from the on-device matcher. repeat_instruction and report_position execute immediately. Fallback: no reply in 2 s, or any error, silently routes the transcript to the on-device intent matcher. The next turn cue never waits on Claude.

Failure-mode slide:
| Where Claude could hurt someone | What we built |
|---|---|
| Calls a tree-ringed lot clear | Downgrade-only; radiant-heat rule is the floor |
| Drops a "not" in Spanish | Back-translation diff; stamp required |
| Writes above the reader's level | Grade target from the cognition flag; reviewer attests |
| Mishears "left" as "right" | Read-back and yes before any route change |
| API slow or down in smoke | Router never waits; on-device fallback in 2 s |
| Two things it is not allowed to do | Decide a refuge is safe; print unreviewed instructions for a cognition-flagged client |

Checklist: README section "Where Claude is used and where it could go wrong" mirroring the table; one sentence naming the community and the nonprofit, with their quote; demo includes the downgraded lot, the side-by-side card, the voice read-back, and the key-revoked run; office-hours ask: how to evaluate the plan writer on real clients safely.

## Cartesia track
Criteria (25% each): problem and originality; Cartesia meaningfully in the core experience with clear, responsive, natural voice; execution of the main flow with edge cases; accessibility, privacy, responsible use.
Features: TTS (/tts/bytes) to pre-generate every spoken string per plan into the bundle, and streaming TTS when online for uncached strings. Voice cloning from a 30-second consented recording of a caregiver or family member (opt-in, off by default).
Pre-generation pipeline (staff tool, after the card is stamped):
1. Collect every string the navigator can say for this client: plan steps for refuges A and B, every turn-template instantiated with the street names on both routes ("Turn left onto Clark Rd"), the survive-in-place steps, the device sentences, and the fixed phrase set ("Say again?", "Blocking {street}. Say yes to reroute.", "Leave now.", numbers 1–500 for blocks and meters).
2. For each string, POST /tts/bytes with model_id: sonic-2, voice = the client's chosen voice (default: a calm, slower voice at speed 0.85; or the cloned voice), output_format: mp3, 44.1 kHz.
3. Save as audio/<sha1(string)>.mp3 with index audio/index.json {hash: text}. A plan is 150–300 clips, 2–5 MB.
4. Speaker looks up by hash and plays; miss → streaming Cartesia if online, else AVSpeechSynthesizer.
Live path (online only): navigator opens a Cartesia streaming TTS WebSocket on launch when signal exists and sends any uncached instruction; first audio well under a second. If the socket is down, the miss path handles it. Nothing waits more than 500 ms for Cartesia before the fallback speaks.
Familiar-voice consent flow (staff tool): 1) Staff open "Record a voice" with the caregiver present. 2) Screen shows: "Your voice will be used only to read [client]'s evacuation plan aloud on their phone. It is stored by the nonprofit and can be deleted at any time." Caregiver taps "I agree" and says their name and the date on the recording. 3) Record 30 s of the caregiver reading the plan's first section. 4) Create the clone, generate the plan's audio set with it, store the consent text and timestamp with the profile, print "Voice: [name], recorded [date]" on the card. 5) Deleting the profile deletes the clone.
Edge cases: pronunciation map ("Skyway" → "sky way") applied before generation; a new instruction stops the current clip, "repeat" replays it; clips normalized to −1 dBFS, AVAudioSession .playback with .duckOthers; hearing loss: every spoken string also on screen in 28 pt, haptic on each instruction.
Checklist: README: setup; Cartesia features used (TTS bytes, streaming TTS, voice cloning); known limitations (clone generation needs signal; uncached strings use Apple TTS offline; English and one second language only). No API keys in the repo; .env.example provided.

## Apify track
Actor 1: `wildfire-refuge-evidence` (Best Actor). Given a fire, find where civilians sheltered and survived, as geocoded points with sources. Input: `{fire_name: string, year: int, region_hint?: string, max_pages?: int (default 60)}`. Sources: Google News search results for `"<fire_name>" survived OR sheltered OR "took refuge"` via apify/google-search-scraper called from inside this actor; article bodies via apify/website-content-crawler; Reddit via apify/reddit-scraper-lite on the fire name. Public pages only. Extraction: each article body → Claude (claude-sonnet-4-5, structured output): "Extract places where people sheltered during this fire and survived. Return only places named in the text." Schema `[{place: string, kind: "parking lot"|"lake"|"field"|"building"|"road"|"other", quote: string ≤ 240 chars, people_count_hint?: int}]`. Geocoding: Nominatim with region_hint bias; keep results within 50 km of the fire perimeter centroid when FRAP data is available. Dedupe: cluster within 150 m; keep all quotes and URLs per cluster. Output dataset (GeoJSON FeatureCollection): `{geometry: Point, properties: {place, kind, quotes: [{text, url, outlet, date}], mentions: int}}` plus summary.json with counts by kind. Privacy rule in code: strip person names from quotes with a simple NER pass; store places and what happened, never who. Used by validate.py (share within 300 m of top-tier). Demo: run live on "Tubbs Fire 2017" and overlay on Santa Rosa. Publishing: apify push, Store listing (title, description, input schema with examples, README with the privacy rule), public; 30-second Camp Fire run as example dataset.

Actor 2: `county-fire-situation`. Input `{county: string, state: "CA"}`. Sources: CAL FIRE incidents (active incidents in county, acres, containment, updated); Caltrans QuickMap / LCS (full and partial closures with lat/lon and description); Genasys Protect / Zonehaven public zone pages (zone id, status normal/warning/order, updated); PG&E outage map / PSPS (outage polygons or ZIPs, est. restoration). Output: `{county, fetched_at, incidents: [...], closures: [{lat, lon, road, kind, since}], zones: [{id, status, updated}], outages: [{area, kind: "psps"|"unplanned", est_restore}]}`. Schedule every 15 min during demo; otherwise on demand. Used by: staff board (zone status per client, outage flag); navigator online (closures within 2 km → blocked edges before routing; device-runtime timer when client's ZIP in outage). Build Genasys and Caltrans first; CAL FIRE and PG&E if under budget. Degrades per source: a failed source returns an empty array with an error note, never a failed run.
Consumption: staff tool and navigator call the Apify API (GET /v2/datasets/<id>/items) with a 2 s timeout and cache the last result. No fire-day feature depends on either.
Checklist: README "Where Apify is used"; actor 1 public with README, input examples, privacy rule; demo includes live run of actor 1 on a second fire and the overlay; code shows the 2 s timeout and cache.

## Notability track
One notebook, "Ember build log": 1) Before the hackathon (handwritten first sketch; nonprofit call recorded as audio with live handwritten notes; two evacuee conversations; photo of judging criteria annotated). 2) Design (hand-drawn refuge-scoring diagram; navigator state machine drawn by hand; plan card sketch photographed and annotated; imported Paradise map PDF with Kmart lot, Walgreens lot, Lake Concow circled). 3) Build (page per lane, handwritten log every 4–6 h; screenshots of first route, first card, first spoken instruction; cut-lines list crossed out). 4) Claude and sponsors (failure-mode table by hand; Cartesia consent wording; Apify input schema sketch). 5) Pitch (Smart Notes outline, rehearsal timing, judge Q&A).
Capture schedule: Before Friday — sections 1 and first half of 2; Hour 0 — team plan photo, lane assignments; every 4–6 h — one handwritten paragraph per lane, one screenshot each; Hour 26 (freeze) — crossed-out cut list, "what changed since the sketch"; after each rehearsal — timing and Q&A; Submission — export PDF and share link.
Show: handwriting throughout; ≥ 3 audio recordings synced; 2 annotated PDFs; 1 Smart Notes page; photos of paper sketches with ink on top.
Checklist: notebook link and PDF on Devpost; one submission paragraph ("Notability was where the nonprofit call was recorded and where the scoring and state machine were drawn before they were coded; the build log shows what we cut and why."); first-sketch and final-architecture pages side by side at the opening.

## 50-hour plan
Four lanes, hard freeze at hour 38. A Engine + Apify; B Navigator; C Staff tool + Cartesia; D Community + demo (Akshita). Hours 38–50: integration fixes only; four rehearsals (normal, Claude key revoked, Cartesia unreachable, judge interruption); record the 90-second video and the Cartesia 2-minute video; print cards.
Cut lines if behind at hour 24: 1 Apify actor 2; 2 Cartesia voice clone; 3 second language; 4 Claude voice agent; 5 vision pass on the county bundle; 6 device-runtime timer. Never cut: airplane-mode routing with re-plan, the printed card with a stamp, the Paradise validation slide, the key-revoked run, the nonprofit quote.

## Definition of done per component
| Component | Done when | Check |
|---|---|---|
| Engine | Both bundles build in < 20 min; Paradise top tier contains Kmart and Lake Concow (and Walgreens if the evidence actor confirms it) and excludes the hospital campus | validate.py prints PASS and the overlay PNG |
| Graph grades | Grade on a known hill matches the DEM within 2% | Spot-check five edges |
| Router | Routes to every top-five refuge from ten random addresses in < 300 ms each on an iPhone 12; no route uses a step edge for a chair profile | XCTest with the county graph |
| Blocked re-plan | Blocking the current edge yields a different route or a clear "no route, shelter" within 1 s | XCTest + manual |
| Fire-side filter | A refuge 30° off the fire bearing is excluded; 90° off is kept | Unit test |
| Airplane mode | Full flow Home → Arrived with radios off, including speech | Manual |
| Speaker | Cached clip plays within 200 ms; uncached falls to Apple TTS without a gap > 500 ms | Manual |
| Intents | All 12 phrases plus three synonyms each recognized on-device | Scripted test |
| Claude agent | "There's a tree down on Clark" → block_edge, read-back, yes, new route; key revoked → intents handle the same phrase | Manual |
| Plan writer | Card text at target grade level (readability score); back-translation diff catches a planted dropped "not" | Unit test with a seeded error |
| Stamp gate | Print disabled until reviewer fields set; cognition flag requires the attestation tick | Manual |
| Card print | Letter PDF, 18 pt body, route visible on the satellite image, QR opens the plan in the app | Print one |
| Cartesia pre-gen | Every string the navigator can say for a plan has a clip; index matches | Script asserts no misses on a dry run |
| Consent flow | Consent text, name, date stored and printed; deleting the profile deletes the clone | Manual |
| Apify actor 1 | Runs on "Camp Fire 2018" and "Tubbs Fire 2017"; ≥ 60% of points within 300 m of a top-tier refuge on Paradise | Run log + overlay |
| Apify actor 2 | Returns Genasys zones and Caltrans closures; a failed source yields an empty array, not a failed run | Run with one source URL broken |
| Notability | Three audio notes, two annotated PDFs, a build-log page per lane, exported PDF | Checklist |
