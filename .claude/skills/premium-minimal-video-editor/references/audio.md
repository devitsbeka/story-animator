# Sound design and finishing specification

## Before audio pass
Do NOT add final SFX/music ahead of approved picture lock when a user review is expected. Dialogue stays authoritative. Preserve original speech and avoid speech-edit artifacts.

## Sound-to-visual map
- P01 caption accents: small clean click/tick, sparingly, not per every word.
- P04/P05 line drawing: subtle pencil/ink movement, miniature ping at anchor dots.
- P03 painted reveal: soft textured slide; low whoosh only if move merits it.
- P10 charts: drawing/tracker clicks or highlighter-like strokes synced to new data point.
- P07–P09 reveal: restrained paper/cloth rustle or airy swell.
- Cut to A-roll: mostly dry or subtle room continuity. Avoid repetitive generic whoosh fatigue.

## Mix guidance
- Use user-owned or properly licensed music, otherwise produce original low-level ambient underscore using available synthesis; never claim commercial tracks are free.
- Apply dialogue cleanup and consistent level without removing speech texture. Start music around 18–26 dB below dialogue perceptually; duck under critical lines. Do not treat this range as measured target.
- Check output loudness for platform needs, avoid true-peak clipping (target <= -1 dBTP if limiter available), prevent harsh clicks at edit boundaries. AAC export at appropriate bitrate.
- Validate with `ffmpeg -af loudnorm=print_format=json` / `ebur128` when supported; report actual observed values, no fabricated loudness.
- Export stems if requested and legally possible. Keep cue sheet with scene ID, source, rights, timing, gain.
