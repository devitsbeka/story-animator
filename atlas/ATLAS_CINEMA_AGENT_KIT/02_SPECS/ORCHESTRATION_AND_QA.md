# Job orchestration and realistic quality controls

States: created → planning → plan_validated → asset_search → preflight → scene_build → animation → preview_render → preview_review → revision (bounded) → final_render → audio → editorial → qc → completed | failed | cancelled. Persist events and idempotency keys. Branch-per-shot DAG with caches and dependency hashes. Handle worker deaths, reruns, user cancellations and resumability.

## Objective QC

Frame count, codec, aspect, resolution, duration, stream metadata, missing texture warnings, missing assets, render error log, black frames, frozen content, audio peaks and clipping, unexpected silence, subtitle safety, corrupt images, excessive motion jitter, wrong timebase. Maintain artifact SHA256 and manifest.

## Subjective QC

Use sampled previews and short clips with visual model for composition, object scale, visible intersections, photorealism issues, light motivation, skin/eyes, typography, color continuity and pacing. Return localized correction suggestions; do not fake a perfect score. Human review for critical high-value outputs.

## Bounded revisions

Max 2–3 auto revisions by default; select minimal repair (camera/light/material/asset/shot timing) and avoid invalidating unaffected shots. Keep diff, prior frames and reason for chosen solution. Exit when cost threshold reached. The system must not enter an indefinite render loop.
