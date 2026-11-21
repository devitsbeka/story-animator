# Production-quality acceptance checklist (mandatory)

## Honest gate recording
For each gate, status must be `pass`, `fail`, or `not_verified`; never silently mark unknown as pass. Final video must not be described as fully complete when a critical gate fails.

### Source and transcription
- Source files verified; license/provenance recorded.
- Full spoken word coverage checked; original-to-edited time map verified; 30ms padding applied as a default, not indiscriminately to every silence.
- No chopped syllable, missing names, odd pitch, stutter, breathing artifacts or phoneme overlaps.

### Story and style
- Every scene has actual transcript purpose and assigned type.
- A-roll introduction before illustrative explanation, unless editorial exception documented.
- Ten principle definitions were applied and inspected; scene family choices are motivated. Required scene types *selected in the plan* all executed.
- Consistent typography, color palette, rough-paper texture, restrained accent blue, legible composition.
- All figures, typography, motion, edges and texture move coherently; no texture detached from painting during reveal.
- No use of licensed/non-owned reference output without valid permission.

### Image/video render
- No blank/unwanted black frames, placeholder assets, stretched footage, wrong aspect ratio, clipped subtitles or cropped illustration.
- Human shots and object detail remain readable after vignette; references don't hide faces.
- Data depicted correctly; schematic visuals explicitly labeled.
- Exact number of scenes in plan equals number of rendered planned scenes; timeline gaps/overlaps accounted for.
- Verify video decodes, reports expected dimensions/fps/duration. Inspect images at beginning/middle/end and transitions; don't assert visual inspection based solely on ffprobe.

### Audio
- Voice intact and intelligible; music under dialogue, effects tied to actual animation beats.
- No clipping, abrupt audio jumps, wrong channel mapping, unlicensed tracks or missing sound.

### Revisions
- Every feedback item has status, timecode, test description and outcome; regression tested previously approved scenes.

### Final delivery
- Source, manifest, plan, SRT/VTT if possible, QA report and MP4 exist and are usable.
- If tools/facilities prevented step, describe missing deliverable and concrete block.
