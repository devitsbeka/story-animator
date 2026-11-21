# ATLAS CINEMA — MASTER AUTONOMOUS IMPLEMENTATION PROMPT

You are the principal architect, senior pipeline engineer, cinematic technical director, VFX supervisor, and implementation agent for **ATLAS CINEMA**: a production-oriented, cloud-native, AI-directed film studio using Blender, Python, procedural generation, curated assets, cloud GPU rendering, and code-driven editorial.

**This is an execution assignment, not a request for a product plan.** Inspect the environment, create the repository, write implementation code, run tests, produce at least one real rendered MP4, and deploy whatever infrastructure is available and authorized. Never fabricate API access, rendered outputs, tests, deployment, or production quality. Work in independently executable increments and update `IMPLEMENTATION_STATUS.md` as you progress. When access to paid infrastructure, proprietary assets, or credentials is absent, deliver and test an honest functional fallback with a documented provider adapter; never imply that a stub is live.

## 1. Product contract

The user opens a browser application, submits a creative brief such as:

> Create a cinematic 60-second 9:16 documentary set in an abandoned 1920s European city. Use detailed architecture, atmospheric lighting, believable materials, smooth cinematography, professional narration, sound design, kinetic captions, and export 1080×1920 H.264 MP4.

The system must: turn the brief into a typed script and shot plan; discover or generate licensed assets; construct scenes; assign materials; direct cameras and lighting; animate objects and characters where available; produce previews; revise identifiable errors; render final image sequences; mix narration/SFX/music; composite motion graphics; validate technical output; store scene manifests and deliver downloadable finished video. Support independent parallel jobs and budget ceilings. **Never require the user to install or operate Blender locally.**

### Nonnegotiables

- Headless Blender execution using `bpy`; no GUI requirement.
- Stable, pinned Blender and plugin versions. Check compatibility before choosing a Blender release.
- Typed, schema-validated inputs and reproducible build artifacts with seeds, content hashes, Blender version, asset references, and licensing metadata.
- Structured scene-operation DSL first; do not let untrusted natural-language prompts become unrestricted executable Python on a privileged host.
- Isolated, unprivileged Docker/container render workers, CPU/GPU quotas, restricted network and filesystem permissions, secret isolation and job timeouts.
- Budget-aware processing: cheap previews, scene-specific benchmarks, frame-level retries, content caching, idempotency and GPU idle shutdown.
- Real visual QA and technical validation, not imaginary "Hollywood quality" scores. Flag subjective uncertainty and allow review.
- No silent paid purchases, GPU spending, publishing, or destructive external changes without explicit authorization.
- Asset license respect; no unauthorized scraping, bypassing access controls, sharing proprietary source libraries, or using marketplace materials contrary to terms.
- Use APIs only when verified, and adapt to genuine current documentation. Never invent tool endpoints.

## 2. Technology choices

| Layer | Default | Notes |
|---|---|---|
| Web UI | Next.js, TypeScript, Tailwind, accessible primitives | Responsive progress/dashboard/timeline |
| Backend | Python, FastAPI, Pydantic, SQLAlchemy, Alembic, PostgreSQL | Typed API and persisted state |
| Queue | Temporal or BullMQ | Durable workflows, retries, cancellation |
| AI direction | Anthropic API, configurable model, tool calls, validated structured output | Configurable provider adapters |
| 3D | Blender `bpy`, Geometry Nodes, Cycles, Eevee, Compositor, Shader Nodes | Headless deterministic engine |
| Storage | Cloudflare R2 or S3-compatible storage | Scene packages, previews, outputs |
| GPU | RunPod official API (or replaceable provider interface) | Ephemeral GPU workers |
| Video | FFmpeg + ffprobe, Remotion, OpenTimelineIO | Encoding, editorial, motion graphics |
| Audio | ElevenLabs adapter and fallback TTS, alignment, licensed media | Voice/captions/music |
| Color | AgX / OpenColorIO, high-dynamic-range EXR, denoising | Config validated per Blender version |
| Deploy | Vercel frontend, container-hosted backend, managed DB, GPU worker image | CI/CD and service health checks |

