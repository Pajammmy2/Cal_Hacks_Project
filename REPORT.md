# Ember: engineer #3 report

Patch: `ember-agent3.mbox` (`git format-patch --binary base..HEAD`, many small commits). Screenshots and the follow-map
recording are attached beside this file. Every number below was observed in this session on the Paradise bundle
(`paradise-noaudio.zip`, 10,412 OSM nodes, 10,992 edges, 32 refuges, 45 addresses) in the iPhone Simulator
(iOS 26.5, iPhone 17 size class: the Mac had no iPhone 14 Pro runtime; it is the same 393 pt width).

## (a) What changed and why

### Visuals (phone)
- **Look A "Signal" is the default**: real Apple satellite photo (`.satellite`, no hybrid labels) under a dark navy veil
  (`Theme.mapVeil`), route lit in `Theme.route` (light blue) with a black casing; refuge outline + icon + name pill;
  Start pin; scale bar; north arrow. Street labels only where the route turns onto a street, at most 4, overlap-free
  (`drawTurnStreetNames`), the upcoming turn's street first. Clutter removed: no entry pin, no POI labels.
- **Look C "Blueprint" is the offline/no-photo fallback and a Settings toggle** (`Settings → Map: Satellite / Drawn`,
  `Theme.mapStyleKey`): vector streets from `graph.json` on navy land, steel-blue roads, used automatically when there
  is neither signal nor a saved photo.
- **Following map on Navigate (addendum 4)**: the whole route for 1 s, then an animated zoom to a 150 m heading-up
  view centred 22 % ahead of the user (`FollowCamera`, EmberCore; `AppModel.enterNavigateCamera/animateCamera`).
  Heading = compass, else the route's travel heading (so the Simulator rotates too); north-up when neither exists.
  Drag/pinch pauses following; a `Re-centre` button (EmberButtonStyle, ≥ 64 pt, VoiceOver label + hint) resumes.
  Labels, Start pin and refuge adapt: off-screen refuge becomes an edge pill "→ name", Start hides when behind you,
  the north arrow and "you" arrow turn with the map, the scale bar follows the zoom.
