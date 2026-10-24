# Notability: "Ember build log"

One teammate owns this notebook; everyone else hands them things to put in. About 90 minutes across the weekend.
Notability is a hand-written, audio-synced tool, so this file is the plan and the checklist, not the notebook itself.

## Dividers

1. **Before the hackathon**
   - [ ] Handwritten first sketch of the idea
   - [ ] Problem research: recorded as audio with handwritten notes taken live (audio sync is what judges look for), e.g. a talk-through of the Camp Fire survivor accounts
   - [ ] Evacuee conversation 1: audio + live notes
   - [ ] Evacuee conversation 2: audio + live notes
   - [ ] Photo of the printed judging criteria, annotated in ink
2. **Design**
   - [ ] Hand-drawn refuge-scoring diagram with the five terms (40 heat, 20 area, 20 access, 10 shelter, 10 water; d_fuel < 15 m excluded)
   - [ ] Navigator state machine drawn by hand before it is coded (Home → WhichWay → Choose → Navigate / Shelter → Arrived)
   - [ ] Plan card sketched on paper, photographed, annotated
   - [ ] Imported PDF of the Paradise map with the Kmart lot, Walgreens lot, and Lake Concow circled (`bundles/paradise/validation.png` exported to PDF works as the base)
3. **Build**: one page per lane (A Engine + Apify, B Navigator, C Staff tool + Cartesia, D Community + demo)
   - [ ] Handwritten log every 4–6 h per lane: what was tried, what broke, what was cut
   - [ ] Screenshot: first route (annotated)
   - [ ] Screenshot: first card (annotated; `staff/out/sample_card.pdf`)
   - [ ] Screenshot: first spoken instruction (annotated)
   - [ ] Cut-lines list, items crossed out as they are cut (list below)
4. **Claude and sponsors**
   - [ ] Failure-mode table drafted by hand before it becomes a slide
   - [ ] Cartesia consent-flow wording drafted and edited
   - [ ] Apify actor input schema sketched
5. **Pitch**
   - [ ] Pitch outline in Smart Notes
   - [ ] Rehearsal timing notes (4 rehearsals)
   - [ ] Judge questions and answers after each rehearsal

## Capture schedule

| When | What goes in |
|---|---|
| Before Friday | Sections 1 and the first half of 2 |
| Hour 0 | Photo of the team plan; lane assignments handwritten |
| Every 4–6 h | One handwritten paragraph per lane, one screenshot each |
| Hour 26 (freeze) | Crossed-out cut list; the "what changed since the sketch" page |
| After each rehearsal | Timing and judge Q&A notes |
| Submission | Export the notebook as PDF and share the Notability link |

## Features to show deliberately

- [ ] Handwriting throughout
- [ ] At least three audio recordings synced to notes
- [ ] Two imported PDFs annotated (Paradise map, judging criteria)
- [ ] One Smart Notes page (the pitch)
- [ ] Photos of paper sketches with ink annotations on top

## Cut lines (copy by hand; cross out as cut, if behind at hour 24)

1. Apify actor 2 (keep actor 1 and the validation overlay)
2. Cartesia voice clone (keep Cartesia TTS pre-generation)
3. Second language (keep English + the stamp)
4. Claude voice agent (keep on-device intents with read-back)
5. Vision pass on the county bundle (keep it on Paradise for the slide)
6. Device-runtime timer

Never cut: airplane-mode routing with re-plan, the printed card with a stamp, the Paradise validation slide, the key-revoked run.

## Rehearsals (hours 40–48), each timed and logged here

1. Full pitch, normal conditions, five minutes, one teammate as judge asking the hard questions.
2. Claude key revoked for the whole run (`unset ANTHROPIC_API_KEY`; clear it in the app settings). Everything must still route and speak.
3. Cartesia unreachable (block `api.cartesia.ai` in /etc/hosts or turn on airplane mode). Apple fallback must be seamless.
4. A judge takes the phone and says something unscripted; a judge closes a road on the map. The presenter does not touch the phone.

Backup assets on a USB stick and a phone: screen recording of the full flow, printed cards, validation PNG, pitch PDF.

## Submission checklist

- [ ] Notebook link and PDF export attached to the Devpost
- [ ] One paragraph in the submission: "Notability was where the scoring and state machine were drawn before they were coded; the build log shows what we cut and why."
- [ ] The first-sketch page and the final-architecture page side by side as the opening of the notebook