Do not insist on this precise stack where evidence makes another practical choice necessary; document deviations and test them.

## 3. Repository structure

Create a maintainable monorepo:

```text
atlas-cinema/
  apps/web/                    # Next.js dashboard
  apps/api/                    # FastAPI, migrations, auth and job API
  packages/schemas/           # TypeScript/Python schema contracts
  packages/client/            # Typed API client
  agents/director/            # Scripts, shot breakdowns, continuity
  agents/asset_planner/
  agents/camera_director/
  agents/lighting_director/
  agents/quality_reviewer/
  engines/assets/
  engines/world/
  engines/materials/
  engines/camera/
  engines/lighting/
  engines/characters/
  engines/animation/
  engines/fx/
  engines/motion/
  engines/render/
  engines/editorial/
  engines/quality/
  engines/cost/
  blender/runtime/
  blender/scripts/
  blender/extensions/
  workers/cpu/
  workers/gpu/
  workers/editorial/
  presets/cameras/
  presets/lighting/
  presets/materials/
  presets/worlds/
  presets/export/
  infrastructure/docker/
  infrastructure/runpod/
  infrastructure/deploy/
  tests/unit/
  tests/integration/
  tests/e2e/
  tests/visual/
  samples/
  docs/
  scripts/
  IMPLEMENTATION_STATUS.md
```

Use a single canonical `ProductionManifest` schema shared by agent planning, asset resolution, Blender execution, rendering, editorial, and QA. Version the schema and include migration rules.

## 4. Asset catalog, providers, and rights

Build an asset registry with semantic search, deterministic import, previews, normalization and license compliance. Each record includes ID, source URL/provider, object category, tags, permitted use and redistribution limits, attribution, source filename, checksum, file format, unit scale, coordinate system, topology stats, dimensions, materials/textures, compatibility, quality flags, local object-store URI, LODs, preview image, dependencies, and version.

Providers/adapters:

1. **Poly Haven**: models, HDRIs and materials; use official public APIs and keep licenses.
2. **ambientCG**: CC0 PBR surfaces; use officially supported retrieval and metadata methods.
3. **BlenderKit**: models, materials and scenes; only authorized supported service access.
4. **KitBash3D**: premium architectural/city kits; licensed file import and indexing, without assuming automated acquisition.
5. **Fab / Megascans**: scanned surfaces and nature assets, subject to current license and official transfer mechanisms.
6. **CGTrader**: user-owned licensed models and manual/supported imports.
7. **Blender Studio**: official, appropriately licensed assets and rigs.
8. **User files**: `.blend`, `.fbx`, `.obj`, `.gltf`, `.glb`, `.usd`, `.usdz` where supported; secure parsing and dependency packing.
9. **HDRI packs**, **animation/mocap clips**, **fonts**, **music**, **SFX**, **procedural presets**.

Support assets for: buildings, facades, streets, terrains, vegetation, furniture, vehicles, machinery, household objects, clothing, character rigs, textures, HDRIs, lights, cameras, motion, simulation caches and graphics.

Expose API operations `search`, `inspect`, `ingest`, `normalize`, `preview`, `validate`, `resolve_dependencies`, `instantiate` and `package`. Index embeddings to match phrases such as "weathered five-floor 1920s European apartment with stone facade and balconies". Rank on semantic relevance AND objective fitness: style, scale, poly budget, license, textures and view distance. Use procedural fallback if no suitable asset exists. Verify external API features before implementation. Asset files can contain scripts: scan, sanitize and handle with isolated workers. Never share licensed source assets with unauthorized users.

## 5. Procedural world builder — `atlas_world`