- **Offline follow view never goes grey**: "Save satellite snapshot" (Settings) now also writes 420 m corridor tiles
  every 180 m along each route (`SatelliteCache.corridorBoxes`, files `satellite/<client>_<i>_c<j>.jpg|json`); the
  map picks the sharpest tile containing the view (`SatelliteSnapshot.covering`) and falls back to Blueprint for any
  gap. Verified with `-ember-offline` (forces the offline path) after one online save: 90 tiles for Harold, the
  follow view showed sharp photo tiles the whole route (`navigate_offline_follow*.png`). I did not cut the Mac's
  network (it is this session's lifeline); `-ember-offline` disables the live MapKit path exactly as airplane mode
  would (`online == false`).
- **Big maps**: Choose A map 360 pt (300 at accessibility sizes), B 140 pt; Navigate 340/300 pt with a one-line
  stat row (`StatLine`) instead of three tiles.
- **AX5 wrap/truncation root cause fixed**: `Theme.font` used `Font.custom(_, size:)`, which Dynamic Type scales a
  second time on top of `@ScaledMetric`, so Inter/Hyperlegible buttons became "Bloc…" while Apple's font behaved.
  Now `fixedSize:`. Instruction text bounded at 56 pt. Font choices two per row (three across truncated
  "Hyperlegible"). Checked at AX5 on Home, Which way, Choose, Navigate, Settings: no wrapped or truncated button.
- Colours unchanged: navy `#040917`-ish background, dull steel-blue controls, white text; all six Theme pairs ≥ 7:1
  (computed in the dashboard). Inter stays default.

### Logic (phone)
- Which way with stale fire data / no compass no longer dead-ends: a `Not sure` button (and "no") plans with the
  historical fire-direction prior from the bundle (`history.json`) when there is one, else without a bearing
  (`NavigatorStateMachine.skipFireDirection`). Spoken via the new phrase `history_dir` ("No fresh fire data. Past
  fires here came from the east.").
- Crash fixed: first GPS fix on Navigate hit `pts[1...0]` in the walked-route path when still on the first edge
  (`Range requires lowerBound <= upperBound`, reproduced with `simctl location`, fixed in `drawRoute`).
- Fire ETA tile only when a real number exists (the "?" tile wasted a third of the row).
- Cue quality on real OSM: a short unnamed stub between two legs of the same street (sidewalk/service ping-pong)
  is folded into the street, Python and Swift alike (`_merge_pingpong` / `mergePingpong`), so the phone no longer
  says "the side road, then Skyway, then the side road".

### Features added (justified)
- Follow map + Re-centre (owner's addendum 4; a static overview cannot be read at arm's length while rolling).
- `Not sure` on Which way (older adults without a compass must still get a plan).
- Historical-fire input end to end (addendum 2): engine ranks refuges down for recent burns, records the home's
  burn history and the fire-direction prior in every plan; staff review shows it; dashboard replays it.
- Staff: workflow steps bar, status summary cards with filters, "Next:" guidance, Print queue page, past-fire flag
  per client. A volunteer with 200 rows always knows the next click.

### Features removed
- Ranking terms ("score 52.2 of 100, heat 27.9, …", "Claude, satellite photo…") off the **printed** card: jargon
  for whoever picks the client up, still on the review preview for the reviewer.
- The entry pin and the always-on street names on the map; the "?" fire-ETA tile.

### Staff + engine
- **Cards fit two pages for long OSM routes**: `cues.card_steps` keeps 4-7 steps *and* a 90-word budget per route
  by chaining short hops ("Turn left onto Gate Lane, then Cabernet Lane, then Clark Road."); route B reuses the
  shared start ("Same way as A until Skyway." new template `same_way`, printed only). On 60 synthetic clients
  (sample profiles cycled over the 45 OSM addresses) 3-page refusals went 8 → 3 → 1 (dashboard: 39 cards rendered,
  max 2 pages, 1 refused). The last one prints anyway at the tightest layout with its real page count (a 3-page
  card beats a 403) and the review page says so.
- Staff review: "Past fires here" panel with the county's recorded perimeters (red = since 2017), home/route/refuge
  flags, why a refuge was ranked down (×factor), and the offline prior with its source fires. Clients list flags
  "home burned". Larger type, Inter.
- Engine `core/history.py`: `burn_history`, `refuge_factor` (−8 % per recent fire, max −25 %: deliberately mild,
  because the Camp perimeter contains every Paradise refuge and a flat penalty would not rank anything), weighted
  centroid-based `prior_bearing`, `history.json` baked into bundles, plan `history` block. FRAP entries carry the
  unclipped perimeter centroid.
- Eval dashboard `eval/build_dashboard.py` (see regeneration below).

## (b) What was tested and how

Final matrix (same tree as the patch; the dashboard run also re-executes all three suites and prints the counts):

```
cd engine    && python -m pytest          # engine
cd staff     && python -m pytest          # staff
cd navigator && swift test                # EmberCore (incl. parity with engine/tests/parity/fake_parity.json)
cd navigator && xcodegen generate && xcodebuild -project EmberNavigator.xcodeproj -scheme EmberNavigator \
   -destination 'platform=iOS Simulator,id=<sim>' build          # simulator: built, installed, ran
cd navigator && xcodebuild -project EmberNavigator.xcodeproj -scheme EmberNavigator \
   -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO build  # device: built, no errors
cd engine && python fixtures/make_fake_bundle.py && python tests/parity/dump_parity.py   # fake bundle + parity dump
```
Results pasted at the end of this file (`## Final test run`). Baseline at `base` was engine 74 / staff 53 / swift 70.
New tests: engine `test_history.py` (7), `test_eval.py` (4), card-step word budget, ping-pong legs, route-B shared
start; staff workflow/print-queue/past-fires (2); Swift `FollowCameraTests` (6) and stale/no-compass + `HistoryFile`
decoding in `StateMachineTests`.

By hand in the Simulator (Harold Kim, Paradise bundle, location set to his home `39.748562,-121.615275`):
- Home → Start → Which way ("Fire is to the southeast. OK?") → Choose (A the parking lot on Nunneley Road 33 min,
  B the Paradise Preforming Art Center lot 34 min) → Go → Navigate, at default size and at AX5
  (`xcrun simctl ui booted content_size accessibility-extra-extra-extra-large`).
- Follow map: overview → zoom animation → heading-up follow; drove 121 GPS points every 12 m along route A with
  `xcrun simctl location booted set` (recording `follow_demo_small.mp4`, 1.3 MB, ends on "You made it.");
  drag paused following and showed Re-centre (`navigate_paused_recentre.png`); Re-centre resumed.
- Blocked mid-route → re-plan ("Keep going on Buschmann Road for 6 blocks", `navigate_reroute.png`).
- Offline: Settings → Save satellite snapshot (90 files), relaunch with `-ember-offline`, Navigate: photo tiles
  under the follow view along the drive, no grey.
- Route vs aerial: `alignment_routeA_vs_usgs.png` draws plan A's coordinates over USGS imagery (EPSG:3857,
  1.08 m/px): the line sits on the pavement of Buschmann Rd, Recreation Dr, Pearson Rd, Clark Rd and the side road
  into the lot; the Simulator's satellite view shows the same alignment (`choose.png`, `navigate.png`).
- Staff tool: login → import `sample_registry_paradise.csv` (6) → Run all (1.0 s) → review Harold (past fires
  panel, two routes, card preview) → stamp → Print queue → PDF. Screenshots `staff_*.png`. Throughput test with
  200 synthetic clients inside the dashboard: 200 imported in 0.26 s, 200 planned in 9.5 s, 39 cards rendered
  (max 2 pages).

## (c) Known gaps (not verified)
- Real microphone, camera/QR scan, VoiceOver on a device, haptics, compass heading (the Simulator has none; the
  follow view used the route's travel heading), Cartesia voice (no key; Apple fallback heard in the Simulator).
- Airplane mode proper: verified through `-ember-offline`, not by disabling the Mac's network.
- Live MapKit satellite in the follow view relies on Apple tiles being cached; with signal it is used, without
  signal the saved tiles/Blueprint take over. Tile caching inside MapKit itself was not measured.
- Historical data: FRAP returned only Camp (2018) and Honey (2017) inside the 10 km Paradise bbox for 2017-2025;
  North Complex, Dixie, Park etc. lie outside it. The fire-direction prior is a centroid proxy (Camp 109° "east";
  documented wind was north-easterly). Corridor penalties beyond refuge ranking were not implemented.
- The replay front model (straight front at 7.5 km/h) is an explicit assumption, stated on the dashboard.
- 1 of 200 synthetic clients (t0031) still needs 3 pages (two very long routes + devices). It prints with a note.
- Voice command phrasing breadth ("louder" repeats and raises volume: code path present, not heard on a device).

## (d) Three-minute demo
1. (0:00) Staff laptop: Clients page, "Next: review and stamp 6 cards", the steps bar. Open Harold: two real routes,
   the card, **Past fires here**: his home burned in Camp 2018, both routes inside the perimeter, "without live fire
   data the phone assumes fire from the east". Stamp, Print queue, PDF.
2. (0:50) Phone (projected): Home → Start. Which way: compass arrow; "Not sure" exists for people without a compass.
   Choose: satellite photo, the route on real roads, refuge outline. Go.
3. (1:30) Navigate: whole route, then the map zooms and turns with you; drive the GPS along Buschmann Road; "Blocked"
   → reroute in a second; drag the map → Re-centre. Switch to AX5 text: nothing wraps.
4. (2:30) Dashboard slide: 45 addresses × 4 profiles, 93 % reroute success under random blockages, the Camp Fire
   replay (homes burned vs routes cut by quarter hour), 100 % AAA contrast, 200 clients planned in 9.5 s.

## (e) Remaining risks, ranked
1. Audio: 9,885 sayable clips for 6 clients, 0 recorded in this bundle; anything un-recorded speaks in Apple's voice.
2. The follow view's live MapKit layer in weak signal (tiles half-loaded): the snapshot path covers it only after
   staff/owner saved snapshots for that client.
3. Camp-perimeter geometry makes every in-town refuge "historically burned"; the mild factor keeps ranking useful but
   a county with refuges outside the perimeter would benefit more. Needs a wider bundle bbox.
4. Long routes (> 4 km for a manual chair) produce 100+ word cards; one in 200 still spills to 3 pages.
5. Compass/heading-up behaviour untested on hardware (magnetic vs true north, jitter: `headingFilter = 2`).
6. Staff tool runs a single process with SQLite; fine for one volunteer, untested with several at once.

## Regenerating the dashboard
```
cd eval && ../.venv/bin/python build_dashboard.py --bundle <bundle dir> --run-tests   # ~2.5 min
# writes eval/dashboard.html (self-contained) and eval/metrics.json; --quick skips tests + throughput
```
Inputs: the bundle (graph, refuges, addresses, perimeters/history, plans), `staff/sample_registry_paradise.csv`,
`shared/`, `Theme.swift` colours (kept in sync by `engine/tests/test_eval.py`), `eval/screens.json` (manual AX5
check record). Sources and dates are listed on the page.

## Final test run (this tree)
```
staff:     55 passed in 8.15s
engine:    88 passed in 1.60s
navigator: Test run with 78 tests in 14 suites passed after 2.172 seconds.
simulator: xcodebuild EmberNavigator (iPhone Simulator) built, installed, ran
device:    xcodebuild -destination generic/platform=iOS CODE_SIGNING_ALLOWED=NO built, no errors
```
