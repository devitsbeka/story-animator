---
name: film-craft-canon
description: MANDATORY craft pass for this project. Use whenever writing or changing a story, narration, shot plan, camera, acting/face, lighting, sound, previs, render settings, or when reviewing any frame/clip/animatic of an episode. Enforces the studio's founding craft canon (Calahan lighting, CML night continuity, two-shot coverage, Reisz & Millar action order, Greengrass reactive handheld, Animation Mentor turn-then-change, Carpenter look-dev test, Hitchcock bomb/shared suspense, Rabiger narration, Das three-column script) plus the lessons ledger, and blocks work that violates it.
---

# Film-craft canon pass

This project's films follow a fixed craft canon. You **must** run this pass on every task that touches story, direction, performance, lighting, sound or picture, and also when you review renders. It isn't optional and it isn't a style suggestion: if the pass fails, fix the cause in the engine (see `factory/lessons/README.md`), not by hand in one shot.

Sources and full distilled rules (with quotes and page references) live in:
- `factory/canon/SOURCES.md`: the 11 founding sources.
- `factory/canon/VISUAL_CANON.md`: lighting, coverage, editing, handheld, performance, look-dev.
- `factory/canon/STORY_SOUND_CANON.md`: suspense, knowledge, narration, sound and picture.
- `factory/lessons/lessons.yaml`: every past defect turned into a rule. Never repeat one.

## Step 1: Automated pass (always run)

```bash
python3 -m factory.canon pass --episode <episode dir or episode.json> [--plates <dir>] [--video <mp4>]
```

It runs the canon checks, the shot validator, the lighting continuity check, the lessons checks and the affected goldens. It writes `qc/canon_report.json`. **Any FAIL blocks** approval, merge and render. If the command or a check isn't implemented yet, say so explicitly and do Step 2 by hand for that rule. Never skip silently.

## Step 2: Craft review (judge it like the source authors would)

Go through each item. For every item, write one line: PASS, FAIL (with the reason) or N/A.

**Story and suspense (Hitchcock, bomb under the table; Rear Window, shared suspense)**
- [ ] CAN-S1 Every threat is **shown to the audience before the character notices it**, with real screen time. The audience's knowledge is ahead of the character's in suspense beats.
- [ ] CAN-S2 Each beat declares **who knows** (audience vs character) and **who can act**. The audience's question changes on purpose, e.g. "Will he look up?" → "Can he turn in time?".
- [ ] CAN-S3 There's a **ticking clock** the viewer can feel. Ordinary actions (restarting the engine) cost visible time once the danger is known.

**Coverage and camera (UW two-shot; Greengrass)**
- [ ] CAN-C1 The **wide establishes geography**: the man, the boat or wreck, and the threat or tree line in one composition before any coverage.
- [ ] CAN-C2 **The close-up is reserved** for the reaction or decision the scene builds toward, e.g. the instant he hears something inland and changes his mind. No casual close-ups.
- [ ] CAN-H1 **Impact handheld reacts:** on an impact the subject briefly escapes the frame, and the camera catches up a few frames late, like an operator reacting. No locked-off impacts.

**Editing order in action (Reisz & Millar)**
- [ ] CAN-E1 Action follows **information order**: obstacle seen by the audience → seen by the character → impact → **cost revealed**. Each step is a deliberate shot or beat, and the pace comes from these choices.

**Performance (Animation Mentor)**
- [ ] CAN-P1 **Turn, then change:** a key expression change never happens during a head turn. He turns, settles, then the thought lands on his face. Check it with the sound off: can you see the thought land?
- [ ] CAN-P2 Faces are alive (lessons L011, L018): eyes lead, saccades, no frozen mask. Hands have shapes and correct palms (L010, L017).

**Lighting (Calahan; CML "Filming at night")**
- [ ] CAN-L1 **Discovery map:** for each sequence, decide which detail the viewer discovers and when, and let the light reveal it, e.g. a reflection reveals the damaged hull while the forest stays dark. Light leads the eye to the story point. Everything else stays subordinate.
- [ ] CAN-L2 **Night continuity:** the close-up must not suddenly feel like daylight next to its wide. Face exposure and key direction stay consistent across the cut, and every light is motivated (moon, a practical lamp, fire).
- [ ] CAN-L3 Light creates depth: foreground, midground and background are separated by value and colour, with a rim on dark subjects against a dark sea.

**Look-dev order (Carpenter, Titanic)**
- [ ] CAN-T1 Before spending on spray, weather or animation, **test the boat + one deck lamp + water together** (the look-dev test frame in previs). The light-on-water look is approved first.

**Narration and sound (Rabiger; Das)**
- [ ] CAN-N1 **Three columns:** every beat has PICTURE, NARRATION and SOUND. The script is written in all three, not narration alone.
- [ ] CAN-N2 **Sound before words where it serves the beat:** e.g. let the first breaker reach us before "He heard the shore before he saw it." Reserved **narration gaps** for actor breath and key sounds (the dry click of the ignition) exist in the voiced timing, and sound fills them.
- [ ] CAN-N3 **Key word versus reveal:** each line declares whether its key word lands before or after the visual reveal, and the cut times honour it. The narrator never talks over the character's breath or reaction beats.
- [ ] CAN-N4 **Voice authority:** it's clear who's speaking and why we trust them. Lines that the picture and sound already carry are cut.

## Step 3: Act on the result
- Any FAIL becomes a fix in the engine or the director prompts, plus a check. If it's a new defect class, also run `python -m factory.lessons add ...` and attach a stress scenario.
- Report the pass to the user as a short table (rule → PASS/FAIL → fix) before presenting renders as done.
- Never present a frame, animatic or episode as finished while any canon item FAILs.

## Data the director must output (so the pass can check it)
- `story.json`: `knowledge_timeline[]` (per beat: audience_knows, character_knows, who_can_act, audience_question, threat_planted_shot); `script_columns[]` (picture, narration, sound per beat); `narration_gaps[]` (start, length, filled_by); per line `reveal_order` (key word before or after the reveal).
- `shotplan`/`episode.json`, per sequence: `discovery_map[]` (detail, shot, light_reveal); `reserved_close_up` (beat id); `action_order` (obstacle_audience, obstacle_character, impact, cost_revealed shot ids); `impact_handheld` (escape_frames, lag_frames); acting `turn_then_change` timing; `lookdev_test` frame.
