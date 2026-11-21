# Data contracts and shot schema

Implement exact typed models, JSON schemas, OpenAPI definitions and DB migrations for these entities:

- `Project`: id, owner, brief, target duration, fps, aspect ratio, style bible, spend ceiling, state, created_at.
- `Sequence`: ordered shots, narrative arc, tempo, palette, continuity bible.
- `Shot`: uuid, immutable spec_version, purpose, duration_frames, start/end, environment_id, asset_refs[], camera_spec, lighting_spec, animation_spec, audio_spec, render_spec, QA policy.
- `Asset`: source, source_id, URI, checksum, license type, evidence URL, entitlement owner, derivative flags, semantic tags, model units, geometry metrics, textures, provenance, version.
- `Job`: state, retries, worker type, dependencies, max cost, observed cost, deadline, outputs, error envelope.
- `Render`: Blender version, worker image digest, scene hash, scene spec ID, frame range, output URIs, pass types, samples, denoiser, execution times.
- `Review`: reviewer type, objective metrics, sampled image IDs, findings, proposed modifications, confidence, status.

## Shot JSON example

```json
{
  "shot_id": "s01",
  "duration_frames": 144,
  "fps": 24,
  "narrative_purpose": "Reveal a quiet 1920s street",
  "environment": {"type":"procedural_street", "period":"1920s", "seed":17},
  "assets": [{"id":"cc0-lamp-001", "usage":"set_dressing"}],
  "camera": {"preset":"dolly_in", "lens_mm":35, "start_m":[0,-12,2], "end_m":[0,-7,2], "target_m":[0,0,1.8], "ease":"quintic_smooth"},
  "lighting": {"preset":"overcast_soft", "exposure_ev":0},
  "render": {"engine":"cycles", "resolution":[1080,1920], "samples":128},
  "audio": {"narration_segment_id":"v01", "sfx_cues":["wind_soft"]}
}
```

Validate numeric ranges, asset references, allowed presets, permissions, frame counts, and exposure of frontend-entered text. Use a schema version and migration policy; reject unknown dangerous operations. Do not accept expressions as substitute for literal typed values in the scene DSL.
