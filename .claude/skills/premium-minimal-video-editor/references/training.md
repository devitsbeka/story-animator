# Train a reusable style pack from real references

## Source requirement
Original workflow example: 20 premium sample videos, around 130 editorial screenshots, 225 animation references, plus a Figma categorization board. These numbers describe the tutorial, **not** the contents of this ZIP. Never report achieved counts not confirmed on disk.

## Acquisition and inventory
1. Ask for user-provided video files or authorized accessible URLs and Figma board. Fetch only with accessible tools and rights. Capture `source_id`, `title`, `origin_url`, `license`, `duration`, `fps`, `resolution`, and hash in `style-pack/source-inventory.json`.
2. Probe each video and transcribe actual dialogue; link every spoken phrase to scene classification.
3. Extract regular inspection frames (e.g. 1–2 fps); detect shot boundaries using ffmpeg scene metrics; sample extra frames around any animation; generate contact sheet via `scripts/make_contact_sheet.py`.
4. For each scene extract: video ID, start/end ms, narrative function, P01..P10/AROLL type, palette (sampled), fonts (human-confirmed, not guessed with certainty), text content, anchor coordinates, safe margin, asset categories, texture strength, transition, motion path, duration, audio cue and confidence.
5. Classify clips into ten principles. Retain actual cropped reference frames and spritesheets of sampled keyframes; preserve source citations and timecode. Do not represent sampled stills as original editable animations.
6. Build editable manifest, `style-pack/style-manifest.json`, with typography, gradients/palette, textures, layout tokens and motion ranges. Board interpretations must be flagged as empirical or inferred.
7. If Figma tools inaccessible, request exported PDF/PNG or user board screenshots; do not claim inspected board.

## Animation reference card schema
```
{
 "id":"reference-001", "video_id":"video-01", "source_start_ms":1200,
 "source_end_ms":2950, "principle_id":"P04", "intent":"connect ideas",
 "script_text":"...", "frame_samples":["...png"],
 "design":{"font_primary":"...","accent":"#...","layout":"..."},
 "motion":{"path":"...","keyframes":[{"ms":0,"event":"line begins"}]},
 "sound":{"cue":"thin draw"},"rights":"reference only","confidence":0.78
}
```

## Verification
Write a count report: provided sources, successfully read, scenes detected, stills sampled, animation cards extracted, principle coverage and unclassifiable scenes. Deduplicate identical sequences. Avoid "100% trained" claims unless footage and measurements actually support them.

## Figma procedure
Make one top-level Figma board with source index and 10 columns P01–P10; include sample frame, timecode, notes on why chosen, and asset/motion breakdown. Zoom into individual scene examples to identify details. If true editable Figma access is not granted, provide a comparable exported board or HTML contact sheet with openly labeled limitation.
