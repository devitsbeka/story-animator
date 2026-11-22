---
name: film-craft-canon
description: MANDATORY craft pass for this project. Use whenever writing or changing a story, narration, shot plan, camera, acting/face, lighting, sound, previs, render settings, or when reviewing any frame/clip/animatic of an episode. Enforces the studio's founding craft canon (Calahan lighting, CML night continuity, two-shot coverage, Reisz & Millar action order, Greengrass reactive handheld, Animation Mentor turn-then-change, Carpenter look-dev test, Hitchcock bomb/shared suspense, Rabiger narration, Das three-column script) plus the lessons ledger, and blocks work that violates it.
---

# Film-craft canon pass

This project's films follow a fixed craft canon. You **must** run this pass on every task that touches story, direction, performance, lighting, sound or picture, and also when you review renders. It isn't optional and it isn't a style suggestion: if the pass fails, fix the cause in the engine (see `factory/lessons/README.md`), not by hand in one shot.

Sources and full distilled rules (with quotes and page references) live in:
- `factory/canon/SOURCES.md`: the 11 founding sources.
- `factory/canon/VISUAL_CANON.md`: lighting, coverage, editing, handheld, performance, look-dev (quotes, sub-rules `CAN-L1a`…, engines, fields, thresholds).
- `factory/canon/STORY_SOUND_CANON.md`: suspense, knowledge, narration, sound and picture.
- `factory/lessons/lessons.yaml`: every past defect turned into a rule. Never repeat one.

## Step 1: Automated pass (always run)

```bash
python3 -m factory.canon pass --episode <episode dir or episode.json> [--plates <dir>] [--video <mp4>]
```

It runs the canon checks (`factory/canon/checks.py`, thresholds in `factory/canon/thresholds.yaml`), the shot validator and the lighting continuity check. It writes `qc/canon_report.json` with every sub-rule (`CAN-S1a`, ...) as PASS / FAIL / WARN / MANUAL. **Any FAIL blocks** approval, merge and render: `factory/run` runs it before the previs approval (`--stage plan`) and before publishing (`--stage publish`; an unapproved look-dev test FAILs CAN-T1a there). The director's retry loop runs the same rules while drafting (stage 1: story rules, stage 4: plan rules). Rules still reported MANUAL (they need plates with masks or baked face tracks) must be done in Step 2 by hand. Never skip silently.

## Step 2: Craft review (judge it like the source authors would)

Go through each item. For every item, write one line: PASS, FAIL (with the reason) or N/A.