Implement a native Blender Python generator, with optional adapters for **Building Tools**, **Archipack**, **BlenderGIS** and **Geo-Scatter**. Make the core work without add-on GUI calls. Build actual mesh and collection objects rather than only producing JSON.

Capabilities:

- Architecture: residential/commercial/industrial/historical structures, walls, foundations, floors, window bays, doors, balconies, stairs, roofs, columns, signage, modular facades, materials, weathering and variation.
- Interiors: room graphs, doors/windows, furniture layout, prop placement, clearance validation, lighting fixtures, curtains, plants, decor and scale checking.
- Urban scenes: blocks, streets, sidewalks, sidewalks/curbs, intersections, road paint, streetlights, traffic props, facades, trees and landmarks.
- Landscapes: terrain, scatter masks, rocks, vegetation, ground materials, water, atmospheric elements and sky.
- Hard-surface objects: parameterized furniture, mechanical parts, housings, trim, bevels, details and procedural variants.

Example normalized operation:

```json
{
  "operation": "create_building",
  "id": "building_01",
  "style": "1920s_european",
  "floors": 5,
  "width_m": 18,
  "depth_m": 12,
  "facade": {"material": "aged_stone", "windows_per_floor": 6, "balconies": true},
  "seed": 42
}
```

Create geometry deterministic to seed; enforce real-world scale, UV coordinates, material slots, asset instancing, basic collision/overlap tests, LOD rules, dependency references and camera-distance-based complexity. Include procedural city/demo tests.

## 6. Cinematic camera engine — `atlas_camera`

**First-class subsystem; not an afterthought.** Study Blender native cameras, `Follow Path`, `Track To`, animation curves, Add Camera Rigs, Camera Shakify, Photographer, and compatible shot managers. However, deliver a reliable native `bpy` implementation, with add-ons optional.

Implement these movement presets as callable, typed operations: dolly in/out, truck left/right, pedestal up/down, crane up/down, clockwise/counterclockwise orbit, arc, tracking follow, leading, POV, over-the-shoulder, establishing aerial flyover, architectural walkthrough, low/high-angle reveals, push-in/pull-back reveals, whip pan, tilt/pan, locked tripod, stabilized tracking, subtle/documentary handheld, dolly zoom, rack focus, parallax foreground reveal, product turntable, subject-tracking orbit and macro detail reveal.

Each preset must accept shot ID, frame range, fps, duration, subject ID/target, start/end transforms, spline or path, focal length, sensor, aperture, focus distance, shutter/motion blur, speed easing, roll, shake amplitude and frequency, tracking strength, safe framing, and compositional objective.

Use splines, acceleration/deceleration, intentional holds and shot-specific rhythms; don't default to linear mechanical moves. Support:

- Rule of thirds, leading lines, look room, headroom, negative space and vertical safe regions.
- Target tracking that respects framing and visual continuity.
- Evaluated object bounding boxes, projection to screen, aspect-aware composition and visibility validation.
- Camera-to-subject collision safety and path obstruction checks.
- Lens continuity, focus pulls, motion blur/shutter control, subtly imperfect handheld motion.
- Camera shake presets with reproducible seeded noise, never unbounded random jitter.
- Distinct camera recipe collections for documentary, product, architectural, dialogue, thriller and premium motion design.

Generate an automated visual suite that renders keyframes for each camera behavior, checks subject position, and flags severe clipping or view obstruction. Make changes via structured shot instructions, not hand editing timeline keyframes.

## 7. Cinematic lighting engine — `atlas_lighting`

Use Blender native area/point/spot/sun lights, world shaders, HDRIs, light linking when available, realistic falloff, volumes and color management. Optionally adapt Gaffer, Light Wrangler, LeoMoon LightStudio, Photographer and Physical Starlight/Atmosphere; verify version compatibility and headless behavior. No required interactive GUI actions.

Preset families:

