# Demo scripts

## Before any demo

1. Build the bundle and the fake bundle: see README "Run it".
2. In the staff tool, stamp and print the demo client's card; run "Generate audio" so `audio/` is filled.
3. Copy `bundles/<county>.zip` into the navigator's Documents (Finder → iPhone → Files → Ember).
4. Phone: airplane mode ON, Bluetooth OFF. Leave it that way for the whole demo.

## Cartesia track: 2-minute video (opens on the phone, not on slides)

| Time | What happens |
|---|---|
| 0:00–1:20 | Caregiver picks the client on Home → WhichWay: points at the smoke → Choose: hears the refuge choice in the caregiver's own (cloned) voice → Go → follows two turns → says "blocked" → hears "Blocking {street}. Say yes to reroute." → says "yes" → hears the new turn |
| 1:20–1:40 | The problem in two sentences and who it is for |
| 1:40–2:00 | How it was built: pre-generated clips, streaming when online, Apple fallback, the consent flow |

## Anthropic track: what the demo must show

- The downgraded lot (a refuge whose `claude.reason` cut its score; on the review screen)
- The side-by-side card (English and the second language, back-translation result)
- The voice read-back ("There's a tree down on Clark" → read-back → yes → new route)
- The key-revoked run (same phrase handled by on-device intents)

## Apify track

- Live run of actor 1 on "Tubbs Fire 2017"; overlay on Santa Rosa with `validate.py --evidence`
- Show the 2 s timeout and cache in the code (staff feed client, navigator `ApifyFeed`)

## Rehearsals

See `notability/BUILD_LOG_GUIDE.md` → Rehearsals.
