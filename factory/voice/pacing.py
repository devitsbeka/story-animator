"""Pacing: words-per-second targets per format (recipes/ENGAGEMENT_RECIPE.md N-1, ARCHITECTURE formats).

shorts: 2.8-3.1 w/s overall; docuseries: 2.4-2.7 w/s.  wps is measured over the voiced span
(first word start -> last word end), the same number the story checks use.
"""
TARGETS = {"short": (2.8, 3.1), "docuseries": (2.4, 2.7)}
# ElevenLabs voice_settings.speed accepts 0.7..1.2; stay well inside so the voice keeps its character
SPEED_RANGE = (0.85, 1.15)
# post-hoc atempo correction is a last resort (pitch is preserved, but artefacts grow past ~8%)
TEMPO_RANGE = (0.93, 1.08)


def target(fmt):
    return TARGETS.get(fmt or "short", TARGETS["short"])


def centre(fmt):
    lo, hi = target(fmt)
    return (lo + hi) / 2.0


def wps(words):
    if not words:
        return 0.0
    span = words[-1]["e"] - words[0]["s"]
    return len(words) / span if span > 0 else 0.0


def band_distance(value, fmt):
    """0 inside the band, else the w/s distance to the nearest edge."""
    lo, hi = target(fmt)
    return max(0.0, lo - value, value - hi)


def in_band(value, fmt):
    return band_distance(value, fmt) == 0.0


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def speed_for(native_wps, fmt):
    """voice_settings.speed to request so a voice whose measured pace at speed 1.0 is native_wps lands
    at the band centre.  None when no profile is known (send no speed)."""
    if not native_wps:
        return None
    s = _clamp(centre(fmt) / native_wps, *SPEED_RANGE)
    return round(s, 3) if abs(s - 1.0) > 0.01 else 1.0


def tempo_correction(measured_wps, fmt):
    """atempo factor that brings an out-of-band take to the nearest band edge (1.0 when in band)."""
    if not measured_wps or in_band(measured_wps, fmt):
        return 1.0
    lo, hi = target(fmt)
    goal = lo + 0.02 if measured_wps < lo else hi - 0.02
    return round(_clamp(goal / measured_wps, *TEMPO_RANGE), 4)
