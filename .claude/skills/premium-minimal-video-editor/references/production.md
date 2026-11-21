# Precise editorial and rendering workflow

## Preflight
- Determine platform, aspect ratio, frame rate, intended length, spoken language, transcript, brand, preferred voice/dialogue treatment.
- Check availability of `ffmpeg`, `ffprobe`, Node, npm, installed Remotion, font access, ASR, visual asset search, Figma, browser and file permissions.
- Keep raw files immutable and output clear manifests. Avoid browsing/login/paid purchases without permissions.

## Transcript and silence work
- First use a provided time-aligned word transcript, or run an actual available ASR system (Whisper/faster-whisper/service if accessible). Millisecond timestamps mean integer ms values (not scientifically exact articulation onset).
- `scripts/audio_silences.py` calls ffmpeg `silencedetect`; its output is a candidate list, **not** automatic final cut list. Carefully inspect breaths, punctuation, emotion, hard consonant boundaries, overlapping words. Default trim pad 30 ms each side; adapt and flag.
- Store `analysis/words.json`: `[{"text":"hello","start_ms":130,"end_ms":420,"confidence":0.96}]`. Store approved edit timeline and original-to-edited time map. Transcript errors are high priority.
- For precise FFmpeg trimming: use `atrim`, `asetpts`, `trim`, `setpts`, concat filters and encode; avoid inaccurate `-c copy` frame seeking. Check A/V sync after cuts. Keep room tone crossfades where suitable.

## Semantic planning rules
- First categorize sentences: thesis, label, explanation, example, number, comparison, emotional inflection, punchline, transition. Provide at least two scene options for impactful sentences. Choose one deliberately.
- Introduce new category on human A-roll; explain via scene design; return to face after high-density visuals. Make first visual hook match strongest semantic beat.
- Supply shot start/end ms, transcript excerpt, word emphasis, scene family, reference ID (if real), assets, animation action, notes, transitions, text layers, SFX cue. Verify non-overlapping timeline continuity.
- Use `scripts/storyboard.py` for editable local HTML on left + video/transcript right. It stores changes in browser memory and exports revised JSON via explicit download; no false persistence promise.

## Asset sourcing
- Prefer user assets, generated original shapes, hand-coded illustrations, public domain or permissively licensed stock. Record URLs, creator and terms in `assets-manifest.json`.
- Do not depend on scraping protected social platforms or unverified license availability. Do not substitute a claimed image of a real person with invented likeness when accuracy matters. If source access unavailable, use original symbolic visual treatment and flag it.

## Remotion execution
- Copy `assets/remotion-starter/` into job workspace. `npm install` only where internet/package access exists; validate against installed versions. Starter demonstrates actual editable compositions and a manifest-driven timeline; customize to approved storyboard and match style references.
- Use absolute sequence frame starts/durations derived from milliseconds; never reuse original clip source times after removing pauses without mapping them.
- Include components for ALL families, even if only subset used in the chosen edit. Do not mark completed family as present when no scene of that family rendered.
- Keep grain stable, gradients restrained, fonts licensed. Ensure no text cropping at scene boundaries; accurate line and track motion.
- Export a preview, generate ffprobe validation and filmstrip, review before picture lock.

## Deliverables
1. `renders/final.mp4` and `renders/first-cut.mp4` when successful.
2. `remotion/` editable project and `plan/edit-plan.json`.
3. `plan/storyboard.html`, captions SRT/VTT (if word timestamps available), `assets/assets-manifest.json`.
4. `qc/report.json`, `qc/contact-sheet.jpg`, revision log and provenance.
5. Provide actual paths, dimensions, duration, FPS, codec, peak/loudness and limitations.