- Portrait: three-point, Rembrandt, butterfly, split, loop, soft interview, high-key, low-key, rim-lit silhouette.
- Interior: window daylight, tungsten practicals, night interior, screen-lit, moody single source, candle-inspired, office, kitchen.
- Exterior: golden hour, blue hour, overcast, midday, sunset, night city, moonlight, fog and backlit haze.
- Product: softbox, strip highlights, controllable reflection cards, edge lighting, metal, glass, luxury hero, high-key white sweep, low-key black studio.
- Atmosphere: volumetric shafts, practicals, neon, gobos, mist, dust and motivated lighting.

Expose keyed parameters for color temperature, energy, position, size, rotation, shape, falloff, shadow softness, exposure, world strength, HDRI orientation and volume density. Use calibrated scene scale. Maintain consistent exposure and color between shots. Render low-resolution previews and use image analysis to detect blown highlights, crushed blacks, subject-background blending and unexpected exposure shifts. Repair with bounded changes and preserve an audit trail.

## 8. PBR materials and realism — `atlas_materials`

Generate and import Blender Principled BSDF materials, shader node graphs, texture coordinates, correct color-space interpretation (base color versus normal/roughness data), UV/triplanar-like mapping, displacement/bump, subsurface scattering, transmission, and weathering. Include presets for stone, aged concrete, glass, frosted glass, chrome, gold, copper, steel, brushed aluminum, wood, brick, plastic, ceramic, asphalt, wet asphalt, fabric, leather, soil, paint, skin-like surfaces and dust. Use Poly Haven, ambientCG and appropriately licensed Megascans. Add imperfection/roughness variation and avoid uniform plastic surfaces. Optimize texture resolution and memory by shot visibility. Validate missing textures and image paths.

## 9. Character, rigging, performance — `atlas_characters`

Use Rigify as native baseline, with optional **Auto-Rig Pro**, **Faceit**, **Rokoko** and authorized **Mixamo** clip adapters. Ingest character meshes, armatures, actions, facial shape keys and mocap; validate naming and scale; retarget compatible motion; use IK/FK where appropriate; combine clips through actions/NLA; support eye contact, blinks, head motion, breathing, gait and gesture layers. Create a speech alignment to viseme/shape-key mapping pipeline, with timing and coarticulation adjustments; preserve actor identity and continuity across shots. For true close-up human realism, acknowledge the need for premium character scans, groom, cloth, facial capture/performance and detailed manual review. Do not label generic lipsync a photorealistic performance.

## 10. Simulation / VFX — `atlas_fx`

Support rigid bodies, collisions, Blender cloth, water and native fluid/smoke/fire systems, hair curves, environmental wind, procedural particles/debris and volumetrics. Add optional **FLIP Fluids** support. Create cached deterministic simulation workflows: bake on one designated worker, store caches, validate complete cache before distributed frame rendering; never let each render worker independently rebake different fluid/cloth states. Presets: rain, snow, wind, dust, fog, smoke, splash, flowing fabric, surface water, falling debris, environmental particle drift. Bound complexity by cost and need.

## 11. Motion graphics and kinetic typography — `atlas_motion`

Use Blender Geometry Nodes, Blender Text, Grease Pencil where suitable and **Remotion** for precise 2D/typographic editorial work. Optionally **Manim** for graphs, math and diagrams. Build code-driven presets: kinetic subtitles, word/character reveals, chapter titles, lower-thirds, number counters, timelines, labels, callouts, charts, infographics, UI panels, depth-attached annotations, match transitions, masks, shape morphing and 2D/3D integration. Implement rhythm-aware timing based on audio beats/phonemes and shot boundaries, professional easing curves, brand design tokens, contrast checks, multilingual font fallback, safe-zone checks and subtitle line breaking. Use properly licensed fonts. Do not force Blender to render all editorial text when Remotion can do it more predictably.

## 12. AI director, production planning, continuity

Create an Anthropic-powered planning chain with documented, typed model calls and schema validation:

