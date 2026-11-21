# ATLAS CINEMA — AI Coding Agent Implementation Kit

**Purpose:** Deliver a functioning, fully cloud-based, headless Blender + AI cinematic production system. This bundle is a **build specification plus runnable bootstrap examples**, not a completed application or a collection of paid binary assets.

## Send to your coding agent

1. Upload the entire ZIP or extract this folder into a new repository.
2. Give the agent this exact instruction:

> Read `START_HERE.md`, `AGENTS.md`, `01_PROMPTS/MASTER_IMPLEMENTATION_PROMPT.md`, and every file in `02_SPECS/`, `03_CATALOGS/`, `04_OPERATIONS/`, and `05_ACCEPTANCE/`. Execute `01_PROMPTS/EXECUTION_DIRECTIVE.md` in phases. Use manifests as the source of truth, verify provider compatibility and licenses before setup, and produce a real end-to-end rendered MP4. Do not stop at a plan or falsely report a deployed service. Maintain `IMPLEMENTATION_STATUS.md`.

3. Provide your agent credentials through its **secret manager** or server environment, never by pasting real keys into these files.
4. Give explicit permission before paid purchases, GPU deployment spend, publishing, or destructive operations.

## Package map

- `AGENTS.md`: always-on agent working rules and instructions.
- `01_PROMPTS/`: master build order and specialist skill prompts.
- `02_SPECS/`: architecture, data model, cameras, lights, procedural worlds, humans, motion graphics, rendering, audio, orchestration, visual QA, and security.
- `03_CATALOGS/`: machine-readable asset, plugin, provider and cinematic preset manifests; no copyrighted commercial binaries bundled.
- `04_OPERATIONS/`: credentials, installation, cloud rollout, acquisition, cost/quality gates, compatibility validation.
- `05_ACCEPTANCE/`: objective definition of done, demo shots, test matrix.
- `06_BOOTSTRAP/`: actual minimal Blender background-mode render scripts, build smoke tests, and sample shot brief.
- `REFERENCES.md`: official links for primary technologies and APIs; verify freshness.

## Reality check

No stack of plugins guarantees Hollywood quality, and no single coding-agent run guarantees the entire film pipeline is finished. Require real previews, human artistic inspection when needed, asset validation, physically plausible rendering, measurable QC, and iterative improvements. Treat paid plugin headless support as **unverified until demonstrated on the pinned Blender build**.

## Quick smoke test (if Blender and ffmpeg available in agent environment)

```bash
blender -b -t 2 --python 06_BOOTSTRAP/smoke_scene.py -- --output /tmp/atlas-smoke --frames 48 --res 480
python3 06_BOOTSTRAP/verify_render.py /tmp/atlas-smoke --frames 48
ffmpeg -y -framerate 24 -i /tmp/atlas-smoke/frame_%04d.png -c:v libx264 -pix_fmt yuv420p /tmp/atlas-smoke.mp4
ffprobe -v error -show_entries format=duration -of json /tmp/atlas-smoke.mp4
```

Cloud deployment and production integrations must be implemented separately. The bootstrap demo is deliberately a small *real rendered animation*, not a pretend Hollywood deliverable.
