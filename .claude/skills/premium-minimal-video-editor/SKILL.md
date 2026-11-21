---
name: premium-minimal-video-editor
description: End-to-end premium minimal cinematic video editing and motion design skill. Use when asked to train on reference videos, build an editing style library, transcribe and cut talking-head footage, create storyboard plans, produce textured typography, illustration, painting, line, graph, and B-roll animations in Remotion, revise edits, add professional sound design, or export short-form video. Enforces a ten-principle design system with approval gates and QA.
---
# Premium Minimal Video Editor — production contract

This is a production workflow, not merely an aesthetic prompt. Execute real tools, generate real source files and video deliverables, and report accurately what was inspected, produced, tested, and omitted. **Never claim to have trained on, extracted, or recreated media that was not provided or accessed.** All ten design principles are mandatory to UNDERSTAND, evaluate, and maintain consistently; use their particular scene types when semantically justified rather than mechanically forcing all ten into every short video.

## Execution modes
1. **TRAIN**: when reference videos and/or Figma board are supplied, process them into the reusable style pack as described in `references/training.md`. Output analyses, contact sheets, individual scene references, motion specifications, and style manifest. Never invent 20 videos, 130 screenshots, or 225 samples; these are tutorial examples, not input files in this package.
2. **PLAN**: when footage or script is supplied, perform transcript, timing and silence analysis; make interactive/editorial storyboard plan with a selectable scene catalog and per-beat script. Do not create full final animations before approval when iterative interaction is feasible. When explicitly told to work autonomously end-to-end, record and approve a documented baseline plan internally and proceed.
3. **BUILD**: generate real Remotion source, select/obtain appropriately licensed assets, render captions and animation, export first cut. Follow approved plan. If no user-supplied source files, clearly identify missing footage rather than falsely producing an edit.
4. **REVISE**: accept timecode-specific changes; patch source and rerender only affected sequences if possible; log diffs.
5. **FINISH**: complete the sound mix, QC, export source package and video.

## Non-negotiable order of operations
0. Read `references/principles.md`, `references/visual-system.md`, `references/production.md`, and `references/quality-gates.md` before planning. Read `references/training.md` before training and `references/audio.md` before final mix. Do not skip any mandatory test.
1. **Inventory** the workspace: footage, sample videos, design references, transcript, fonts, Figma access, licensed visual/audio assets, output specs. Identify what cannot be accessed. Source material inside ZIP is templates and documentation, NOT the tutorial's original media.
2. **Inspect** every available reference and video with `ffprobe`/`ffmpeg` or supported media tools. Work on local copies. If available, extract audio, detect shots, create frame sheets, sample representative frames; analyze all ten dimensions. Use timecoded actual observations, NOT fabricated screenshots.
3. **Transcribe** accurately with a real available ASR engine or supplied transcript, maintaining word start/end times (milliseconds) and confidence or uncertainty. NEVER claim millisecond precision unless tool output actually supports it. Correct names manually when context allows. Do not hallucinate speech. Detect silence via FFmpeg. Keep **30 ms cut padding as a configurable default**; optimize for natural phoneme boundaries, breathing and word tails; do not overcut. Respect intentional dramatic pauses. Keep cut decision list and preserve untouched original.
4. **Draft beat sheet** mapping every phrase to semantic purpose (hook, new concept, example, list, data, emotion, twist, payoff) and visual choice; A-roll priority for concept introductions, human connection, emotional beats, and callbacks; visual explanation for descriptions. Never over-animate.
5. **Build a reviewable storyboard** with video/timecode/transcript on the right and a list of suggested, selectable visual scenes and editorial notes on the left. `scripts/storyboard.py` creates a static, locally interactive HTML planner from JSON. Never call a static exported file a cloud-synced UI. Collect approval if possible; otherwise document autonomous decisions.
6. **Prepare asset manifest**, provenance, rights and alternatives; try browser/internet tools only if actually available and permitted. For missing rights/asset/access, use original coded/vector illustration or user assets, not misleading unlabeled copyrighted references. No assumptions about website access.
7. **Build** a real Remotion project from `assets/remotion-starter/`, implementing the ten scene engines or equivalent reusable components. Consult current installed Remotion APIs and adjust starter code to environment if versions differ. Motion must track word timing precisely; for graphs data must be supported. Render a 10–15 second sample when practical to validate appearance and timing, then full draft.
8. **Review** every scene, frame edges, typography hierarchy, rhythm, real media resolution, transitions, caption accuracy, graph accuracy, full audio. Capture objective artifacts: QC checklist, render metadata, contact sheet, issues with timecodes. Deliver first cut and solicit targeted corrections if interactive.
9. **Revise** without dropping untouched decisions. Every user-supplied revision is a test case. Rerender and prove resolution by inspecting the affected range.
10. **Sound design** AFTER approved picture lock (unless explicitly requested earlier): music under dialogue with controlled dynamics, clicks for text, line/scribble marks for graphs, subtle whooshes, texture and atmosphere. Use licensed/original tracks or synthesize clean original FX. Nothing should overwhelm intelligibility. Loudness and peaks must be measured.
11. **Export** MP4 H.264/AAC or required specs; video source project, machine-readable edit plan, source assets manifest, captions SRT/VTT, preview sheet, QA and change log. Report explicit file paths and missing elements. Validate outputs exist before declaring success.