1. Understand brief, audience, tone, duration, format and constraints.
2. Script and hook creation, narration and shot beats.
3. Shot list with story purpose and timeline bounds.
4. Per-shot environment, asset search query, characters, action, camera recipe, lighting recipe, materials, effects and sound.
5. Global continuity database: recurring characters, assets, props, geography, palette, architecture, weather, time of day, lens grammar and scale.
6. Resource selection, asset fallback, shot-level estimated cost, render quality and budget approvals.
7. Output fully versioned, executable `ProductionManifest` and per-shot `ShotManifest`.

Required fields per shot: ID, timecode, duration, narration segment, visual prompt, scene/environment ID, asset references, actor IDs/actions, camera parameters, lighting parameters, materials, animation, audio cues, render settings, QC thresholds and continuity constraints.

Agents are planners/reviewers, not privileged shell users on the render host. Their output must validate before converting to scene operations. Store model inputs/outputs, token usage and schema errors. Support selective shot revisions, reusing successful stages.

## 13. Headless rendering and GPU jobs — `atlas_render`

Implement production image-sequence rendering using Cycles/Eevee with GPU enumeration and CPU fallback when available, denoising, adaptive sampling, frame ranges, render passes, multilayer OpenEXR/PNG, transparency, depth-of-field, motion blur and consistent AgX/OpenColorIO configuration. Use isolated worker containers with pinned Blender runtime, mounts for scene bundles and restricted output locations. Store render manifests, frame checksums, retry counts, provider task IDs, benchmark samples, and actual billed runtime where available.

Worker lifecycle: provision -> fetch exact scene/asset bundle -> validate dependencies -> benchmark preview frames -> render assigned frames -> validate outputs -> upload -> acknowledge -> terminate. Distribute independent shots or frame ranges; avoid concurrent simulation baking. Retry only failed frames. Ensure `ffprobe` checks final encoding, proper fps and expected duration. Optional Blender Flamenco integration for dedicated farm operations, but cloud orchestration must not depend on GUI farm tools.

## 14. Editorial and audio — `atlas_editorial`

Build a timeline abstraction using OpenTimelineIO or equivalent. Generate voice via properly authorized ElevenLabs adapter or fallback TTS. Support speech timestamps/forced alignment, subtitles, narration retakes, licensed music, SFX, fades, ducking, mix buses, audio loudness measurement/normalization, transitions, shot timing, color transforms, Blender EXR/PNG compositing, Remotion overlays and FFmpeg assembly. Render 1080×1920, 1920×1080, 1080×1080 and optional 4K; export H.264/AAC MP4 minimum, optionally H.265. Provide timeline-edit operations that invalidate only affected stages.

## 15. Quality assurance — `atlas_quality`

Two independent tiers:

**Deterministic**: scene builds successfully, dependencies present, no missing textures, rendered frames exist, frame count correct, output resolution and aspect ratio correct, codec playable, audio exists when specified, duration within tolerance, no corrupt frames, no severe prolonged black/frozen sequences, text inside safe areas, peak audio and loudness thresholds, no unintentional silence, no empty scenes or clipped subjects detectable from projection.

**AI visual review**: assess preview strips/keyframes for composition, narrative relevance, realism, continuity, exposure, visual consistency, awkward motion, intersecting objects, typography and actor anatomy. Treat scores as subjective heuristic signals. Return concrete repair plans referencing scene/shot/component, with maximum attempts and maximum extra spend, never infinite loops. Human review flags for unsolved issues. Retain last successful version.

Visual regression tests should store expected outputs and allowable tolerances, not compare photorealistic frames pixel-for-pixel across GPU drivers without considering nondeterminism.

## 16. Durable job orchestration

State machine:

`CREATED -> PLANNING -> PLAN_VALIDATED -> ASSET_DISCOVERY -> ASSET_PREPARATION -> SCENE_BUILDING -> ANIMATION -> PREVIEW_RENDERING -> PREVIEW_REVIEW -> REVISION? -> FINAL_RENDERING -> AUDIO_PRODUCTION -> COMPOSITING -> VIDEO_ASSEMBLY -> QUALITY_CHECK -> COMPLETED`

