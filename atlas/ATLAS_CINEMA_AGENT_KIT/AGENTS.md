# Rules for every autonomous coding agent

**Mission:** Build a production-capable web application, headless Blender worker pipeline, asset warehouse, creative agents, render orchestration, editorial, and cost-controlled QC. The owner does not install Blender locally.

Read `01_PROMPTS/MASTER_IMPLEMENTATION_PROMPT.md` plus all specs and manifests before architecture decisions. Start with working vertical slices, not dozens of incomplete components. Implement, test, record evidence and continue sequentially. Complete blocked-independent work rather than giving up.

## Non-negotiable gates

- Real implementation and tests only; never hallucinate success, URLs, credentials, plugin compatibility, GPU benchmarks, purchased assets, or QA scores.
- Source of truth for external dependencies is `03_CATALOGS/plugins.yaml` and `03_CATALOGS/asset_sources.yaml`; verify upstream docs and current versions before use.
- `REQUIRED` means architectural capability required, **not** commercial plugin mandatory. Native Blender `bpy` fallback must exist for camera, lighting, modeling and rendering.
- Do **not** execute untrusted model-authored code or untrusted `.blend` startup scripts on privileged application servers. Use structured JSON DSL -> validated command interpreter in isolated workers.
- Never use undocumented private marketplace endpoints, scrape protected asset sites, bypass purchasing, share paid asset binaries, or commit secrets.
- No silent paid spend, purchases, production publishing, destructive actions, or uncontrolled GPU scaling.
- Persist each scene's source manifest, source/license, hash, version, frame ranges, required assets, quality findings and estimated/actual cost.
- Check video content and visual quality by examining actual frames, not just trusting successful process exit.
- Create `IMPLEMENTATION_STATUS.md` with dates, actual command output, test results, blockers, tested environments and next resume command. Keep it accurate.

## Build order

1. Read instructions/prepare repo; inspect execution environment and credentials.
2. Run the simple Blender smoke render; verify generated files and MP4.
3. Implement API + DB + storage + queue + web UI connected to real jobs.
4. Implement source adapters for Poly Haven and ambientCG, normalize files, store license lineage, index metadata; add premium-manual-import path.
5. Implement Blender scene DSL, world, materials, cameras, lights, animation, render worker.
6. Add short-form editorial, captions, TTS, sound mixing, render QA and cost controls.
7. Add enhanced characters, physics, procedural motion, commercial adapters one at a time after compatibility tests.
8. Deploy verified cloud worker and frontend, perform 3 end-to-end demonstrations, document operational recovery.

## Definition of honesty

Write `implemented`, `integration verified`, `untested`, `blocked: needs credential`, `blocked: needs license`, or `not implemented`. Never substitute one for another.
