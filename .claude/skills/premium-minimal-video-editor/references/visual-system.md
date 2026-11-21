# Design tokens and kinetic grammar

These are implementable **starting tokens** inferred from the verbal description, NOT measured values from the missing original examples. When available, override through empirical reference analysis and document overrides in `style-pack/style-manifest.json`.

## Color and surfaces
- Background paper `#F3F0E8`, alternate pure-ish `#F9F8F5`, charcoal `#111317`, full black near `#0C0E12`.
- Primary text on light `#191B1C`; light text on dark `#F6F3EB`; muted secondary `#777B7B`.
- Accent cobalt `#386AD9` (reference-adjustable). Reserve blue for line, tracker, occasional semantic emphasis; do not flood every scene.
- Paper: procedural very subtle monochrome noise 2–7% opacity, fibrous/grain or irregular matte pattern. The matte stays attached to scene/asset when camera moves; no static screen-space sticker sliding unnaturally.
- Edge vignette on photo/painting scenes: unobtrusive; center subject remains clear. Rough edges and cloth contrast more noticeable in illustration scenes.

## Typeface and layout
- Default sans: Inter; optional serif: Playfair Display / Italic. Acquire legally and respect licensing. Fallback sans system-ui; fallback serif Georgia italic. Fonts not bundled in ZIP.
- 1080x1920 (9:16) working default; 1920x1080 16:9 when asked. Safe margins >= 6% horizontal, 8% vertical, and account for platform overlay zones. High contrast. Headline ~52–105 px on 1080-wide portrait depending on phrase; secondary ~30–54 px. These are guidelines, not fixed measurements.
- Typography rhythm: emphasize semantic words, typographic contrast rather than garish color. Avoid text directly on face, 1px type, collision and automated unreviewed overflow.
- Alignment: intentional asymmetry; use negative space and gaps. Shapes may overlap text only as planned visual compositional relationship (e.g. line interrupted by phrase).

## Motion system
- 30 fps default; 60 fps optional if user requests and resources permit. Work in frame-accurate calculations; dialogue timestamps remain in milliseconds.
- Reveals: subtle opacity/transform easing; words keyed to spoken onset, not random animation delays.
- Hand-drawn line: animate path stroke dashoffset via Remotion `interpolate` or frame-based derived SVG path length.
- Camera move: controlled pan and 1–4% scale, approximately 0.3–0.8 seconds for reveal, depending on speech; intentional holds.
- Transitions: direct cut for speaker returns, purposeful match motion or low-amplitude paper wipe for visual change; avoid relentless flashy zooms/glows.
- Smoothing: no pop in/out, aliasing, abrupt discontinuities. At least one calm pause after information-dense scene.

## Texture implementation
- Generate a deterministic small grain overlay from SVG noise filter or asset; ensure no flicker between frames, no heavy blocking artifacts.
- For painted images, apply controlled desaturation, subtle rough vignette/mask, slight parallax to the whole treatment to avoid texture misalignment.

## Accessibility
- Maintain legible captions; never drop transcript words from access captions even if designed overlay is selective.
- Minimum practical exposure duration for text, respect rapid speech without unreadably flashing lines.
- Prefer non-flashing transitions and protect photosensitive audiences.