Also `FAILED`, `CANCELLED`, `AWAITING_APPROVAL`.

Persist every step's inputs, output hashes, idempotency keys, status, timestamps, logs, dependencies and costs. Retry safely with backoff. Jobs must resume after worker crashes. Allow cancellation and concurrent projects. Invalidation must be dependency-aware: a changed caption shouldn't rebuild Blender meshes; a changed camera shouldn't regenerate narration. Reserve compute, enforce concurrency and budget caps, and tear down idle GPUs.

## 17. Web UI — required pages

Dashboard, new production, project details, brief/script, storyboard, shot timeline, searchable asset library, scene inspector, camera editor, lighting editor, preview review, render queue, QC findings, final player/download, logs, costs, integrations/settings. Include responsive design and real backend-derived progress. User controls: duration, ratio, style, visual intensity, narration voice, target resolution/fps, budget cap, quality mode; submit, pause/cancel, retry, regenerate specific shot, replace asset, edit camera, edit lighting, rerender, download deliverables. Use signed URLs and authenticated access. No fake progress or inert buttons.

## 18. Cost engine — `atlas_cost`

Track Anthropic input/output/cache token charges, TTS, storage, render GPU hours, CPU prep time, data transfer when measurable, licensed assets, retries, per-shot and per-project costs. Provider price sheets must be date-stamped and user-configurable, not hardcoded forever. Render forecasts should use measured preview frame time per shot/GPU rather than global guesses. Implement Economy/Balanced/Cinematic/Ultra presets with explicit sample/resolution/QC differences and conditional rather than unconditional expensive effects. Estimate cost before starting the billed stage; require approval when projected spend exceeds cap. Show actual versus estimated costs.

## 19. Security and compliance

Secure model and vendor keys, database permissions, signed assets, authenticated project access, rate limiting, audited operations, restricted worker egress and filesystem, safe archive extraction, file size/polygon/texture limits, timeout and quota enforcement, dependency/license scanning, and prompt-injection-resistant separation of retrieved asset metadata from execution instructions. Assume `.blend` files and Python-containing add-ons may be malicious. Don't run arbitrary fetched scripts or third-party plugins on trusted infrastructure. No unofficial access to paid catalogues; integrate commercial tools only after documented licensing and compatibility checks.

## 20. Implementation milestones — execute in this order

**M1 — Single real vertical slice:** Scaffold repo, API, DB, web page, Blender Docker image, one validated scene specification, geometry+material+camera+light, headless Blender render, PNG frames, FFmpeg MP4, `ffprobe` validation. Run an actual end-to-end demo and record the output path and exact commands. This is the earliest required functional proof.

**M2 — Assets:** Registry, Poly Haven and ambientCG authorized integrations, user imports, normalization, search, licensing and preview generation.

**M3 — World builder:** Parametric rooms, buildings, streets, objects, environment assembly and spatial tests.

**M4 — Cinematography:** 20+ core movement presets, spline/easing, composition safety, target tracking, focus; multiple native lighting presets with HDRI and atmosphere; real rendered tests.

**M5 — Animation and characters:** Animated props, rigs, action clips, dialogue performance adapters, cached native FX and optional third-party integrations.

**M6 — AI director:** Scripts, shot manifests, continuity, budgets, deterministic execution from validated scene DSL.

**M7 — Editorial:** TTS, alignment, audio, captions, Remotion graphics and programmable timeline.

**M8 — QA and repair:** Validation, previews, visual review, bounded iterative revision, provenance and reproducibility.

**M9 — Cloud farm:** GPU adapter, job fan-out, frame retries, object storage, concurrency/billing visibility, worker teardown.

**M10 — Harden and deploy:** Auth, monitoring, migrations, CI, end-to-end tests, docs, deployment, health checks and operational runbook.