**Story and suspense (Hitchcock, bomb under the table; Rear Window, shared suspense)**
- [ ] CAN-S1 Every threat is **shown to the audience before the character notices it**, with real screen time ("whenever possible the public must be informed": fifteen seconds of surprise versus fifteen minutes of suspense). The planted shot comes ≥ 2 s before the character notices (short), and the audience's knowledge is ahead of the character's in suspense beats. Surprise is rare and declared. A threat the audience was made to fear ends in **relief**, never in killing the innocent (Hitchcock's Sabotage error).
- [ ] CAN-S2 Each beat declares **who knows** (audience vs character), **who can act** and its **mode** (shared / dramatic irony / suppression / mystery / surprise / relief). When the character's knowledge or agency changes, the audience's question changes in the same beat, and it stays about what happens next, e.g. "Will he look up?" → "Can he turn in time?". Don't let the question sit unchanged: keep the audience's mind occupied.
- [ ] CAN-S3 There's a **ticking clock in the decor** the viewer can read, and its deadline is known before the danger peaks. It only gets worse. Ordinary actions (restarting the engine) cost visible time once the danger is known, and attacks are spaced so the anticipation outlasts the bang ("no terror in the bang, only in the anticipation of it").

**Coverage and camera (UW two-shot; Greengrass)**
- [ ] CAN-C1 The **wide establishes geography**: the man, the boat or wreck, and the threat or tree line in one composition before any coverage. Hold it long enough to read: ≥1.2 s, since a new angle alone takes 8 film frames to register (Animation Mentor p.20). Re-establish after ≤6 tighter shots. Never confuse the audience about the geographical relationship (Reisz p.49).
- [ ] CAN-C2 **The close-up is reserved** for the reaction or decision the scene builds toward, e.g. the instant he hears something inland and changes his mind. Use one hero-face CU per sequence (`reserved_close_up`), on a beat where what he knows or can do changes. It must be long enough to see the thought land (≥1.5 s). No casual close-ups.
- [ ] CAN-H1 **Impact handheld reacts:** on an impact the subject briefly escapes the frame (2-6 f), and the camera catches up a few frames late (3-8 f lag, re-found within 15 f), like an operator who didn't know it was coming. No locked-off impacts. No constant decorative wobble either: the shake is caused by the event. The shot validator's centring and eye-trace rules are exempt inside the impact window.

**Editing order in action (Reisz & Millar)**
- [ ] CAN-E1 Action follows **information order**: obstacle seen by the audience → seen by the character (look → POV → reaction, as in *Naked City* shots 8-9-10) → impact → **cost revealed** in its own held shot (≥2.5 s; the dead dog in *Naked City* holds 3.75 s). Each step is a deliberate shot or beat. The pace comes from what each cut tells, not from cutting fast. Reisz p.49: cutting so fast that it confuses the physical details defeats the object. Every action cut goes to a new angle or a parallel action. Close static shots run shorter than moving long shots. Accelerate only into a mounting climax.

**Performance (Animation Mentor)**
- [ ] CAN-P1 **Turn, then change:** "Never stage an important face change to occur mid-motion. Ever." (Animation Mentor p.19). He turns, settles and lets it sink in, then the thought lands on his face, marked by a blink. Alternatively, start the change just before the turn. Make no expression, pose or direction change in the first or last 8 film frames of a shot (10 f at our 30 fps) unless the action matches across the cut. Check it with the sound off: can you point to the frame where the thought lands?
- [ ] CAN-P2 Faces are alive (lessons L011, L018): eyes lead the head, saccades, no frozen mask. Blinks mark thought shifts and fast head turns, never a 2-second metronome. Holding blinks back is allowed for fear or a transfixed stare, for up to 10 s. Nothing moves without a reason. Hands have shapes and correct palms (L010, L017).

**Lighting (Calahan; CML "Filming at night")**
- [ ] CAN-L1 **Discovery map:** for each sequence, decide which detail the viewer discovers and when, and let the light reveal it, e.g. a reflection reveals the damaged hull while the forest stays dark. "The primary objective of good lighting is to show the viewer where to look" (Calahan §3). One focal point dominates. Before its beat the detail is only hinted, and everything else stays subordinate. Night is low key, "dark but not murky": real blacks, plus at least one hot area.
- [ ] CAN-L2 **Night continuity:** the close-up must not suddenly feel like daylight next to its wide. Face exposure stays within +0.5 EV of the wide, with little frontal fill (≥4:1), and the key comes from the same direction (three-quarter back at night). The close-up may only darken its background (Calahan §9). Every light has one motive and one job (moon, a practical lamp, fire). A practical in frame sets the light direction. Night is cued by colour (cool moon, warm practicals), and the face's shadows stay readable (Cameron, ASC).
- [ ] CAN-L3 Light creates depth: foreground, midground and background are separated by value and colour (warm subject over a cool ground). Put a rim on dark subjects against a dark sea, but no heavy blue backlight wash. Background accents sit at least 1 stop under the subject (CML p.140). Close-ups are shallow, and night shots are not deep-focus.

**Look-dev order (Carpenter, Titanic)**
- [ ] CAN-T1 Before spending on spray, weather or animation, **test the boat + one deck lamp + water together** (the look-dev test frame in previs: `cloud/blender/test/yachtsea_lookdev.py`). This is the Titanic model in Mylar "water", lit for how its practicals "would play". The light-on-water look is approved first, and what the test discovers (gels, LUT, lamp colour) becomes locked parameters. FX and acting renders are refused until the approved test's hash matches the current lighting and materials.

**Narration and sound (Rabiger; Das)**
- [ ] CAN-N1 **Three columns:** every beat has PICTURE, NARRATION and SOUND rows. Picture comes first, and narration "does not lead the narrative" (Das). Each sequence has at least one sound-only row, and ambience runs continuously under everything.
- [ ] CAN-N2 **Sound before words where it serves the beat:** e.g. let the first breaker reach us before "He heard the shore before he saw it." Break phrases apart "to open up spaces for featured sound effects … don't obscure them with talking" (Rabiger). Reserved **narration gaps** for breath, key sounds (the dry click of the ignition) and reactions are **measured in the voiced word timings** after TTS, filled by the sound designer, and never left as dead air.
- [ ] CAN-N3 **Key word versus reveal:** each line declares whether its key word lands before, on or after the visual reveal, and the cut times honour it. Operative words hit the cuts. "The first word to fall on each new image" sets how the shot is read, so the syntax follows the audience's order of perception. The narrator never talks over the character's breath, reaction or reserved close-up.
- [ ] CAN-N4 **Voice authority:** it's declared who speaks (person, persona, knowledge scope) and why we trust them. Each line states what it **adds** that picture and sound don't. Lines that describe what is evident, or that repeat what a sound already said, are cut. Value judgements only come after the evidence. The narration is tried out against the animatic and fits without speeding up.

## Step 3: Act on the result
- Any FAIL becomes a fix in the engine or the director prompts, plus a check. If it's a new defect class, also run `python -m factory.lessons add ...` and attach a stress scenario.
- Report the pass to the user as a short table (rule → PASS/FAIL → fix) before presenting renders as done.
- Never present a frame, animatic or episode as finished while any canon item FAILs.

## Data the director must output (so the pass can check it)
- `story.json`: `knowledge_timeline[]` (per beat: audience_knows, character_knows, who_can_act, audience_question, threat_planted_shot); `script_columns[]` (picture, narration, sound per beat); `narration_gaps[]` (start, length, filled_by); per line `reveal_order` (key word before or after the reveal).
- `story.json` also: `narrator` (person, persona, authority, knowledge_scope), `threats[]` (planted_shot, planted_t, noticed_at, peak_t, outcome), per line `purpose`, `adds`, `evidence` (for value judgements), optional `sound_lead`.
- `shotplan.json`: `sequences[]` {shots, tension, action, `reserved_close_up` {beat, shot, reason}, `discovery_map[]` (detail, shot, frame, light_reveal), `action_order` (obstacle_audience, obstacle_character, impact, cost_revealed shot ids)}; `lookdev_test` (view, elements, lighting_preset, hash, approval, locks); per shot `establishes[]`, `match_action`, `time_cut`, `cut_word`, `reaction_windows[]`, `gaze_away_from[]`, `extra_cu_reason`, `impact_handheld` (impact_frame, escape_frames, lag_frames, recover_frames), `turn_then_change[]` (turn, settle_frames, change), and a `why` on every pose and verb; `story_links` re-points story.json's planned shot references at the shots actually cut. See the field and threshold tables in `VISUAL_CANON.md` and `factory/canon/thresholds.yaml`.
