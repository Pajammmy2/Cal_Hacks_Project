# Ember: engineer #3 report — DROP 2

Patch: `ember-drop2.mbox` (`git format-patch 88dd45f..HEAD`, on top of drop 1 / efcbbbb). Visuals are frozen at
efcbbbb; every commit after it is logic, data, card, report, or a bug fix against rules 1–6 and the AX5 leftovers.
Everything below was observed in this session on the locally rebuilt Paradise bundle in the iPhone Simulator
(iOS 26.5, iPhone 17 size class, 393 pt width).

## Final test run (this tree)
```
engine:    92 passed                                   (python -m pytest engine;    92 collected)
staff:     72 passed, 2 skipped                        (python -m pytest staff;     74 collected)
navigator: Test run with 150 tests in 28 suites passed (swift test; 150 @Test)
simulator: xcodebuild EmberNavigator (iPhone Simulator) BUILD SUCCEEDED, installed, ran
generic:   swift build  -> Build complete!
overlay gate (W2 tools/overlay_check.py): 12 images checked, 0 with route-over-overlay defects; 0 negative cases missed
```
Total 314 tests (92 + 72 + 150; the 2 staff skips are the real-bundle audio-coverage checks, see Deviations).
The two staff skips become real checks the moment the bundle has an `audio/` dir with clips.

## What is in drop 2
- #5's logic mbox (power-out clock reset, oxygen "leave now", "1 minute" singular, fire age offline/online wording,
  shelter Done→Home, blind skips Which way, "Spoken instructions are in English." notice, `test_card_matches_phone`).
- #5's demo stepping **v2** (v1 dropped): Settings "Demo: step through route" → Navigate `Next`; last tap lands on
  `route.nodes.last` (entry point), intermediate taps 1 m past each group's announce threshold, arrive cue at 60 m,
  Arrived. W1's directional haptics are hooked into `Next` (`AppModel.directionalHaptic`).
- #2's card redesign + thumb commits (`ember-agent2-card-all.mbox`), tighten loop capped at level 2 (never < 16 pt),
  Margaret on two pages.
- Card must-fixes: main image = whole-route satellite corridor (USGS NAIP export of the route bbox, ≥ 300 dpi, never
  upscaled; `staff/ember_staff/corridor.py`) drawn with the phone look (orange route in black casing, green refuge
  outline/pin, white Start dot, label pills, route trimmed at badge/pills); #2's refuge close-up is the small secondary
  image; grey schematic inset removed; headlines "A." / "B." so "Same way as A" resolves; QR ≥ 1.1 in.
- Registry addresses: all six were missing from the bundle's `addresses.json`; the bundle generator now takes the
  registry (`--extra-addresses`), so plans start at the client's own address (Harold, 1204 Buschmann Rd:
  "Start on Buschmann Road. Go east."; Margaret, 1705 Foster Rd: "Start on Foster Road. Go northeast."; Rosa:
  "Start on Pearson Road."; …). The "5974 Pentz Road / Canyon View Drive" card the owner saw came from #2's fixture
  registry, not from this bundle. Staff test: first cue street == address street (or an explicit walk/roll-to cue).
- Refuge-name normalisation in bundle generation (`NAME_FIXES`: "Paradise Performing Arts Center").
- W1 trunk: took (2) directional haptic vocabulary and (3) speech watchdog + stall counter. Did **not** take
  (1) heading arrow + live metres in the strip: at AX5 the strip already wraps to two lines, so the extra element
  would push the map further below the fold (rule 5).
- Review must-fixes (rules 1–5): route cut at the refuge badge, at the map edge, under the position arrow and under
  Re-centre; pills clamped fully inside the map; ≥ 8 pt scale-bar clearance; Re-centre bottom-centre at every
  size; follow camera span 250 m so imagery ≤ 1.5× native (recorded as `imagery.map` in every sidecar, 1.33 at
  follow zoom); Start dot hidden when it would sit under the position arrow (the Start pill stays); Start over moved
  to Settings; AX5 strip kept (wraps, never "…"); `.overlays.json` sidecar for every map screenshot.
- Pass-3 AX5: `WordFit` (CoreText widest-word check) covers buttons, Home names, refuge names, instructions,
  Settings labels and CaregiverInfo; Navigate instruction capped at 44 pt at AX sizes so it is never truncated and
  the strip stays visible; Choose map 190 pt at AX so it is whole above the pinned buttons; mobility icon per profile
  (cane / walker / manual chair / power chair / bedbound); CaregiverInfo capped at 22 pt at AX so "independently"
  never breaks mid-word.