## The ten *mandatory* style laws
For exact, exhaustive composition and motion behavior read `references/principles.md` and `references/visual-system.md`. Every scene is assigned a `principle_id` P01–P10 or `AROLL`, and validated against them. Never substitute random generic kinetic text or stock-template motion.
- P01: Hierarchical cinematic caption typography; Inter-like sans plus Playfair-like serif italic contrast. Main semantic words bold and central; supporting words small in negative space; generally at most five words per phrase.
- P02: Semantic B-roll plus paper texture, edge vignette and optional peripheral blur, text overlay.
- P03: Art/painting illustration, restrained rough-paper/painterly treatment, integrated typography, short camera slide reveal.
- P04: Thin blue line connecting/interrupting typographic phrases with camera tracking.
- P05: Line plus illustrations, anchor dots, horizontal or zigzag path for sequences.
- P06: Centered quote with large quotation marks on textured monochrome/blue base.
- P07: Central rough-edged illustration, visually weighted in lower half with room for text.
- P08: Side illustration and opposite-side typography; strong balanced composition.
- P09: Single object callout, textured reveal and supporting typography.
- P10: Accurate graph/stats on dark subtle grid, thin glowing white lines and blue moving tracker.

## Operational constraints and truthfulness
- A skill is instructions plus helpers. It cannot grant unavailable browser, Figma, external API, internet, transcription model, voice, music, package manager, filesystem, rendering, or payment capabilities. Check them. Ask only for genuinely blocking access/approval, and offer the strongest feasible alternative.
- Original tutorial's named animation library, Figma board, 20 reference videos and extracted 225 sequences are **not** bundled and cannot be conjured from a text transcript. This ZIP encodes the described visual grammar and workflow; actual fidelity depends on supplied footage, art and review.
- Do not assume named versions of models or subscription capability. Inspect available environment.
- For references from third parties, derive stylistic features rather than presenting someone else's footage or proprietary packs as owned templates. Record source and license.
- Do not fake successful renders or exact alignment; state a blocker and provide the project/code plus next deterministic step.

## Project conventions
Output working directories: `input/`, `analysis/`, `style-pack/`, `plan/`, `assets/`, `remotion/`, `renders/`, `qc/`. Filenames must be predictable and job-specific; preserve provenance. Use `scripts/inventory.py`, `scripts/storyboard.py`, `scripts/plan_validate.py`, `scripts/audio_silences.py`, `scripts/make_contact_sheet.py`, `scripts/qc_media.py` as appropriate; inspect `--help` before use. Use schema `assets/edit-plan.example.json` as the starting data format and compare `references/example-plan.md` for decision logic.

## Phase completion gates
- TRAIN gate: reference inventory, measurements for all ten principle families, style manifest, actual scene/frame references with timecodes, no invented samples.
- PLAN gate: readable word-timed transcript, cut decisions, per-beat purpose, chosen design, story arc, storyboard rendered, assets/access status, human approval or explicit autonomous baseline.
- BUILD gate: each planned scene maps to an implemented component, renders decode successfully, no missing media or font placeholders, meaningful textured design rather than bare text on black.
- REVISE gate: user issues tracked by timecodes and verified solved.
- FINISH gate: dialogue intelligible, sound licensed, no clipping, no clipped typography, no accidental blank frames, correct length and specs, edit source delivered.

## Trigger examples
- "Train this style from these 20 videos and this Figma board" -> TRAIN then offer PLAN.
- "Edit my talking-head clip in this premium minimal style" -> PLAN -> BUILD -> REVISE -> FINISH.
- "Make a full short from this podcast clip with no manual intervention" -> autonomous baseline plan then BUILD + FINISH, clearly report quality and gaps.
- "Change scene at 00:24, extend spiral, fix quotation marks" -> REVISE with regression check.