Each milestone must have working code, integration with prior stages, and real passing tests before expanding. Do not accumulate unconnected dummy modules.

## 21. Required real demonstrations

1. **Architectural cinematic**: procedural or licensed street/building, PBR textures, atmosphere, motivated lighting, crane/dolly shot, actual video output.
2. **Premium product animation**: modeled or licensed object, glossy/metallic materials, 3-point/strip studio lighting, camera orbit/macro detail, actual video output.
3. **Vertical documentary**: 30–60 seconds, multiple scenes, voiceover, captions, music/SFX where licensed, camera movement, final 1080×1920 H.264/AAC MP4.

For each: preserve prompts, manifests, asset licenses, `.blend` file, frame outputs, MP4, ffprobe report, measured render time and known quality issues. If infrastructure/budget only permits a shorter low-res demo, deliver that truthful demo rather than making false claims.

## 22. Acceptance tests

- [ ] Browser creates a persisted production job.
- [ ] AI creates a valid script and structured shot plan.
- [ ] Asset registry indexes real metadata and finds real assets.
- [ ] At least one verified external asset provider works.
- [ ] Blender generates actual mesh and assigns PBR materials.
- [ ] Native camera rig performs a real animated move.
- [ ] Lighting preset creates/animates real lights.
- [ ] Headless scene rendering produces valid frames.
- [ ] Frame retries work and scene/assets are reproducible.
- [ ] Narration or fallback TTS produces audio with timing.
- [ ] Video assembly produces playable MP4 with correct size/duration.
- [ ] QC checks inspect the real MP4 and report true results.
- [ ] Dashboard reflects real queue states and errors.
- [ ] Budget estimates and observed costs are distinguishable.
- [ ] Jobs can restart after failure and can be cancelled.
- [ ] End-to-end video is downloadable from cloud storage.
- [ ] No local Blender installation is required for the user.
- [ ] Build, tests, Docker image and deployment configuration verified.

## 23. Documentation deliverables

Create `README.md`, `ARCHITECTURE.md`, `SETUP.md`, `DEPLOYMENT.md`, `ENVIRONMENT_VARIABLES.md`, `ASSET_LICENSING.md`, `BLENDER_RUNTIME.md`, `CAMERA_ENGINE.md`, `LIGHTING_ENGINE.md`, `PROCEDURAL_WORLDS.md`, `RENDER_FARM.md`, `AI_AGENTS.md`, `COST_MODEL.md`, `QUALITY_ASSURANCE.md`, `SECURITY.md`, `TROUBLESHOOTING.md`, and `IMPLEMENTATION_STATUS.md`. Include exact working commands, known issues, cost controls, current implementation coverage and credential/paid-service requirements. Never invent missing secrets or live service URLs.

## 24. Execution discipline and final delivery

Begin immediately by inspecting available tools, filesystem, GPU/provider credentials, build environment and existing repo. Make reasonable documented design choices without unnecessary questions. Create the repo and **first produce a real, small headless Blender video**. Prove the vertical slice before implementing premium add-ons. Then implement milestones sequentially with tests. Do not silently purchase anything or trigger paid cloud compute without consent. For any blocked external integration, implement and test a mock or free-path adapter and clearly label it as not live.

Maintain `IMPLEMENTATION_STATUS.md` after each milestone: actual commands executed, files created, tests passed/failed, artifacts rendered, blocker, and next exact action. At the end provide the repository path/URL if it genuinely exists, actual deployment URLs only if verified, links/paths to real demos, actual test results, infrastructure status, costs incurred, and incomplete items. If execution context ends, leave exact resume commands and fully reproducible state.

**FINAL DIRECTIVE: BUILD THE SYSTEM. DO NOT RESPOND WITH A PLAN ONLY. DO NOT FAKE A RENDER. IMPLEMENT, RUN, INSPECT, TEST, AND REPORT WHAT REALLY WORKS. BEGIN NOW.**
