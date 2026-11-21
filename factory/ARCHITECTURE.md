# Episode Factory

The goal: **one idea in, one finished, Netflix-grade 9:16 episode out.**
- Everything is directed from the first step and assembled by code, with no image-to-video models.
- Ten ideas can run at once.
- A house style is locked first. More styles plug in later as data.

```
 IDEA ──► 1 DEVELOP ──► 2 BREAKDOWN ──► 3 LIBRARY ──► 4 DIRECT ──► 5 VOICE+SOUND ──► 6 PREVIS ──► 7 RENDER ──► 8 FINISH ──► 9 QC ──► EPISODE
          story/hook    scenes+assets   reuse/source   shots+acting  VO, SFX, music     gate: boards  Blender GPU   Remotion      auto + vision
```

## Stage contracts

Every stage writes one validated JSON artifact under `episodes/<id>/`. Each stage is idempotent and resumable.

| # | Stage | Agent / tool | Reads | Writes | Gate |
|---|---|---|---|---|---|
| 1 | Develop | Director (Claude API) + `recipes/ENGAGEMENT_RECIPE.md` + `recipes/PIXAR_RECIPE.md` | idea, style | `story.json`: logline, hook, stakes, beat sheet (story spine), narration with performance tags, suspense devices, fact sheet with sources | engagement checklist |
| 2 | Breakdown | Breakdown agent | story.json | `breakdown.json`: locations, sets, characters, props, FX, vehicles, time of day and weather per scene, each tagged with what it must DO on screen | every narration line maps to a picture |
| 3 | Library | Librarian agent + `library/` adapters | breakdown.json, `library/catalog.json` | `manifest.json`: for each element, one of REUSE (internal id), SOURCE (provider, asset id, licence), or BUILD (procedural recipe), with hashes and licences | nothing unlicensed, nothing missing |
| 4 | Direct | Director + Cinematographer + Gaffer + Animator agents | story, breakdown, manifest, recipes | `episode.json`: shots (camera, staging, acting, face, props, FX, light rig, grade), cut on narration beats | shot-language and lighting checklists |
| 5 | Voice + Sound | ElevenLabs (VO) + sound designer agent | narration, episode.json | `audio/narration.mp3`, word timings, `sound.json` (ambience beds, spot FX on frames, risers, music cues, ducking) | loudness (LUFS) and sync checks |
| 6 | Previs | Blender (low res, EEVEE) | episode.json | `boards/` contact sheet and animatic mp4 | **human approval gate** |
| 7 | Render | Blender workers on AWS GPU (shot × frame-range jobs) | episode.json, manifest | `plates/<shot>/####.exr` | per-frame technical QC |
| 8 | Finish | Remotion | plates, sound.json, captions | `final/episode.mp4` (1080×1920) | |
| 9 | QC | Automatic checks + vision model | final mp4, recipes | `qc/report.json`; failing shots go back to stage 4 or 7 | retention, framing, eyeline, exposure, caption-safe-area checks |

## The internal library (reuse first)

`library/catalog.json` lists every reusable element. Each entry records: id, kind, how it's built (code module or file), licence, tags, and which episodes have used it.
- **Worlds:** ocean (FFT, with sea state), night sky and moon, dawn sky, island (coastline from real geodata), reef.
- **Vehicles:** yacht.
- **Props:** radio, beacon, phone, helm, switch panel, lamp, trash bag.
- **Characters:** hero, with face and eye engine.
- **Systems:**
  - acting rig (stances, poses, verbs)
  - face engine (emotions, gaze, blinks, visemes)
  - camera presets
  - lighting presets
  - grade presets
  - caption styles
  - sound beds

New elements built or sourced for an episode are added to the catalog, so the library grows with every episode.

**World kits** (`factory/worlds/`) make any idea stageable, not only the yacht/island world. A kit is a set as data (`kit.schema.json`): terrain + sky/time/weather + scatter layers of catalog assets + hero set pieces + named marks (stand/sit/interaction points) + camera-safe zones + a default lighting preset + ambience beds. `layout.py` turns (kit, seed) into a deterministic plan that the director (marks, camera checks) and `cloud/blender/set_assembly.py` (the Blender build) share. The librarian maps a breakdown location to a kit (REUSE `kit:<id>`) or drafts a new kit from the library (BUILD with a `kit_proposal`); a shot with `"set": "<kit>"` is staged on the kit's marks and rendered through the set assembler. Starter kits: `jungle_clearing`, `desert_canyon`, `snow_mountain_ridge`, `abandoned_city_street` (+ `sea_yacht`, the legacy path). `python -m factory.worlds list|validate|layout|propose`.

