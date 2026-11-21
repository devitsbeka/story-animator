# Motion design, editing, voice and sound

Blender for 3D spatial motion; Remotion for precise typography, 2D UI animation and branded overlays; FFmpeg for robust assembly and encoding; OpenTimelineIO for interchange. Use Manim optionally for math/diagrams. Keep shot editing independent of expensive Blender renders.

## Video strategy

Shot duration and cuts match narration/music beat and visual intent; avoid unmotivated transitions. Implement multi-track timebase (integer frames) and robust audio sync. Vertical subtitles within safe area, avoid conflict with platform UI overlays. Support word / phrase captions, glow-free premium editorial styles and accessibility contrast.

## Sound

Narration provider adapter with voice consistency and TTS fallback; forced alignment with actual audio, trim silence, SFX at motivated events, ambience beds, music stems and ducking. Use licensed sources and preserve media origin/rights. Validate loudness, clipping and appropriate fades. Never imply copyrighted soundtrack assets are included.

## Exports

1080×1920, 1920×1080, 1080×1080 default profiles; 24/30/60 fps explicit; H.264 AAC MP4 first, optional ProRes mezzanine and H.265. Verify duration, visible frames, streams and no unexpected freeze; produce thumbnail and metadata manifest.
