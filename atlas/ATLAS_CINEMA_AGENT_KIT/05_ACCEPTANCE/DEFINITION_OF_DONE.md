# Production-oriented definition of done

## Milestone A — Working local/cloud VM vertical slice

- [ ] Runnable repo and pinned Python/Node/Blender versions.
- [ ] Headless Blender renders a real animated sequence, not static frame repeated.
- [ ] Scene camera and lights animated by `bpy`, not hand-clicked.
- [ ] FFmpeg assembles actual 9:16 H.264 MP4; ffprobe verifies it.
- [ ] Real render logs and output checksums saved.

## Milestone B — End-to-end app

- [ ] User creates job in real web UI.
- [ ] Typed AI storyboard generated and validated; sample fallback clearly labeled.
- [ ] Asset source API ingestion works and license metadata saved.
- [ ] Procedural architecture, selected assets and materials appear in scene.
- [ ] Render queue handles shot retry/cancel, status, costs and budget ceilings.
- [ ] Narration, captions, SFX/music track available from licensed or generated source.
- [ ] QC checks actual images and MP4 and stores findings.
- [ ] Signed file download works.

## Milestone C — Cloud production

- [ ] Actual API/DB/worker deployments verified and health checks recorded.
- [ ] Cloud GPU render actually executed, timing and billed cost recorded.
- [ ] Idle GPU shutdown, retry after failure and per-job budget enforced.
- [ ] Asset warehouse can use selected free and owner-imported commercial assets.
- [ ] 3 sample videos pass objective tests and human quality review.

**Blockers and honest status:** Unlicensed plugin? mark blocked or native fallback. No access to RunPod? local CPU path verified but cloud GPU unverified. No footage? do not claim full film. No TTS? synthetic placeholder soundtrack must be labeled. No live deployment? list reproducible deployment steps, not invented URLs.