## Sourcing (in priority order)

1. **Internal library:** reuse.
2. **Code-built:** procedural in bpy (props, ships, terrain, water, sky).
3. **CC0 libraries with APIs:** Poly Haven (HDRIs, textures, models), ambientCG (materials), MakeHuman/MPFB (humans, eyes, face units, visemes, clothes), Quaternius and Kenney (stylised props).
4. **Licensed libraries:** Sketchfab (CC-BY downloads, needs a token), BlenderKit (key), Fab/Megascans (account).
5. **Sound:** ElevenLabs sound-effects API, Freesound (token), Sonniss GDC bundles (CC0-like licence), plus the music library.

Every sourced file stores its provider, URL, licence, author and sha256 in `manifest.json`. Attribution lines are generated for licences that require them.

## Recipes (the taste, as rules)

- **`recipes/PIXAR_RECIPE.md`:** pipeline gates, story spine, shot language, lighting, colour script, performance, eyes.
- **`recipes/ENGAGEMENT_RECIPE.md`:** hook, re-hooks, pacing, captions, sound density, loudness.
- **`styles/<style>.json`:** the house look as data: palette, tone mapping, lens set, light ratios, outline or none, caption typography, music palette.

The first style is `pixar_night_survival`.

Each recipe ends in an automatable checklist. Stages 1, 4 and 9 validate against these checklists, so taste becomes a test that can fail.

## Formats: shorts and long-form docuseries

The same stages run at two scales, set by `format` in `story.json`.

| | Short | Docuseries episode |
|---|---|---|
| Length | 60–120 s | 15–25 min |
| Story unit | 1 story spine, 25–35 shots | 5–8 **chapters**, each with its own spine (hook, escalation, payoff), 150–400 shots |
| Structure | hook → steps → payoff → loop | cold open (≤90 s) → title → chapters with act breaks and a re-hook every 2–3 min → climax → resolution → tease of the next episode |
| Narration | about 3 words/s, energetic | about 2.4–2.7 words/s, documentary register, with interview-style beats and archival-style reconstructions |
| Pacing | average shot 1.8–2.6 s | varies by chapter: 3–6 s, with long establishing and suspense holds |
| Output | 1080×1920 | 3840×2160 / 1920×1080 master, plus vertical cut-downs |

### Deriving shorts from long-form

The director plans the shorts while directing the long-form, not afterwards:

1. Every chapter is written so that one self-contained beat can stand alone, with a setup, a turn and a payoff inside 45–90 s. Each such candidate is tagged `short_candidate` with in/out points and a hook line.
2. Those beats are **staged for both frames**. The hero and key action stay inside a centre band that holds in 16:9 and 9:16, and the virtual camera records a second 9:16 camera alongside the 16:9 one, so verticals are re-framed rather than cropped.
3. At finish, each candidate becomes its own short:
   - a new 1–3 s cold-open hook, either re-cut from the climax of that beat or a VO pickup line generated with the same voice
   - vertical captions in the short style
   - a tighter re-cut, using the shorts pacing rules from the engagement recipe
   - an end that loops back to the start
4. QC runs the shorts checklist on every derived short, and the long-form checklist on the master.

This multiplies the output: one 20-minute episode yields about 8–15 shorts, all from the same renders.

### Production scale for long-form

- Library reuse is what makes 20 minutes affordable. Sets, characters and props are built once per series, and episodes mostly recombine them.
- Rendering splits by chapter and shot across GPU workers.
- EEVEE handles previs and suitable final shots; Cycles handles hero shots. The director picks the engine per shot from the shot's needs (volumetrics, glass, hair close-ups).
- Continuity is tracked per series in `series.json`: characters, wardrobe, injuries, time of day, props in hand, and the location state of everything the story changes.

## Scale

- One episode is a DAG of jobs: develop → (VO ∥ breakdown → library) → direct → previs → render (N shot jobs) → finish → QC.
- A queue (SQS, or Temporal on AWS) runs many DAGs in parallel. Render jobs fan out to spot GPU workers, each running the same Blender image with the library baked in.
- For 10 ideas at once: stages 1–6 are cheap (API plus CPU), and stage 7 dominates. Expect about 33 shots × about 75 frames per episode, rendered in parallel across GPUs.
