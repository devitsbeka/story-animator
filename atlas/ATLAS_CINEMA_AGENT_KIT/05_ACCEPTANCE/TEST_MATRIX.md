# Test matrix

| Area | Mandatory test | Evidence |
|---|---|---|
| Blender | headless native render with changing pixels | frame images and hashes |
| Asset | Poly Haven/ambientCG auth-free metadata retrieval | parsed entries, source docs, rate-limit compliance |
| Rights | commercial source missing entitlement | import rejected |
| Geometry | seeded building created with expected floors/wall spacing | mesh stats and preview |
| Camera | path smooth and subject visible at key frames | keyframe sample report, contact sheet |
| Lighting | presets create real lights, meaningful visible contrast | before/after renders |
| Audio | voice track is valid and synchronized | waveform + timing manifest |
| Editorial | export has correct dimensions, timebase and codecs | ffprobe report |
| Job queue | intentional worker crash and resume | event log, no duplicate billing |
| Cost | job exceeding configured ceiling is paused | blocked job log |
| Security | arbitrary scene-script invocation rejected | negative API test |
| Deployment | API and render worker genuinely reachable | health logs and completed job URI |

Automate tests in CI where possible; GPU and paid-provider tests run in explicitly authorized environments. Record `NOT_RUN` rather than passing a skipped integration test.