- **Shelter here** (owner): with every route cut mid-route, `NavigatorStateMachine.noRouteLeft` re-runs refuge
  selection from the current node with the lowered bar (`fallbackChoices`: every bundle refuge regardless of score,
  no fire-direction penalty, route time ≤ 300 s at the profile's speed, nearest first) and navigates there with the
  normal cues after "No route to a safe place ahead. Going to the nearest open area."; if nothing is reachable →
  new state `.stayHere`: Henry "No safe road left. Stay in the open, away from trees and cars. Call 911 and read them
  this location.", latitude/longitude + nearest street in large text, Call 911, Repeat. The home shelter script is
  only used within 100 m of the plan origin (`awayFromHomeM`). Tests: cut halfway → nearest fallback chosen; nothing
  reachable → Stay here with coordinates; at home → shelter script (StressTests).
- **QR scanner zoom** (owner): auto-zoom when the detected code is < 20 % of the frame width (ramps
  `videoZoomFactor` ×1.5 steps up to `min(videoMaxZoomFactor, 4)` until it decodes), pinch-to-zoom on the preview,
  spoken + VoiceOver hint "Hold the card about a foot away" after 3 s without a decode (`QRScanner.swift`).
- **Audio coverage** (owner): `pregen.collect` adds each registry client's own sleep-room shelter sentences and every
  spoken constant/inline string from the Swift sources (`Utterance("…")`, `say("…")`, `NavigatorStateMachine` static
  lets); `staff/tests/test_audio_coverage.py` fails when a collected string has no clip in a bundle that has an
  `audio/` dir (skips otherwise).
- "1 hour left" singular in device sentences (Walter's card said "1 hours").
- Dashboard regenerated from the rebuilt bundle (`eval/dashboard.html`, `eval/metrics.json`).

## Pitch alignment: deck claim → metric key → value on this tree
| Deck claim | metric key (`eval/metrics.json`) | value on this tree | action |
|---|---|---|---|
| 98 % of power-chair homes reach a refuge within 45 min | `route_quality.profiles.power_chair.within.45` | **95.9** (49 addresses incl. the six registry homes) | change slide, or re-run on the authoritative bundle |
| 92.7 % reroute success / 356 trials | `robustness.blockage_success_pct` / `blockage_trials` | **95.3 % / 386** (wedge 82.6 % / 368) | change slide |
| 73 % of homes inside the front within 90 min | `replay.fires[Camp (2018)].hours["1.5"].home_burned_pct` | **51.9 at 1.5 h; 94.2 at 1.75 h** | pick the hour and print it |
| 7.1 s for 200 plans | `staff.plan_s` | **7.98 s** (200 planned, 0 failed) | say "under 10 s" |
| 221 tests | pytest collected + swift @Test | **314** (92 + 72(+2 skipped) + 150) | change slide |
| 10,992 edges / 32 refuges / 7 perimeters | `bundle.edges` / `bundle.refuges` / `bundle.historical_perimeters` | **10,952 / 32 / 7** (OSM drift since drop 1; 10,383 nodes, 49 addresses) | change slide |
| 100 % WCAG AAA | `accessibility.all_aaa` | **true** (all text pairs ≥ 7:1) | keep |
| cards fit two pages | `staff.pdf_pages_max` / `pdf_pages_over_2` | **2 / 0** (40 cards rendered) | keep |
| 5 screens at AX5 | `accessibility.ax5_screens` | Home, Which way, Choose, Navigate, Settings all true | keep |

## Margaret's 119 minutes
From her plan file: profile `walker`, route A to the parking lot on Nunneley Road is **3,581.5 m → 119 min**
(B: Performing Arts Center lot, 3,655.4 m → 121 min). Harold (`power_chair`) reaches the same lot over **1,445.6 m
in 33 min**. The difference is 2.5× the distance at the walker profile's speed with its rest model, not a routing
fault; it is why her card leads with "Leave early" and the helper list.

## Demo (v2 stepping)
Settings → "Demo: step through route" on → Home → Start → Which way OK → Choose → Go → tap `Next` once per cue group
(Harold: 7 taps) → "You made it." → Arrived. Each tap speaks exactly one group and fires the matching haptic.

## Known deviations and limitations (honest list)
1. **Bundle**: the locally rebuilt bundle (10,383 nodes / 10,952 edges / 32 refuges / 49 addresses / 8 perimeter
   records, 7 distinct) has no `tiles.mbtiles` content (tippecanoe absent) and **no Henry audio** (0 recorded, 15,775
   sayable strings). It is NOT the authoritative ≈407 MB bundle with 10,005 clips; that bundle and `newclips.tgz`
   never reached this machine, so the dashboard audio panel shows 0 recorded and the two staff coverage tests skip.
   To finish: drop `audio/` into `bundles/paradise`, rerun `eval/build_dashboard.py --bundle …` and `pytest staff`.
2. **Deck numbers** differ from this tree (table above); the authoritative bundle may move them again.
3. **Offline screenshot** (`offline_follow.png`, launched with `-ember-offline`) shows the Drawn (vector) fallback
   because this bundle has no raster tiles and no saved snapshot; it proves the offline path, not cached imagery.
4. **Walter** (bedbound) has no routes by design (`no_route: true`): his card is sections 1–5 with the shelter
   steps; the phone goes straight to the shelter script at home.
5. **AX5 Navigate**: the instruction and the first line of the strip are above the fold; the strip's second line,
   the map and the helper card are reached by scrolling (reviewers allowed scroll). AX5 Which way: the dial is
   reached by scrolling behind the five buttons — not fixed in drop 2.
6. **QR zoom** is Simulator-untestable (no camera); the ≥ 40 cm / 1.1-inch decode is device-verified by the owner.
7. **Shelter-here fallback** candidates are the bundle's refuges (parking lots, parks, masonry buildings already in
   `refuges.json`); the bar is lowered by ignoring score and direction, not by adding new candidate types.
8. Sidecars exist for the 12 map screenshots; Home / Which way / Settings have no map and no sidecar.
9. The Lupe/Rosa cards carry the English notice where the staff tool has no translation.

## Artifacts
`ember-drop2.mbox`; `shots/` (18 PNG: 9 default + 9 AX5, incl. offline) + 12 `.overlays.json`; `cards/` six PDFs
+ page PNGs; `henry_new_strings_after_rebuild.json` (keys not in the 15,770 list already sent; sha1 of the
whitespace-normalised sentence, file `audio/<key>.mp3`); `dashboard.png`, `eval/dashboard.html`; bundle tgz.
