"""
lighting.py - sequence lighting + night world for the Blender episode renderer.

Implements the ATLAS lighting presets (atlas/ATLAS_CINEMA_AGENT_KIT/03_CATALOGS/lighting_presets.yaml)
as code and the PIXAR_RECIPE section 4 sequence-lighting rules (checklist L1-L9):

  * ONE world-fixed key per shot taken from env.moonDir (the same vector the procedural sky uses for its
    moon disc, so light and sky always agree). Within a sequence (shot id letter, or shot["sequence"])
    the key azimuth must stay within +-15 deg and elevation within +-10 deg; check_sequences() reports
    violations unless the shot carries lighting.cheat_reason / lighting.light_event (a dawn change counts
    as a light event automatically).
  * Cool blue moon key vs warm practicals (hue separation >= 120 deg, L5); key:fill on the hero face
    6:1-8:1 for night (preset fill_ratio), with an absolute floor so the shadow side never goes black
    (L9: >= 0.03 linear for a ~0.45 albedo face).
  * Hero face fill: a soft area light that follows the hero's head but keeps a WORLD-fixed direction
    (opposite-ish the key azimuth), so it does not change when the camera cuts. Light-linked to the hero
    so it does not flatten the set.
  * Rim ("moon kiss") and eye light are the only camera-aware cheats, as the recipe allows (sec. 4.3.4);
    the rim is weakened automatically when the moon itself is already behind the hero.
  * Night world: a Poly Haven night HDRI (downscaled + normalised, rotated so its moon matches moonDir,
    lower hemisphere folded so the ground never shows) lights and reflects the scene, while camera rays
    still see the art-directed procedural sky (stars, moon disc, clouds). Dawn blends in a day sky HDRI.
  * Optional bounded volumetric haze (Volume Scatter, density 0.002-0.02 /m, anisotropy 0.3-0.6).

Spec interface (all optional; the default preset is moonlight_practical_mix):
  world.lighting = {"preset": "moonlight_practical_mix",
                    "sequences": {"D": {"preset": "storm_night"}},     # per-sequence overrides
                    ...any preset parameter...}
  shot.env.lighting / shot.lighting = {"preset": ..., "cheat_reason": ..., "light_event": ..., params}
  preset "legacy" (or render_episode --lighting legacy) keeps the old hard-coded rig.

Pure-python parts (presets, resolve(), check_sequences()) import without bpy:
  python3 cloud/blender/lighting.py --check episodes/sentinel/episode_v2.json
  python3 cloud/blender/lighting.py --list
  python3 cloud/blender/lighting.py --qa frame.png [...]      # L5 bright-pixel fraction (needs numpy+PIL)
"""
import colorsys
import json
import math
import os
import sys
import tempfile

try:
    import bpy
    from mathutils import Vector
except ImportError:  # pure-python use (checks, CLI)
    bpy = None
    Vector = None

LOG_PREFIX = "[lighting]"


def log(*a):
    print(LOG_PREFIX, *a, flush=True)


# ----------------------------------------------------------------------------------------------
# colour helpers
# ----------------------------------------------------------------------------------------------
MOON_BLUE = (0.55, 0.70, 1.0)      # PIXAR_RECIPE 4.2 moonlight convention
WARM_PRACTICAL = (1.0, 0.62, 0.32)  # 2700-3200 K look


def kelvin_rgb(k):
    """Blackbody-ish colour for k Kelvin (Tanner Helland fit), normalised so max channel = 1, linear-ish."""
    t = max(1000.0, min(40000.0, float(k))) / 100.0
    if t <= 66:
        r = 255.0
        g = 99.4708025861 * math.log(t) - 161.1195681661
        b = 0.0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307
    else:
        r = 329.698727446 * ((t - 60) ** -0.1332047592)
        g = 288.1221695283 * ((t - 60) ** -0.0755148492)
        b = 255.0
    c = [max(0.0, min(255.0, x)) / 255.0 for x in (r, g, b)]
    c = [x ** 2.2 for x in c]  # sRGB-ish -> linear
    m = max(c) or 1.0
    return tuple(x / m for x in c)


def hue_deg(rgb):
    return colorsys.rgb_to_hsv(*rgb)[0] * 360.0


def hue_sep(a, b):
    d = abs(hue_deg(a) - hue_deg(b)) % 360.0
    return min(d, 360.0 - d)


# ----------------------------------------------------------------------------------------------
# presets (units: key_energy = irradiance on a surface facing the key, Blender sun strength W/m^2;
# fill_ratio = key:fill on the hero face; rim_energy / eye_light_energy = multiples of key irradiance)
# ----------------------------------------------------------------------------------------------
BASE = {
    "family": "night",            # night | dawn | day | interior | studio | underwater
    "key_source": "celestial",    # celestial: world-fixed from env.moonDir ; subject: relative to hero front
    "key_az_deg": 45.0,           # subject mode: azimuth from the hero's front, + = hero's left
    "key_elev_deg": None,         # subject mode elevation; celestial: None = keep env elevation
    "key_energy": 1.8,
    "key_color": MOON_BLUE,
    "key_kelvin": None,           # overrides key_color when set
    "key_size_m": 1.2,            # subject-mode area light size
    "shadow_softness": 1.5,       # celestial sun angular diameter, degrees
    "key_motivation": "moon",
    "fill_ratio": 7.0,
    "fill_color": (0.45, 0.52, 0.78),
    "fill_az_offset_deg": 160.0,  # face fill azimuth = key azimuth + this (world-fixed)
    "fill_elev_deg": 12.0,
    "fill_motivation": "bounce:water",
    "rim_energy": 1.7,            # night rim 1-2x key (PIXAR 4.1): dark clothing needs it to separate
    "rim_color": (0.62, 0.74, 1.0),
    "rim_elev_deg": 38.0,
    "rim_motivation": "moon",
    "hdri": "ph:moonlit_golf",
    "hdri_ambient": 0.05,         # mean upper-hemisphere radiance after normalisation (sky fill <= ~30% of face)
    "hdri_reflect": 0.3,          # share of HDRI in glossy rays (rest: procedural sky, so reflections match)
    "hdri_saturation": 0.45,
    "hdri_tint": (0.80, 0.88, 1.0),
    "haze_density": 0.0,
    "haze_color": (0.55, 0.62, 0.80),
    "haze_anisotropy": 0.45,
    "haze_size_m": (500.0, 500.0, 140.0),
    "exposure_ev": 0.0,
    "practical_color": WARM_PRACTICAL,
    "practical_kelvin": None,
    "retint_practicals": True,
    "flicker": 0.0,               # key flicker amplitude (fire/candle), 6-12 Hz noise
    "lightning_per_s": 0.0,       # storm: random key flashes (logged as light events)
    "face_fill": True,
    "wrap_share": 0.6,            # share of the face fill given by the omni-directional hero wrap (camera-proof floor)
    "eye_light": True,
    "eye_light_energy": 0.45,
    "shadow_floor": 0.03,         # L9: min shadow-side face radiance (linear) for a 0.45 albedo face
    "face_albedo": 0.45,
    # >>> polish_light look-dev
    "face_key": 1.3,              # face key cheat, x key irradiance when the moon misses the visible face side
    "face_key_min": 0.5,          # ...and a share even when the moon keys the face: the hero outshines the set
    "face_key_max_deg": 50.0,     # max azimuth of the face key off the camera axis (3/4 key)
    "face_key_elev_deg": 18.0,    # low enough to get under the cap brim into the eyes
    "face_key_size_m": 1.1,
    "face_key_warmth": 0.55,      # moon blue -> warm-neutral: protects the skin hue band (recipe 6.3 appeal cheat)
    "view_look": None,            # AgX look; None = by family (night: Medium High Contrast, storm: Punchy, dawn: Base)
    "practical_glow": 2.2,        # deck-lamp glass emission strength (warm, not clipping)
    "practical_bulb_scale": 0.3,  # deck-lamp bulb power scale (props author 60 W)
    # CAN-L2 night continuity: the hero face's incident exposure (meter at the eyes, aimed at the lens) is held to
    # one per-sequence target, so a close-up never reads brighter ('daylight') than its wide. Only the hero-linked
    # cheats (face key / fill / wrap) are trimmed; the moon, practicals and the set are untouched.
    "face_normalize": True,
    "face_target": 0.55,          # target face incident irradiance, x key_energy (calibrated on A01a/A03/C21)
    "face_ev_offset": 0.0,        # deliberate per-shot exposure change in stops (needs cheat_reason/light_event)
    "face_ev_tol": 1.0 / 3.0,     # wide <-> close-up tolerance, stops
    # <<< polish_light
}

DAWN = {"family": "dawn", "key_energy": 2.2, "key_color": (1.0, 0.70, 0.52), "fill_ratio": 3.0,
        "fill_color": (0.55, 0.55, 0.75), "rim_energy": 0.9, "rim_color": (1.0, 0.78, 0.62),
        "hdri": "ph:kloppenheim_02_puresky", "hdri_ambient": 0.11, "hdri_saturation": 0.7,
        "hdri_tint": (1.0, 0.86, 0.80), "exposure_ev": -0.3, "shadow_softness": 2.5,
        "key_motivation": "sun", "rim_motivation": "sun", "retint_practicals": False,
        "haze_color": (0.92, 0.74, 0.66)}  # polish_light: dawn mist picks up the pink-gold sky

STUDIO = {"family": "studio", "key_source": "subject", "key_motivation": "softbox", "hdri": None,
          "fill_motivation": "bounce:card", "rim_motivation": "kicker", "key_color": kelvin_rgb(5600),
          "fill_color": kelvin_rgb(5600), "rim_color": (1.0, 1.0, 1.0), "retint_practicals": False,
          "hdri_ambient": 0.0, "key_energy": 2.0, "exposure_ev": -0.5}

DAY = {"family": "day", "hdri": "ph:kloppenheim_02_puresky", "hdri_ambient": 0.25, "hdri_saturation": 1.0,
       "hdri_tint": (1.0, 1.0, 1.0), "key_motivation": "sun", "rim_motivation": "sun", "key_color": kelvin_rgb(5600),
       "fill_color": (0.7, 0.8, 1.0), "rim_color": (1.0, 0.95, 0.9), "retint_practicals": False,
       "eye_light": True, "shadow_softness": 0.6}

INTERIOR = {"family": "interior", "key_source": "subject", "hdri": None, "hdri_ambient": 0.0,
            "key_motivation": "practical:lamp", "retint_practicals": True}


def _p(*parts, **kw):
    out = {}
    for p in parts:
        out.update(p)
    out.update(kw)
    return out


PRESETS = {
    # ---- the night set this episode lives in
    # polish_light: low moonlit sea mist (homogeneous, 12 m deep: horizon depth, stars stay clear) for depth on every night preset of the episode
    "moonlight": _p(haze_density=0.0011, haze_size_m=(700.0, 700.0, 12.0), exposure_ev=-0.4),
    "moonlight_practical_mix": _p(fill_ratio=6.5, haze_density=0.0011, haze_size_m=(700.0, 700.0, 12.0), exposure_ev=-0.4),
    "low_key_portrait": _p(fill_ratio=10.0, rim_energy=1.3),
    "rim_silhouette": _p(fill_ratio=14.0, rim_energy=2.2, key_energy=1.2, eye_light=False, face_key=0.0),
    "blue_hour": _p(key_energy=0.8, key_color=(0.45, 0.60, 1.0), fill_ratio=3.0, hdri_ambient=0.07,
                    hdri="ph:qwantani_night", exposure_ev=0.2, rim_energy=0.8),
    "storm_night": _p(key_energy=0.8, key_color=(0.50, 0.60, 0.85), fill_ratio=8.0, rim_energy=1.5,
                      hdri="ph:qwantani_night", hdri_ambient=0.025, hdri_saturation=0.2,
                      haze_density=0.004, exposure_ev=0.25, lightning_per_s=0.12, shadow_softness=8.0),
    "firelight": _p(key_source="subject", key_az_deg=60.0, key_elev_deg=8.0, key_kelvin=1900,
                    key_energy=1.6, key_motivation="fire", fill_ratio=6.0, rim_color=MOON_BLUE,
                    rim_motivation="moon", flicker=0.15, retint_practicals=True),
    "candlelight": _p(INTERIOR, key_az_deg=30.0, key_elev_deg=-5.0, key_kelvin=1900, key_energy=1.2,
                      key_size_m=0.15, fill_ratio=8.0, flicker=0.12, key_motivation="practical:candle",
                      rim_energy=0.4),
    "night_city": _p(fill_ratio=5.0, practical_kelvin=3000, hdri="ph:qwantani_night", hdri_ambient=0.045),
    "neon_night": _p(fill_ratio=4.0, practical_color=(1.0, 0.2, 0.75), rim_color=(0.2, 0.9, 1.0),
                     rim_energy=1.6, hdri="ph:qwantani_night"),
    "rainy_street": _p(fill_ratio=5.0, haze_density=0.006, practical_kelvin=3000, hdri_reflect=0.5,
                       hdri="ph:qwantani_night"),
    "screen_lit": _p(key_source="subject", key_az_deg=0.0, key_elev_deg=0.0, key_color=(0.6, 0.75, 1.0),
                     key_size_m=0.35, key_energy=1.0, key_motivation="practical:screen", fill_ratio=8.0),
    "underwater": _p(family="underwater", key_color=(0.30, 0.80, 0.90), key_energy=1.6, key_elev_deg=80.0,
                     fill_ratio=3.0, fill_color=(0.2, 0.5, 0.6), rim_energy=0.5, rim_color=(0.4, 0.9, 1.0),
                     hdri=None, hdri_ambient=0.0, haze_density=0.05, haze_color=(0.10, 0.40, 0.50),
                     haze_anisotropy=0.6, exposure_ev=0.3, retint_practicals=False, shadow_softness=12.0),
    # ---- dawn / day
    "dawn": _p(DAWN),
    "foggy_dawn": _p(DAWN, haze_density=0.02, fill_ratio=2.5, shadow_softness=10.0, haze_color=(0.85, 0.75, 0.75)),
    "golden_hour": _p(DAY, key_elev_deg=6.0, key_color=kelvin_rgb(3200), key_energy=3.0, fill_ratio=3.0,
                      rim_energy=1.4, exposure_ev=-1.0),
    "midday": _p(DAY, key_elev_deg=65.0, key_energy=6.0, fill_ratio=3.0, rim_energy=0.3, exposure_ev=-2.0),
    "soft_overcast": _p(DAY, key_energy=1.6, shadow_softness=60.0, fill_ratio=1.8, rim_energy=0.2,
                        hdri_saturation=0.3, exposure_ev=-0.8),
    "volumetric_sunshafts": _p(DAY, key_elev_deg=25.0, key_energy=4.0, fill_ratio=4.0, haze_density=0.015,
                               haze_color=(0.9, 0.88, 0.8), exposure_ev=-1.3),
    "window_motivated": _p(INTERIOR, key_az_deg=70.0, key_elev_deg=15.0, key_size_m=2.0, key_kelvin=6000,
                           key_energy=1.8, fill_ratio=4.0, key_motivation="window", retint_practicals=False),
    "tungsten_interior": _p(INTERIOR, key_az_deg=40.0, key_elev_deg=30.0, key_kelvin=2900, key_energy=1.8,
                            fill_ratio=4.0, fill_color=kelvin_rgb(3400)),
    # ---- portrait (subject-relative key)
    "three_point_portrait": _p(STUDIO, key_az_deg=45.0, key_elev_deg=35.0, fill_ratio=3.0, rim_energy=0.8),
    "rembrandt": _p(STUDIO, key_az_deg=45.0, key_elev_deg=45.0, fill_ratio=4.0, rim_energy=0.4),
    "butterfly": _p(STUDIO, key_az_deg=0.0, key_elev_deg=40.0, fill_ratio=3.0, rim_energy=0.5),
    "split": _p(STUDIO, key_az_deg=90.0, key_elev_deg=10.0, fill_ratio=8.0, rim_energy=0.6),
    "loop": _p(STUDIO, key_az_deg=35.0, key_elev_deg=30.0, fill_ratio=3.5, rim_energy=0.6),
    "high_key_portrait": _p(STUDIO, key_az_deg=20.0, key_elev_deg=25.0, fill_ratio=1.5, rim_energy=0.6,
                            key_size_m=2.5, exposure_ev=0.0),
    # ---- product / studio
    "product_softbox": _p(STUDIO, key_az_deg=30.0, key_elev_deg=50.0, key_size_m=2.0, fill_ratio=2.5, rim_energy=1.0),
    "strip_highlight": _p(STUDIO, key_az_deg=90.0, key_elev_deg=10.0, key_size_m=0.4, fill_ratio=6.0, rim_energy=1.5),
    "metal_product": _p(STUDIO, key_az_deg=60.0, key_elev_deg=40.0, key_size_m=3.0, fill_ratio=3.0, rim_energy=1.2),
    "glass_product": _p(STUDIO, key_az_deg=170.0, key_elev_deg=20.0, key_size_m=2.5, fill_ratio=4.0, rim_energy=2.0),
    "jewelry_hero": _p(STUDIO, key_az_deg=30.0, key_elev_deg=60.0, key_size_m=0.6, fill_ratio=3.0, rim_energy=1.4,
                       eye_light_energy=0.5),
    "white_seamless": _p(STUDIO, key_az_deg=20.0, key_elev_deg=30.0, key_size_m=3.0, fill_ratio=1.6, rim_energy=0.5,
                         exposure_ev=0.3),
    "studio_black": _p(STUDIO, key_az_deg=50.0, key_elev_deg=35.0, key_size_m=1.0, fill_ratio=10.0, rim_energy=1.6),
}

# numeric/colour fields interpolated when a night preset drifts toward dawn (env.dawn > 0)
_BLEND = ("key_energy", "key_color", "fill_ratio", "fill_color", "rim_energy", "rim_color", "hdri_ambient",
          "hdri_saturation", "hdri_tint", "exposure_ev", "shadow_softness", "haze_color")  # polish_light: + haze

DEFAULT_PRESET = "moonlight_practical_mix"
LEGACY = ("legacy", "off", "none")


# ----------------------------------------------------------------------------------------------
# pure-python resolution
# ----------------------------------------------------------------------------------------------
def sequence_of(shot):
    if shot.get("sequence"):
        return str(shot["sequence"])
    sid = str(shot.get("id", ""))
    # polish_light: the LEADING letters only ('A01b' -> 'A'; it was 'Ab', which split A01a/A01b into two sequences)
    lead = ""
    for ch in sid:
        if not ch.isalpha():
            break
        lead += ch
    return lead or sid


def _lerp(a, b, t):
    if isinstance(a, (tuple, list)):
        return tuple(x + (y - x) * t for x, y in zip(a, b))
    return a + (b - a) * t


def shot_env(spec, shot):
    env = dict(spec.get("world") or {})
    env.update(shot.get("env") or {})
    return env


# --- style system hook (factory/styles): preset per time of day -------------------------------
def time_of_day(env):
    """night | storm | dawn | day | interior for a merged shot env (world + shot.env)."""
    tod = env.get("timeOfDay")
    if tod in ("night", "storm", "dawn", "day", "interior"):
        return tod
    w = env.get("weather") or {}
    if float(w.get("rain", 0) or 0) >= 0.5 or float(w.get("overcast", 0) or 0) >= 0.5 or float(env.get("seaState", 0) or 0) >= 2.2:
        return "storm"
    if float(env.get("dawn", 0) or 0) >= 0.5:
        return "dawn"
    return "night"


def style_lighting(spec, shot):
    """The style's lighting entry ({preset, params...}) for the shot's SEQUENCE, or None.

    The time of day is read from the sequence's first shot so one sequence keeps one preset (L8); a night sequence
    drifting into dawn stays on its night preset and blends (resolve). Scripted storm lightning (env.weather.lightning)
    switches the preset's random lightning off so flashes are not doubled."""
    table = (((spec.get("style") or {}).get("lighting") or {}).get("time_of_day")) or {}
    if not table:
        return None
    seq = sequence_of(shot)
    members = [s for s in spec.get("shots") or [] if sequence_of(s) == seq] or [shot]
    tod = time_of_day(shot_env(spec, members[0]))
    entry = dict(table.get(tod) or table.get("night") or {})
    if not entry.get("preset"):
        return None
    if any(((s.get("env") or {}).get("weather") or {}).get("lightning") for s in members):
        entry["lightning_per_s"] = 0.0
    entry["time_of_day"] = tod
    return entry
# --- end style system hook ---------------------------------------------------------------------


def resolve(spec, shot, override=None):
    """Merged lighting config for one shot (dict), or None for the legacy rig."""
    env = shot_env(spec, shot)
    wl = dict((spec.get("world") or {}).get("lighting") or {})
    seq = sequence_of(shot)
    layers = [wl, dict((wl.get("sequences") or {}).get(seq) or {}),
              dict((shot.get("env") or {}).get("lighting") or {}), dict(shot.get("lighting") or {})]
    # style system hook: with no explicit preset anywhere, the episode style picks one per time of day
    if not any(L.get("preset") for L in layers):
        sl = style_lighting(spec, shot)
        if sl:
            layers.insert(0, sl)
    preset = DEFAULT_PRESET
    for L in layers:
        preset = L.get("preset", preset)
    if override:
        preset = override
    if str(preset).lower() in LEGACY:
        return None
    if preset not in PRESETS:
        log(f"WARNING: unknown lighting preset '{preset}', using {DEFAULT_PRESET}")
        preset = DEFAULT_PRESET
    cfg = dict(BASE)
    cfg.update(PRESETS[preset])
    for L in layers:
        cfg.update({k: v for k, v in L.items() if k in BASE})
    dawn = float(env.get("dawn", 0) or 0)
    cfg["hdri_mix"] = [(cfg["hdri"], 1.0)] if cfg["hdri"] else []
    if cfg["family"] == "night" and dawn > 0:  # the night drifts into dawn: one continuous light event
        for k in _BLEND:
            cfg[k] = _lerp(cfg[k], DAWN[k], dawn)
        cfg["hdri_mix"] = [(h, w * (1 - dawn)) for h, w in cfg["hdri_mix"]] + [(DAWN["hdri"], dawn)]
        if dawn > 0.5:
            cfg["key_motivation"] = cfg["rim_motivation"] = "sun"
            cfg["retint_practicals"] = False
    if cfg.get("key_kelvin"):
        cfg["key_color"] = kelvin_rgb(cfg["key_kelvin"])
    if cfg.get("practical_kelvin"):
        cfg["practical_color"] = kelvin_rgb(cfg["practical_kelvin"])
    cfg["preset"] = preset
    cfg["sequence"] = seq
    cfg["dawn"] = dawn
    cfg["moonDir"] = list(env.get("moonDir", (0.12, 0.3, 1.0)))
    cfg["cheat_reason"] = next((L["cheat_reason"] for L in layers if L.get("cheat_reason")), None)
    cfg["light_event"] = next((L["light_event"] for L in layers if L.get("light_event")), None)
    return cfg


def key_angles(moon_dir_spec):
    """(azimuth, elevation) in degrees of a spec-space (Y up) direction; azimuth = atan2(x, z)."""
    x, y, z = moon_dir_spec
    return math.degrees(math.atan2(x, z)), math.degrees(math.atan2(y, math.hypot(x, z)))


def fill_irradiance(cfg):
    """Fill irradiance on the hero face: key/ratio, but never below the L9 shadow floor."""
    floor = cfg["shadow_floor"] * math.pi / max(cfg["face_albedo"], 0.05)
    return max(cfg["key_energy"] / max(cfg["fill_ratio"], 1.0), floor)


def check_sequences(spec, tol_az=15.0, tol_el=10.0):
    """PIXAR L2/L5 continuity report over a whole episode spec. Returns (rows, problems)."""
    rows, problems, ref = [], [], {}
    for shot in spec.get("shots", []):
        cfg = resolve(spec, shot)
        if cfg is None:
            rows.append({"shot": shot["id"], "preset": "legacy"})
            continue
        az, el = key_angles(cfg["moonDir"])
        seq = cfg["sequence"]
        r = ref.setdefault(seq, {"shot": shot["id"], "az": az, "el": el, "dawn": cfg["dawn"], "preset": cfg["preset"]})
        daz = (az - r["az"] + 180) % 360 - 180
        del_ = el - r["el"]
        event = cfg["light_event"] or ("dawn" if abs(cfg["dawn"] - r["dawn"]) > 0.2 else None)
        row = {"shot": shot["id"], "seq": seq, "preset": cfg["preset"], "key_az": round(az, 1), "key_el": round(el, 1),
               "d_az": round(daz, 1), "d_el": round(del_, 1), "dawn": cfg["dawn"],
               "key_fill": round(cfg["key_energy"] / fill_irradiance(cfg), 2),
               "hue_sep_practical": round(hue_sep(cfg["key_color"], cfg["practical_color"]), 1),
               "event": event, "cheat": cfg["cheat_reason"]}
        rows.append(row)
        if (abs(daz) > tol_az or abs(del_) > tol_el) and not (event or cfg["cheat_reason"]):
            problems.append(f"L2 {shot['id']}: key moved {daz:+.1f} az / {del_:+.1f} el vs {r['shot']} (seq {seq}) "
                            "without cheat_reason/light_event")
        if cfg["preset"] != r["preset"] and not (event or cfg["cheat_reason"]):
            problems.append(f"L8 {shot['id']}: preset {cfg['preset']} differs from sequence key shot {r['shot']} ({r['preset']})")
        if cfg["family"] == "night" and cfg["dawn"] < 0.5 and row["hue_sep_practical"] < 120:
            problems.append(f"L5 {shot['id']}: key/practical hue separation {row['hue_sep_practical']} < 120 deg")
    return rows, problems


# ----------------------------------------------------------------------------------------------
# Blender side
# ----------------------------------------------------------------------------------------------
STATE = {"cfg": None, "report": {}}


def active():
    return STATE["cfg"] is not None


def begin_shot(spec, shot, override=None):
    """Call once per shot before build_world. Returns the config (None = legacy rig)."""
    cfg = resolve(spec, shot, override)
    STATE["cfg"] = cfg
    STATE["shot"] = shot
    STATE["spec"] = spec  # polish_light: discovery map
    STATE["hero_arm"] = None  # polish_light: face meter
    STATE["cam_at"] = None
    STATE["report"] = {} if cfg is None else {
        "preset": cfg["preset"], "sequence": cfg["sequence"], "dawn": cfg["dawn"], "lights": [], "checks": {},
        "warnings": []}
    if cfg is not None:
        az, el = key_angles(cfg["moonDir"])
        STATE["report"].update({"key_az_deg": round(az, 2), "key_elev_deg": round(el, 2)})
        log(f"shot {shot.get('id')}: preset={cfg['preset']} seq={cfg['sequence']} key az={az:.1f} el={el:.1f} dawn={cfg['dawn']}")
    return cfg


def report():
    return STATE.get("report") or {}


def _b3(v):
    return Vector((v[0], -v[2], v[1]))


def _tag(ob, motivation, role):
    ob["lighting_rig"] = role
    ob["motivation"] = motivation
    STATE["report"]["lights"].append({"name": ob.name, "role": role, "motivation": motivation,
                                      "energy": round(float(ob.data.energy), 4)})


def _link(ob, coll=None):
    (coll or bpy.context.scene.collection).objects.link(ob)
    return ob


def _key_dir_blender(cfg):
    """unit vector pointing FROM the scene TOWARD the key (Blender space)."""
    d = _b3(cfg["moonDir"]).normalized()
    if cfg["key_source"] == "celestial" and cfg.get("key_elev_deg") is not None:
        az = math.atan2(d.y, d.x)
        el = math.radians(cfg["key_elev_deg"])
        d = Vector((math.cos(az) * math.cos(el), math.sin(az) * math.cos(el), math.sin(el)))
    return d


# ---------------- HDRI: cached downscale + stats ----------------
HDRI_FILES = {
    "ph:moonlit_golf": "polyhaven/moonlit_golf/moonlit_golf_4k.exr",
    "ph:qwantani_night": "polyhaven/qwantani_night/qwantani_night_4k.exr",
    "ph:kloppenheim_02_puresky": "polyhaven/kloppenheim_02_puresky/kloppenheim_02_puresky_4k.exr",
}
HDRI_RES = (1024, 512)


def _library_store():
    if os.environ.get("LIBRARY_STORE"):
        return os.environ["LIBRARY_STORE"]
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(os.path.dirname(here)), "library_store")


def _cache_dir():
    d = os.environ.get("LIGHTING_CACHE") or os.path.join(tempfile.gettempdir(), "story_animator_lighting")
    os.makedirs(d, exist_ok=True)
    return d


def _hdri_stats_and_clamp(img):
    """Find the moon/sun (brightest upper-hemisphere spot), then clamp it out of the image: the key lamp owns
    that light, the env should only be the soft sky. Returns stats measured on the CLAMPED image."""
    import numpy as np
    W, H = img.size
    raw = np.empty(W * H * 4, np.float32)
    img.pixels.foreach_get(raw)
    raw = raw.reshape(H, W, 4)
    px = raw[..., :3]
    lw = np.array([0.2126, 0.7152, 0.0722], np.float32)
    lum = px @ lw
    el = ((np.arange(H) + 0.5) / H - 0.5) * math.pi
    wgt = np.cos(el)[:, None] * np.ones((1, W))
    up = el > 0
    # brightest spot after a cheap 3x3 box blur
    L = lum.copy()
    L[~up] = 0
    Lb = L.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            Lb += np.roll(np.roll(L, dy, 0), dx, 1)
    r, c = np.unravel_index(int(np.argmax(Lb)), Lb.shape)
    peak = float(L[r, c])
    phi = 2 * math.pi * (c + 0.5) / W  # verified: Blender equirect u = atan2(y, -x) / 2pi
    elev = ((r + 0.5) / H - 0.5) * math.pi
    d = (-math.cos(phi) * math.cos(elev), math.sin(phi) * math.cos(elev), math.sin(elev))
    med = float(np.median(lum[up]))
    clip = max(8.0 * med, 1e-6)
    scale = np.minimum(1.0, clip / np.maximum(lum, 1e-9))[..., None]
    raw[..., :3] = px * scale
    img.pixels.foreach_set(raw.ravel())
    px = raw[..., :3]
    lum = px @ lw
    mean_up = float((lum[up] * wgt[up]).sum() / wgt[up].sum())
    col_up = (px[up] * wgt[up][..., None]).sum(axis=(0, 1)) / wgt[up].sum()
    return {"mean_up": mean_up, "color_up": [float(x) for x in col_up], "peak": peak, "median_up": med,
            "clip": clip, "peak_dir": list(d), "has_moon": bool(peak > 200 * max(med, 1e-6) and elev > math.radians(3))}


def load_hdri(hid):
    """(bpy image, stats) for a catalog HDRI id, using a downscaled, moon-clamped cached copy; (None, None) if missing."""
    rel = HDRI_FILES.get(hid)
    if rel is None:
        return None, None
    src = os.path.join(_library_store(), rel)
    if not os.path.exists(src):
        log(f"WARNING: HDRI {hid} not found at {src}")
        return None, None
    W, H = HDRI_RES
    base = os.path.join(_cache_dir(), f"{hid.replace(':', '_')}_{W}x{H}_clamped")
    exr, js = base + ".exr", base + ".json"
    if not (os.path.exists(exr) and os.path.exists(js)):
        tmp, tmpj = f"{exr}.{os.getpid()}.tmp.exr", f"{js}.{os.getpid()}.tmp"
        try:
            big = bpy.data.images.load(src, check_existing=False)
            big.scale(W, H)
            stats = _hdri_stats_and_clamp(big)
            big.filepath_raw = tmp
            big.file_format = "OPEN_EXR"
            big.save()
            bpy.data.images.remove(big)
            with open(tmpj, "w") as fh:
                json.dump(stats, fh)
            os.replace(tmp, exr)  # atomic: parallel renders may build the cache at the same time
            os.replace(tmpj, js)
        finally:
            for t in (tmp, tmpj):
                if os.path.exists(t):
                    os.remove(t)
        log(f"cached {hid} -> {exr}")
    img = bpy.data.images.load(exr, check_existing=True)
    with open(js) as fh:
        stats = json.load(fh)
    return img, stats


def _env_branch(nt, hid, weight, cfg, key_dir, link):
    """Environment texture branch: folded lower hemisphere, rotated moon->key, desaturated, normalised."""
    img, st = load_hdri(hid)
    if img is None:
        return None, None
    N = nt.nodes
    tc = N.new("ShaderNodeTexCoord")
    sep = N.new("ShaderNodeSeparateXYZ")
    link(tc.outputs["Generated"], sep.inputs[0])
    ab = N.new("ShaderNodeMath")
    ab.operation = "ABSOLUTE"
    link(sep.outputs["Z"], ab.inputs[0])
    comb = N.new("ShaderNodeCombineXYZ")
    link(sep.outputs["X"], comb.inputs["X"])
    link(sep.outputs["Y"], comb.inputs["Y"])
    link(ab.outputs[0], comb.inputs["Z"])
    mp = N.new("ShaderNodeMapping")
    mp.vector_type = "POINT"
    rot = 0.0
    if st["has_moon"]:  # spin the HDRI so its moon/sun sits at the key azimuth: theta = az(hdri) - az(key)
        pd = st["peak_dir"]
        rot = math.atan2(pd[1], pd[0]) - math.atan2(key_dir.y, key_dir.x)
    mp.inputs["Rotation"].default_value = (0.0, 0.0, rot)
    link(comb.outputs[0], mp.inputs["Vector"])
    et = N.new("ShaderNodeTexEnvironment")
    et.image = img
    link(mp.outputs[0], et.inputs["Vector"])
    hs = N.new("ShaderNodeHueSaturation")
    hs.inputs["Saturation"].default_value = cfg["hdri_saturation"]
    link(et.outputs[0], hs.inputs["Color"])
    tint = N.new("ShaderNodeMix")
    tint.data_type, tint.blend_type = "RGBA", "MULTIPLY"
    tint.inputs[0].default_value = 1.0
    link(hs.outputs[0], tint.inputs[6])
    tint.inputs[7].default_value = (*cfg["hdri_tint"], 1.0)
    strength = weight * cfg["hdri_ambient"] / max(st["mean_up"], 1e-6)
    return tint.outputs[2], {"id": hid, "weight": round(weight, 3), "strength": round(strength, 4),
                             "rot_deg": round(math.degrees(rot), 1), "src_mean": round(st["mean_up"], 5),
                             "has_moon": st["has_moon"], "_strength": strength}


def dress_world(world, sky_bg, out):
    """Insert the HDRI lighting/reflection branches between the procedural sky background and the output.
    Camera rays keep the art-directed procedural sky; diffuse rays see the normalised HDRI; glossy rays a mix."""
    cfg = STATE["cfg"]
    nt = world.node_tree
    N, link = nt.nodes, nt.links.new
    key_dir = _key_dir_blender(cfg)
    branches = []
    for hid, w in cfg["hdri_mix"]:
        if w <= 1e-3:
            continue
        sock, info = _env_branch(nt, hid, w, cfg, key_dir, link)
        if sock is not None:
            branches.append((sock, info))
    if not branches:
        STATE["report"]["hdri"] = []
        return False
    bgs = []
    for sock, info in branches:
        b = N.new("ShaderNodeBackground")
        link(sock, b.inputs["Color"])
        b.inputs["Strength"].default_value = info.pop("_strength")
        bgs.append(b.outputs[0])
    env = bgs[0]
    for extra in bgs[1:]:
        add = N.new("ShaderNodeAddShader")
        link(env, add.inputs[0])
        link(extra, add.inputs[1])
        env = add.outputs[0]
    lp = N.new("ShaderNodeLightPath")
    refl = N.new("ShaderNodeMixShader")
    refl.inputs[0].default_value = cfg["hdri_reflect"]
    link(sky_bg.outputs[0], refl.inputs[1])
    link(env, refl.inputs[2])
    noncam = N.new("ShaderNodeMixShader")  # fac = glossy ray -> reflections, else HDRI env
    link(lp.outputs["Is Glossy Ray"], noncam.inputs[0])
    link(env, noncam.inputs[1])
    link(refl.outputs[0], noncam.inputs[2])
    final = N.new("ShaderNodeMixShader")  # fac = camera ray -> visible procedural sky
    link(lp.outputs["Is Camera Ray"], final.inputs[0])
    link(noncam.outputs[0], final.inputs[1])
    link(sky_bg.outputs[0], final.inputs[2])
    link(final.outputs[0], out.inputs["Surface"])
    STATE["report"]["hdri"] = [i for _, i in branches]
    return True


def build_world_rig(world, sky_bg, out):
    """Key light + HDRI env for the shot (replaces the legacy Moon/SkyFill suns). Returns the key object."""
    cfg = STATE["cfg"]
    has_env = dress_world(world, sky_bg, out)
    key_dir = _key_dir_blender(cfg)
    kd = bpy.data.lights.new("Moon" if cfg["key_motivation"] == "moon" else "Key", "SUN")
    kd.color = tuple(cfg["key_color"])
    kd.energy = cfg["key_energy"] if cfg["key_source"] == "celestial" else cfg["key_energy"] * 0.25
    kd.angle = math.radians(cfg["shadow_softness"])
    key = _link(bpy.data.objects.new(kd.name, kd))
    key.rotation_mode = "QUATERNION"
    key.rotation_quaternion = (-key_dir).to_track_quat("-Z", "Y")
    # subject-keyed presets keep a dim celestial light as the environment key (motivation: sky)
    _tag(key, cfg["key_motivation"] if cfg["key_source"] == "celestial" else "sky", "key" if cfg["key_source"] == "celestial" else "env_key")
    if not has_env and cfg["family"] not in ("studio",):
        # no HDRI available: a soft hemisphere fill so the set is not black (sky fill <= 30% of face light)
        fd = bpy.data.lights.new("SkyFill", "SUN")
        fd.color = tuple(cfg["fill_color"])
        fd.energy = 0.3 * fill_irradiance(cfg)
        fd.angle = math.radians(90)
        fo = _link(bpy.data.objects.new("SkyFill", fd))
        _tag(fo, "sky", "sky_fill")
    STATE["key"] = key
    STATE["key_dir"] = key_dir
    return key


# ---------------- hero rig ----------------
def _area(name, energy, size, color, parent=None, loc=(0, 0, 0)):
    ld = bpy.data.lights.new(name, "AREA")
    ld.energy, ld.size, ld.color = energy, size, tuple(color)
    ob = _link(bpy.data.objects.new(name, ld))
    if parent is not None:
        ob.parent = parent
    ob.location = loc
    for attr in ("visible_camera",):
        try:
            setattr(ob, attr, False)
        except AttributeError:
            pass
    return ob


def _receivers(holder, name):
    coll = bpy.data.collections.new(name)
    stack = [holder]
    while stack:
        o = stack.pop()
        stack.extend(o.children)
        if o.type == "MESH":
            coll.objects.link(o)
    return coll


def _light_link(ob, coll, shadows=True):
    try:
        ob.light_linking.receiver_collection = coll
        if shadows:
            ob.light_linking.blocker_collection = coll
    except AttributeError:
        STATE["report"]["warnings"].append("light linking unavailable; hero lights also light the set")


def _camera_mean(shot):
    """Mean camera and look positions (spec space -> Blender), resolving yacht-space keys like build_shot."""
    keys = shot["camera"]["keys"]
    y = shot.get("yacht") or {}
    cs, ls = Vector((0, 0, 0)), Vector((0, 0, 0))
    for k in keys:
        c, l = list(k["cam"]), list(k["look"])
        if shot["camera"].get("space", "world") == "yacht" and y:
            h = y.get("heading", 0.0)
            ch, sh = math.cos(h), math.sin(h)
            def tr(p):  # rot_y(h) then translate (three.js Y rotation)
                return [p[0] * ch + p[2] * sh + y["x"], p[1], -p[0] * sh + p[2] * ch + y["z"]]
            c, l = tr(c), tr(l)
        cs += _b3(c)
        ls += _b3(l)
    n = max(len(keys), 1)
    return cs / n, ls / n


# >>> polish_light: hero-rig helpers (head bone of any rig, true world head position for yacht-space shots)
HEAD_BONES = ("def-head", "head", "mixamorig:head", "fk-head")


def head_bone_of(arm):
    names = {b.name.lower(): b.name for b in arm.data.bones}
    return next((names[n] for n in HEAD_BONES if n in names), None)


def eye_point_rest(arm):
    """Mid-eye point in armature space (rest): centre of the eyelid-corner bones, else 0.12 m above the head
    bone head, pushed slightly forward."""
    pts = [b.head_local for b in arm.data.bones if b.name.startswith(("DEF-Eyelid_Upper1", "DEF-Eyelid_Lower1",
                                                                         "DEF-Eyelid_Upper4", "DEF-Eyelid_Lower4"))]
    if pts:
        c = sum(pts, Vector((0, 0, 0))) / len(pts)
        return c + Vector((0, 0.02, 0))  # the lid bones sit on the cornea: the eyeball centre is a bit behind
    hb = head_bone_of(arm)
    b = arm.data.bones[hb] if hb else None
    return (b.head_local + Vector((0, -0.08, 0.12))) if b else Vector((0, 0, 1.6))


def _shot_yacht_matrix(shot):
    """Blender-space matrix of the yacht's nominal (spec x/z/heading) pose; identity without a yacht."""
    from mathutils import Matrix
    y = shot.get("yacht")
    if not y:
        return Matrix.Identity(4)
    return Matrix.Translation(_b3((y["x"], 0.0, y["z"]))) @ Matrix.Rotation(y.get("heading", 0.0), 4, "Z")


def hero_world_point(holder, arm, shot, p_arm):
    """World position of an armature-space point at the shot's nominal yacht pose. During the build the yacht
    root is not yet moved to (x, z, heading) (that is keyed per frame later), so arm.matrix_world is
    yacht-local: re-place it with the spec yacht pose so camera distances / rim sides are right."""
    bpy.context.view_layer.update()
    root = holder
    while root.parent is not None:
        root = root.parent
    local = root.matrix_world.inverted() @ (arm.matrix_world @ p_arm)
    return _shot_yacht_matrix(shot) @ local if root is not holder else arm.matrix_world @ p_arm


def _posed_head(arm, hb):
    pb = arm.pose.bones.get(hb) if hb else None
    return pb.head.copy() if pb else Vector((0, 0, 1.6))
# <<< polish_light


def build_hero_rig(idx, holder, arm, actor, camera, shot):
    """Hero lights for the sequence rig: world-direction face fill, camera-aware rim cheat, eye light.
    Replaces the legacy hero-parented 'GAFFER moonlight portrait' lights."""
    cfg = STATE["cfg"]
    key_dir = STATE.get("key_dir") or _key_dir_blender(cfg)
    head_bone = head_bone_of(arm)  # polish_light: CloudRig heads are DEF-Head
    if actor.get("name", "hero") == "hero" or STATE.get("hero_arm") is None:
        STATE["hero_arm"] = arm  # polish_light: the face meter reads this rig
    # head follower: world position of the head, NO rotation -> children keep world-fixed directions
    fol = bpy.data.objects.new(f"light_head_{idx}", None)
    _link(fol)
    if head_bone:
        c = fol.constraints.new("COPY_LOCATION")
        c.target, c.subtarget = arm, head_bone
    else:
        c = fol.constraints.new("COPY_LOCATION")
        c.target = holder
        fol.location = (0, 0, 1.6)
        c.use_offset = True
    recv = _receivers(holder, f"hero_receivers_{idx}")
    rig = actor.get("lightRig") or {}
    kaz = math.atan2(key_dir.y, key_dir.x)
    E_key = cfg["key_energy"]
    E_fill_total = fill_irradiance(cfg)
    # ambient from the HDRI on a vertical face ~ pi * L / 2 (half the sky, dark sea below)
    E_amb = math.pi * cfg["hdri_ambient"] * 0.5 if STATE["report"].get("hdri") else 0.0
    E_fill = max(E_fill_total - E_amb, 0.0)
    rep = STATE["report"]
    # --- subject-relative key (portrait / practical presets)
    if cfg["key_source"] == "subject":
        bpy.context.view_layer.update()
        fwd = holder.matrix_world.to_3x3() @ Vector((0, -1, 0))  # glTF +z front -> Blender -Y in holder space
        faz = math.atan2(fwd.y, fwd.x) + math.radians(cfg["key_az_deg"])
        kel = math.radians(cfg["key_elev_deg"] if cfg["key_elev_deg"] is not None else 35.0)
        d = 2.0
        kdir = Vector((math.cos(faz) * math.cos(kel), math.sin(faz) * math.cos(kel), math.sin(kel)))
        k = _area(f"hero_key_{idx}", E_key * math.pi * d * d, cfg["key_size_m"], cfg["key_color"], fol, kdir * d)
        _aim(k, fol)
        _light_link(k, recv, shadows=False)
        _tag(k, cfg["key_motivation"], "key")
        if cfg["flicker"] > 0:
            _flicker(k.data, shot, cfg["flicker"])
    # --- face fill, two parts, both light-linked to the hero (they do not flatten the set):
    #  (a) wrap: a 180-degree 'sun' from straight above -> near-uniform soft light on every side of the head,
    #      so the shadow side clears the L9 floor whatever the camera does (vertical face gets ~half its strength);
    #  (b) directional fill from a world-fixed azimuth opposite-ish the key, for modelling.
    if cfg["face_fill"] and E_fill > 0:
        share = float(cfg["wrap_share"])
        wd = bpy.data.lights.new(f"hero_wrap_{idx}", "SUN")
        wd.energy = float(rig.get("wrap", 2.0 * share * E_fill))
        wd.angle = math.radians(180.0)
        wd.color = tuple(cfg["fill_color"])
        wo = _link(bpy.data.objects.new(f"hero_wrap_{idx}", wd))
        _light_link(wo, recv)
        _tag(wo, "sky", "face_wrap")
        faz = kaz + math.radians(cfg["fill_az_offset_deg"])
        fel = math.radians(cfg["fill_elev_deg"])
        d = 1.7
        fdir = Vector((math.cos(faz) * math.cos(fel), math.sin(faz) * math.cos(fel), math.sin(fel)))
        energy = float(rig.get("fill", (1.0 - share) * E_fill * math.pi * d * d))
        f = _area(f"hero_fill_{idx}", energy, 1.4, cfg["fill_color"], fol, fdir * d)
        _aim(f, fol)
        _light_link(f, recv)
        _tag(f, cfg["fill_motivation"], "face_fill")
    # --- rim cheat: behind the hero as seen from the shot's camera, biased to the moon side
    cam_mean, look_mean = _camera_mean(shot)
    bpy.context.view_layer.update()
    # polish_light: true world eye position at the shot's yacht pose (was the yacht-local rest head -> 600 m
    # camera distances on yacht shots away from the origin, so no eye light and a wrong rim side)
    head_w = hero_world_point(holder, arm, shot, eye_point_rest(arm) if head_bone else _posed_head(arm, head_bone))
    to_cam = (cam_mean - head_w)
    to_cam.z = 0
    to_cam = to_cam.normalized() if to_cam.length > 1e-4 else Vector((0, -1, 0))
    kh = Vector((key_dir.x, key_dir.y, 0)).normalized()
    backlit = -to_cam.dot(kh)  # +1: moon behind the hero (already a natural rim), -1: moon behind camera
    rim_scale = 1.0 - 0.35 * max(0.0, backlit)  # backlit: the moon rims the far side; keep an edge kick
    side = 1.0 if to_cam.cross(kh).z >= 0 else -1.0
    E_rim = cfg["rim_energy"] * E_key * rim_scale
    piv = bpy.data.objects.new(f"rim_pivot_{idx}", None)
    _link(piv)
    piv.parent = fol
    lt = piv.constraints.new("LOCKED_TRACK")  # -Y toward the camera, spinning about world Z only
    lt.target, lt.track_axis, lt.lock_axis = camera, "TRACK_NEGATIVE_Y", "LOCK_Z"
    d = 1.8
    rel = math.radians(cfg["rim_elev_deg"])
    lat = math.radians(60.0) * side  # wide: catches the silhouette edge the camera sees
    loc = (math.sin(lat) * math.cos(rel) * d, math.cos(lat) * math.cos(rel) * d, math.sin(rel) * d)
    if E_rim > 0:
        r = _area(f"hero_rim_{idx}", float(rig.get("rim", E_rim * math.pi * d * d)), 0.7, cfg["rim_color"], piv, loc)
        _aim(r, fol)
        _light_link(r, recv, shadows=False)
        _tag(r, cfg["rim_motivation"], "rim")
    # >>> polish_light: soft face key cheat. The world-fixed moon only models the face when the camera is on the
    # moon side; when it is not (moon behind / beside the hero) the face falls into the 6:1 fill and reads as a
    # black mask. A large soft area light, light-linked to the hero only, keeps the moon's elevation and side
    # but is swung toward the camera (max `face_key_max_deg` off the lens axis) and is faded in as the real moon
    # stops lighting the visible side of the face. Logged as a cheat (recipe 4.3.4 'kicker on face').
    frontness = to_cam.dot(kh)  # +1 moon behind camera (moon keys the face), -1 moon behind hero
    E_fk = cfg["face_key"] * E_key * max(cfg["face_key_min"], 1.0 - max(0.0, frontness))
    if cfg["face_key"] > 0 and cfg["key_source"] == "celestial" and E_fk > 0.02:
        cam_az = math.atan2(to_cam.y, to_cam.x)
        rel_az = math.atan2(to_cam.cross(kh).z, to_cam.dot(kh))  # signed angle camera->moon (azimuth)
        lim = math.radians(cfg["face_key_max_deg"])
        faz = cam_az + max(-lim, min(lim, rel_az)) if abs(rel_az) > 1e-3 else cam_az + lim * side
        fel = math.radians(cfg["face_key_elev_deg"])
        d = 1.6
        fdir = Vector((math.cos(faz) * math.cos(fel), math.sin(faz) * math.cos(fel), math.sin(fel)))
        fk = _area(f"hero_facekey_{idx}", E_fk * math.pi * d * d, cfg["face_key_size_m"],
                   _lerp(tuple(cfg["key_color"]), (1.0, 0.93, 0.86), cfg["face_key_warmth"]), fol, fdir * d)
        _aim(fk, fol)
        _light_link(fk, recv)
        _tag(fk, cfg["key_motivation"], "face_key")
        rep.setdefault("cheats", []).append(f"face_key: moon swung {math.degrees(rel_az - (faz - cam_az)):+.0f} deg toward camera")
    # <<< polish_light
    # --- eye light (spec only), only when the camera is close (MCU or tighter)
    cam_dist = (cam_mean - head_w).length
    if cfg["eye_light"] and cam_dist < 3.5:
        # polish_light: small source (crisp catchlight on the coated cornea), just above the lens
        e = _area(f"hero_eyelight_{idx}", 1.0, 0.12, (1.0, 0.97, 0.92), camera, (0.10, 0.12, 0.0))
        e.data.energy = cfg["eye_light_energy"] * E_key * math.pi * cam_dist * cam_dist
        for attr in ("visible_diffuse", "visible_transmission", "visible_volume_scatter"):
            try:
                setattr(e, attr, False)
            except AttributeError:
                pass
        _light_link(e, recv, shadows=False)
        _tag(e, "cheat:eye_light", "eye_light")
    rep["hero"] = {"E_key": round(E_key, 3), "E_fill_total": round(E_fill_total, 3), "E_ambient_est": round(E_amb, 3),
                   "key_fill_ratio": round(E_key / E_fill_total, 2), "rim_scale": round(rim_scale, 2),
                   "backlit": round(backlit, 2), "cam_dist_m": round(cam_dist, 2),
                   "shadow_side_radiance_est": round(cfg["face_albedo"] * E_fill_total / math.pi, 4)}
    _checks(cfg)


def _aim(ob, target):
    c = ob.constraints.new("TRACK_TO")
    c.target, c.track_axis, c.up_axis = target, "TRACK_NEGATIVE_Z", "UP_Y"


def _flicker(ld, shot, amp):
    """6-12 Hz deterministic flicker, +-amp, keyed per frame (a pure function of the frame)."""
    base = ld.energy
    fps = float(bpy.context.scene.render.fps or 30)
    for f in range(shot["from"] - 1, shot["to"] + 2):
        t = f / fps
        n = math.sin(t * 2 * math.pi * 7.1) * 0.5 + math.sin(t * 2 * math.pi * 11.3 + 1.3) * 0.35 + math.sin(t * 2 * math.pi * 3.7 + 0.4) * 0.15
        ld.energy = base * (1.0 + amp * n)
        ld.keyframe_insert("energy", frame=f)


def _checks(cfg):
    rep = STATE["report"]
    roles = {l["role"]: l for l in rep["lights"]}
    key_E = cfg["key_energy"]
    rep["checks"] = {
        "L1_all_motivated": all(l.get("motivation") for l in rep["lights"]),
        "L3_key_fill": rep.get("hero", {}).get("key_fill_ratio"),
        "L5_hue_sep_key_practical": round(hue_sep(cfg["key_color"], cfg["practical_color"]), 1),
        "L6_eye_light": "eye_light" in roles,
        "L7_rim": "rim" in roles,
        "L9_shadow_side_est": rep.get("hero", {}).get("shadow_side_radiance_est"),
        "key_E": key_E,
    }


# ---------------- per-shot finishing ----------------
def _retint(scene, cfg):
    n = 0
    for ob in scene.objects:
        if ob.type != "LIGHT" or "lighting_rig" in ob or ob.data.type == "SUN":
            continue
        nm = ob.name.lower()
        if any(s in nm for s in ("strobe", "nav", "port", "starboard", "search", "beacon", "red", "green")):
            continue
        h, s, v = colorsys.rgb_to_hsv(*ob.data.color)
        if s < 0.35 or 0.02 < h < 0.17:  # white-ish or already warm: push to the sequence's practical colour
            ob.data.color = tuple(cfg["practical_color"])
            n += 1
    return n


def _haze(scene, cfg, centre):
    sx, sy, sz = cfg["haze_size_m"]
    me = bpy.data.meshes.new("HazeVolume")
    hx, hy = sx / 2, sy / 2
    vs = [(-hx, -hy, -2), (hx, -hy, -2), (hx, hy, -2), (-hx, hy, -2), (-hx, -hy, sz), (hx, -hy, sz), (hx, hy, sz), (-hx, hy, sz)]
    fs = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    me.from_pydata(vs, [], fs)
    ob = _link(bpy.data.objects.new("HazeVolume", me))
    ob.location = centre
    m = bpy.data.materials.new("Haze")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    v = nt.nodes.new("ShaderNodeVolumeScatter")
    v.inputs["Color"].default_value = (*cfg["haze_color"], 1)
    v.inputs["Density"].default_value = cfg["haze_density"]
    v.inputs["Anisotropy"].default_value = cfg["haze_anisotropy"]
    nt.links.new(v.outputs[0], o.inputs["Volume"])
    me.materials.append(m)
    ob["lighting_rig"] = "haze"
    try:
        scene.cycles.volume_bounces = max(scene.cycles.volume_bounces, 0)
        scene.cycles.volume_step_rate = 4.0
    except AttributeError:
        pass
    return ob


def _lightning(cfg, shot, key):
    import random
    import zlib
    rnd = random.Random(zlib.crc32(str(shot.get("id", "")).encode()))  # deterministic across processes/chunks
    f0, f1 = shot["from"], shot["to"]
    base = key.data.energy
    events = []
    f = f0
    while f < f1:
        f += max(1, int(rnd.expovariate(cfg["lightning_per_s"]) * 30))
        if f < f1:
            events.append(f)
    for f in range(f0 - 1, f1 + 2):
        key.data.energy = base
        for e in events:
            if 0 <= f - e < 4:
                key.data.energy = base * (6.0 if f - e in (0, 2) else 2.0)
        key.data.keyframe_insert("energy", frame=f)
    return events


# >>> polish_light: practicals, per-sequence look, camera depth of field
def _scale_animated(idblock, data_path, k):
    ad = getattr(idblock, "animation_data", None)
    if ad and ad.action:
        for fc in ad.action.fcurves:
            if fc.data_path == data_path:
                for kp in fc.keyframe_points:
                    kp.co[1] *= k
                    kp.handle_left[1] *= k
                    kp.handle_right[1] *= k
                return True
    return False


def _practicals(scene, cfg):
    """Deck-lamp look: the glass glows warm amber instead of clipping to white, the bulb is a soft source the
    size of the glass (soft shadows, inverse-square falloff) so it pools warm light on the console / face."""
    n = 0
    target = float(cfg["practical_glow"])
    warm = tuple(cfg["practical_color"])
    for m in bpy.data.materials:
        if not m.name.startswith("lamp_glass") or not m.use_nodes:
            continue
        b = m.node_tree.nodes.get("Principled BSDF")
        if b is None:
            continue
        es = b.inputs["Emission Strength"]
        base = es.default_value
        k = target / 8.0  # props.anchor_lamp authors 8.0
        if not _scale_animated(m.node_tree, f'nodes["{b.name}"].inputs[{list(b.inputs).index(es)}].default_value', k):
            es.default_value = base * k
        b.inputs["Emission Color"].default_value = (1.0, warm[1] * 0.85, warm[2] * 0.55, 1.0)
        b.inputs["Base Color"].default_value = (0.9, 0.62, 0.32, 1.0)
        b.inputs["Roughness"].default_value = 0.35  # frosted glass: no hot specular
        n += 1
    for m in bpy.data.materials:  # instrument glow: readable, not clipping cyan-white blobs next to the face
        if m.name.startswith(("helm_gauge", "panel_led")) and m.use_nodes and m.node_tree.nodes.get("Principled BSDF"):
            b = m.node_tree.nodes["Principled BSDF"]
            es = b.inputs["Emission Strength"]
            if _scale_animated(m.node_tree, f'nodes["{b.name}"].inputs[{list(b.inputs).index(es)}].default_value', 0.35):
                n += 1
    for ob in scene.objects:
        if ob.type == "LIGHT" and ob.data.type == "POINT" and ob.name.startswith("lamp") and ob.name.split(".")[0].endswith("_bulb"):
            ob.data.shadow_soft_size = 0.045
            ob.data.color = warm
            k = float(cfg["practical_bulb_scale"])  # 60 W at arm's length is ~10x the moon on the face
            if not _scale_animated(ob.data, "energy", k):
                ob.data.energy *= k
            n += 1
    return n


ALBEDO_WHITE_MAX = 0.6  # code-built white props (helm console, panels): off-white, never a clipping 0.8-0.9


def _albedo_safe(scene):
    """Exposure-safe albedo: flat (untextured) near-white Principled base colours are scaled to <= 0.6 so
    moonlit white boxes do not clip next to the hero. Textured / emissive / character materials are left alone."""
    n = 0
    seen = set()
    for ob in scene.objects:
        if ob.type != "MESH" or ob.get("lighting_rig"):
            continue
        for slot in ob.material_slots:
            m = slot.material
            if m is None or m.name in seen or not m.use_nodes or m.name.startswith(("hero.", "jay.")):
                continue
            seen.add(m.name)
            for b in m.node_tree.nodes:
                if b.type != "BSDF_PRINCIPLED" or b.inputs["Base Color"].is_linked:
                    continue
                if b.inputs["Emission Strength"].default_value > 0 and max(b.inputs["Emission Color"].default_value[:3]) > 0:
                    continue
                c = b.inputs["Base Color"].default_value
                if min(c[:3]) > 0.45 and max(c[:3]) > ALBEDO_WHITE_MAX:
                    k = ALBEDO_WHITE_MAX / max(c[:3])
                    b.inputs["Base Color"].default_value = (c[0] * k, c[1] * k, c[2] * k, c[3])
                    n += 1
    return n


LOOKS = {"night": "AgX - Medium High Contrast", "storm": "AgX - Punchy", "dawn": "AgX - Base Contrast",
         "day": "AgX - Base Contrast", "interior": "AgX - Medium High Contrast", "studio": "AgX - Base Contrast",
         "underwater": "AgX - Medium Contrast"}


def _grade(scene, cfg):
    fam = cfg["family"]
    if fam == "night" and cfg.get("lightning_per_s", 0) > 0:
        fam = "storm"
    if fam == "night" and cfg["dawn"] >= 0.3:
        fam = "dawn"
    look = cfg.get("view_look") or LOOKS.get(fam)
    if look:
        try:
            scene.view_settings.look = look
        except TypeError:
            pass
    return scene.view_settings.look


def motion_blur_policy(scene, arm, cam_at=None):
    """Motion blur where it reads: camera + object (yacht, props) transform blur everywhere, deformation blur
    only on the hero. The ocean / island meshes are millions of vertices; deform blur on them triples their
    memory (OOM on shared 15 GB boxes) for blur nobody sees under the camera's own motion blur."""
    if not scene.render.use_motion_blur:
        return "off"
    hero = set()
    if arm is not None:
        root = arm.parent or arm
        hero = {o.name for o in root.children_recursive}
    n = 0
    for ob in scene.objects:
        if ob.type not in ("MESH", "CURVES", "CURVE"):
            continue
        cy = getattr(ob, "cycles", None)
        if cy is None:
            continue
        if ob.name not in hero:
            cy.use_deform_motion = False
            n += 1
    try:
        scene.cycles.motion_blur_position = "CENTER"
    except AttributeError:
        pass
    scene.render.motion_blur_shutter = 0.5  # 180-degree shutter
    star = star_safe_shutter(scene, cam_at)  # L016: stars must not streak into 'rain'
    return f"camera+object; deform on hero only ({n} meshes rigid); shutter {scene.render.motion_blur_shutter:.2f} ({star})"


STAR_STREAK_MAX_PX = 1.2   # a star may smear at most this many pixels at render resolution (L016)
STAR_SHUTTER_MIN = 0.06    # never below ~22 degrees: the hero keeps a hint of motion blur
STAR_SHUTTER_PCTL = 0.9    # the shot's shutter follows the 90th-percentile sky speed; peaks are handled by dimming


def _rot_rate_px(mats_fovs, H, step):
    """Image-space speed (px/frame) of a point at infinity between consecutive (matrix, vfov_rad) samples taken
    every `step` frames: rotation only (translation does not move the sky); roll included (sky spins about the
    centre, worst at the frame corner ~ half the diagonal, approximated by the frame height)."""
    out = []
    for (m0, f0), (m1, f1) in zip(mats_fovs, mats_fovs[1:]):
        q0, q1 = m0.to_quaternion(), m1.to_quaternion()
        ang = q1.rotation_difference(q0).angle
        fov = 0.5 * (f0 + f1)
        zoom = abs(f1 - f0) / max(fov, 1e-6) * 0.5  # a zoom moves edge stars by ~half the frame per unit fov change
        out.append((ang / max(fov, 1e-6) + zoom) * H / step)
    return out


def _keyed_cam_samples(scene, cam, frames, sub=4):
    """(matrix_world, vfov) of the KEYED camera (includes the buoyancy solve) at sub-frame steps."""
    import mathutils
    ad = cam.animation_data
    if not (ad and ad.action):
        return []
    fcq = {fc.array_index: fc for fc in ad.action.fcurves if fc.data_path == "rotation_quaternion"}
    if len(fcq) < 4:
        return []
    cad = cam.data.animation_data
    lens = next((fc for fc in (cad.action.fcurves if cad and cad.action else []) if fc.data_path == "lens"), None)
    out = []
    for i in range(int(frames[0]) * sub - sub // 2, int(frames[-1]) * sub + sub // 2 + 1):
        f = i / float(sub)
        q = mathutils.Quaternion([fcq[k].evaluate(f) for k in range(4)]).normalized()
        L = lens.evaluate(f) if lens else cam.data.lens
        out.append((q.to_matrix().to_4x4(), 2 * math.atan((cam.data.sensor_height / 2) / max(L, 1e-3))))
    return out


def _star_nodes(scene):
    w = scene.world
    if not (w and w.use_nodes):
        return []
    return [n for n in w.node_tree.nodes if n.label == "stars" and n.type == "MIX"]


def star_safe_shutter(scene, cam_at=None):
    """L016: stars must never streak into 'rain' under camera motion blur.
    1) one shutter per SHOT (chunk-independent): from the 90th-percentile sky speed of the shot's camera rig over
       ALL its frames (cam_at(f) -> (matrix, vfov_deg), render_episode.lod_cam_at), so a star smears at most
       STAR_STREAK_MAX_PX; never below STAR_SHUTTER_MIN.
    2) per-frame star dimming for what the shutter cannot absorb (impact shakes, whip pans): the star layer is
       keyed down by (limit / streak)^2 on the frames where the keyed camera (with the buoyancy solve) still
       smears them, so a residual streak is too faint to read. Day / dawn (no stars) keep 180 degrees."""
    cfg = STATE.get("cfg")
    cam = scene.camera
    rep = STATE.get("report") if STATE.get("report") is not None else {}
    if cfg is None or cam is None or cfg["family"] != "night" or cfg["dawn"] >= 0.5:
        return "no stars"
    H = scene.render.resolution_y * scene.render.resolution_percentage / 100.0
    shot = STATE.get("shot") or {}
    rates = []
    if cam_at is not None and shot:
        f0, f1 = int(shot["from"]), int(shot["to"])
        sm = []
        for i in range((f1 - f0) * 2 + 1):  # half-frame steps over the whole shot
            m, fov = cam_at(f0 + i * 0.5)
            sm.append((m, math.radians(fov)))
        rates = _rot_rate_px(sm, H, 0.5)
    rng = (scene.frame_start, scene.frame_end)
    keyed = _rot_rate_px(_keyed_cam_samples(scene, cam, rng), H, 0.25)
    if not rates:  # no rig function: fall back to the keyed camera over the rendered range
        rates = keyed
    if not rates:
        return "static camera"
    srt = sorted(rates)
    p = srt[min(len(srt) - 1, int(STAR_SHUTTER_PCTL * (len(srt) - 1)))]
    sh = scene.render.motion_blur_shutter
    if p * sh > STAR_STREAK_MAX_PX:
        sh = max(STAR_SHUTTER_MIN, STAR_STREAK_MAX_PX / p)
        scene.render.motion_blur_shutter = sh
    # per-frame residual: dim the star layer where the keyed camera still streaks them
    dims = {}
    nodes = _star_nodes(scene)
    if keyed and nodes:
        sub = 4
        f_first = scene.frame_start
        for f in range(scene.frame_start, scene.frame_end + 1):
            # samples around frame f covering the shutter (centred): indices of (f - sh/2 .. f + sh/2)
            i0 = (f - f_first) * sub + sub // 2 - 1
            seg = keyed[max(0, i0 - 1): i0 + 2]
            r = max(seg) if seg else 0.0
            streak = r * sh
            k = 1.0 if streak <= STAR_STREAK_MAX_PX else (STAR_STREAK_MAX_PX / streak) ** 2
            dims[f] = round(k, 3)
        if any(v < 0.999 for v in dims.values()):
            for n in nodes:
                sock = n.inputs[7]
                base = tuple(sock.default_value)
                for f, k in dims.items():
                    sock.default_value = (base[0] * k, base[1] * k, base[2] * k, base[3])
                    sock.keyframe_insert("default_value", frame=f)
                sock.default_value = base
                ad = scene.world.node_tree.animation_data
                for fc in (ad.action.fcurves if ad and ad.action else []):
                    for kp in fc.keyframe_points:
                        kp.interpolation = "CONSTANT"
    worst = max(keyed) if keyed else p
    out = (f"sky p90 {p:.1f} px/frame (shot max {max(rates):.1f}, keyed max {worst:.1f}) -> shutter {sh:.3f}, "
           f"streak p90 {p * sh:.2f} px; stars dimmed on {sum(1 for v in dims.values() if v < 0.999)} frame(s)")
    rep["stars"] = {"sky_px_per_frame_p90": round(p, 2), "shot_max": round(max(rates), 2), "keyed_max": round(worst, 2),
                    "shutter": round(sh, 3), "streak_px_p90": round(p * sh, 2),
                    "dimmed": {str(f): v for f, v in dims.items() if v < 0.999}}
    rep["star_streak_px"] = round(p * sh, 2)
    return out


# shot size -> f-stop (frame height at the subject, metres). Wides stay deep; CUs get a soft background.
FSTOPS = ((0.55, 2.8, "CU"), (1.0, 4.0, "MCU"), (1.8, 5.6, "MS"), (3.5, 8.0, "MLS"), (1e9, 16.0, "WS"))


def setup_dof(scene, cam, arm, holder, shot, quality="final", cam_at=None):
    """Depth of field focused on the hero's eyes (an empty riding the head bone at the mid-eye point, so the
    focus follows the performance and the camera every frame); f-stop from the shot size at the keyframe."""
    rep = STATE.get("report")
    if rep is None:
        rep = STATE["report"] = {}
    camd = cam.data
    STATE["cam_at"] = cam_at  # polish_light: chunk-independent camera for the face meter / discovery reveals
    if arm is not None and STATE.get("hero_arm") is None:
        STATE["hero_arm"] = arm
    rep["motion_blur"] = motion_blur_policy(scene, arm, cam_at)
    log(f"motion blur: {rep['motion_blur']}")
    if quality != "final" or arm is None:
        camd.dof.use_dof = False
        return None
    hb = head_bone_of(arm)
    if hb is None:
        return None
    bone = arm.data.bones[hb]
    from mathutils import Matrix
    foc = bpy.data.objects.new("focus_eyes", None)
    _link(foc)
    foc.parent, foc.parent_type, foc.parent_bone = arm, "BONE", hb
    foc.matrix_parent_inverse = Matrix.Identity(4)
    tail_m = bone.matrix_local @ Matrix.Translation((0, bone.length, 0))
    foc.location = tail_m.inverted() @ eye_point_rest(arm)
    kf = int(shot.get("keyFrame", (shot["from"] + shot["to"]) // 2))
    cur = scene.frame_current
    scene.frame_set(kf)
    d = (cam.matrix_world.translation - foc.matrix_world.translation).length
    fov = 2 * math.atan((camd.sensor_height / 2) / max(camd.lens, 1e-3))
    frame_h = 2 * d * math.tan(fov / 2)
    fstop, size = next((f, n) for lim, f, n in FSTOPS if frame_h < lim)
    scene.frame_set(cur)
    camd.dof.use_dof = True
    camd.dof.focus_object = foc
    camd.dof.aperture_fstop = fstop
    camd.dof.aperture_blades = 7
    camd.dof.aperture_rotation = math.radians(12)
    rep["dof"] = {"focus": "eyes", "shot_size": size, "fstop": fstop, "focus_m": round(d, 2), "frame_h_norm": round(frame_h, 2)}
    log(f"dof: {size} f/{fstop} focus {d:.2f} m on the eyes")
    return rep["dof"]
# <<< polish_light


# >>> polish_light: CAN-L1 discovery map + CAN-L2 night face-exposure continuity
# ---- CAN-L1 (Calahan): per sequence, the story detail the viewer should DISCOVER, the shot it is revealed in, and
# the motivated light that reveals it; everything else stays subordinate (the reveal is light-linked to the detail).
#   spec.discovery_map = {"B": [{"detail": "the hull grounded on the reef", "shot": "B11", "reveal": "moon_glint",
#                                "point": [0, 0.4, 2.0], "space": "yacht", "match": "gelcoat_hull",
#                                "motivation": "moon", "at": 740, "ramp": 10, "gain": 1.0}]}
#   (also accepted: a list of entries with "sequence", world.lighting.discovery_map, world.lighting.sequences.<S>.discovery_map)
REVEALS = {
    "raking_practical": "a motivated practical grazing the surface at ~12 deg: texture, dents and scrapes read",
    "practical_pool": "a practical pooling warm light on the detail",
    "moon_glint": "a specular-only moon kick mirrored off the surface toward the lens (wet hull, metal, glass)",
    "moon_pool": "a pool of moonlight through a cloud break on the detail",
    "sun_glint": "a specular-only sun kick (dawn) mirrored off the surface toward the lens",
}
REVEAL_MOTIVATION = {"raking_practical": "practical", "practical_pool": "practical", "moon_glint": "moon",
                     "moon_pool": "moon", "sun_glint": "sun"}
REVEAL_GAIN = {"raking_practical": 0.9, "practical_pool": 0.6, "moon_glint": 1.2, "moon_pool": 0.8, "sun_glint": 1.2}


def discovery_map(spec):
    """{sequence: [entry, ...]} gathered from every accepted place in the spec."""
    out = {}

    def add(seq, e):
        if isinstance(e, dict):
            out.setdefault(str(seq), []).append(dict(e, sequence=str(seq)))

    wl = (spec.get("world") or {}).get("lighting") or {}
    for src in (spec.get("discovery_map"), wl.get("discovery_map")):
        if isinstance(src, dict):
            for seq, lst in src.items():
                for e in lst or []:
                    add(seq, e)
        elif isinstance(src, list):
            for e in src:
                if isinstance(e, dict):
                    add(e.get("sequence") or sequence_of({"id": str(e.get("shot") or "")}), e)
    for seq, L in (wl.get("sequences") or {}).items():
        for e in (L or {}).get("discovery_map") or []:
            add(seq, e)
    return out


def _entry_shots(e):
    if e.get("shots"):
        return [str(x) for x in e["shots"]]
    return [str(e["shot"])] if e.get("shot") else []


def discovery_for_shot(spec, shot):
    return [e for e in discovery_map(spec).get(sequence_of(shot), []) if str(shot.get("id")) in _entry_shots(e)]


def check_discovery(spec):
    """CAN-L1 static check. Returns (status, problems, rows)."""
    shots = spec.get("shots") or []
    by_id = {str(s.get("id")): s for s in shots}
    seqs = []
    for s in shots:
        q = sequence_of(s)
        if q not in seqs:
            seqs.append(q)
    dm = discovery_map(spec)
    problems, rows = [], []
    for q in seqs:
        if not dm.get(q):
            problems.append(f"CAN-L1 sequence {q}: no discovery_map entry (which detail does the light reveal, in which shot?)")
    for q, lst in dm.items():
        if q not in seqs:
            problems.append(f"CAN-L1 discovery_map sequence {q}: no such sequence in the episode")
        for e in lst:
            tag = f"CAN-L1 {q}:{e.get('detail', '?')!s:.40}"
            ids = _entry_shots(e)
            if not e.get("detail"):
                problems.append(f"{tag}: entry has no 'detail' (the story point the viewer discovers)")
            if not ids:
                problems.append(f"{tag}: entry has no 'shot'")
            for sid in ids:
                if sid not in by_id:
                    problems.append(f"{tag}: shot {sid} not in the episode")
                elif sequence_of(by_id[sid]) != q:
                    problems.append(f"{tag}: shot {sid} belongs to sequence {sequence_of(by_id[sid])}, not {q}")
            rv = e.get("reveal")
            if rv not in REVEALS:
                problems.append(f"{tag}: reveal '{rv}' not one of {sorted(REVEALS)}")
            if not (e.get("point") or e.get("match")):
                problems.append(f"{tag}: needs a target ('point' and/or 'match' object/material name)")
            mot = e.get("motivation") or REVEAL_MOTIVATION.get(rv)
            if not mot:
                problems.append(f"{tag}: reveal light is unmotivated (CAN-L2: every light has a source)")
            for sid in ids:
                sh = by_id.get(sid)
                if sh is None:
                    continue
                if e.get("at") is not None and not (sh["from"] <= int(e["at"]) < sh["to"]):
                    problems.append(f"{tag}: 'at' frame {e['at']} outside shot {sid} [{sh['from']}, {sh['to']})")
                cfg = resolve(spec, sh)
                if cfg and rv == "sun_glint" and cfg["family"] == "night" and cfg["dawn"] < 0.3:
                    problems.append(f"{tag}: sun_glint in a night shot ({sid}) is unmotivated")
            rows.append({"sequence": q, "detail": e.get("detail"), "shots": ids, "reveal": rv, "motivation": mot,
                         "target": e.get("match") or e.get("point")})
    return ("FAIL" if problems else "PASS"), problems, rows


def _target_world(scene, shot, e):
    """World point for an entry's spec-space 'point' (yacht-local on yacht shots unless space == 'world'),
    else the bounding-box centre of the matched objects."""
    from mathutils import Vector as V
    objs = _match_objects(scene, e.get("match"))
    if e.get("point") is not None:
        p = _b3(e["point"])
        space = e.get("space") or ("yacht" if shot.get("yacht") else "world")
        yr = scene.objects.get("YachtRoot")
        if space == "yacht" and yr is not None:
            return yr.matrix_world @ p, objs
        return p, objs
    if objs:
        pts = [o.matrix_world @ V(c) for o in objs for c in o.bound_box]
        return sum(pts, V((0, 0, 0))) / len(pts), objs
    return None, objs


def _match_objects(scene, match):
    if not match:
        return []
    keys = [m.strip().lower() for m in str(match).split("|") if m.strip()]
    out = []
    for o in scene.objects:
        if o.type != "MESH" or o.get("lighting_rig"):
            continue
        names = [o.name.lower()] + [s.material.name.lower() for s in o.material_slots if s.material]
        if any(k in n for k in keys for n in names):
            out.append(o)
    return out


def _surface(scene, cam_pos, target, objs):
    """(hit point, normal) on the detail as the lens sees it: ray from the camera to the target; falls back to
    the closest point on the matched meshes, then to a normal facing the camera."""
    dg = bpy.context.evaluated_depsgraph_get()
    d = target - cam_pos
    ok, loc, nor, _i, ob, _m = scene.ray_cast(dg, cam_pos, d.normalized(), distance=d.length + 0.5)
    names = {o.name for o in objs}
    if ok and (not names or ob.name in names) and (loc - target).length < 1.5:
        n = nor.normalized()
        return loc, (n if n.dot(cam_pos - loc) > 0 else -n)
    best = None
    for o in objs:
        inv = o.matrix_world.inverted()
        r = o.closest_point_on_mesh(inv @ target)
        if r[0]:
            p = o.matrix_world @ r[1]
            n = (o.matrix_world.to_3x3().inverted().transposed() @ r[2]).normalized()
            if best is None or (p - target).length < (best[0] - target).length:
                best = (p, n if n.dot(cam_pos - p) > 0 else -n)
    if best:
        return best
    return target, (cam_pos - target).normalized()


def _keyed(v, f, default=0.0):
    """render_episode.keyed: number, or [[f, v], ...] linear between keys, hold outside."""
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    ks = sorted(v, key=lambda k: k[0])
    if f <= ks[0][0]:
        return float(ks[0][1])
    if f >= ks[-1][0]:
        return float(ks[-1][1])
    for (f0, v0), (f1, v1) in zip(ks, ks[1:]):
        if f0 <= f <= f1:
            return float(v0) if f1 == f0 else v0 + (v1 - v0) * (f - f0) / (f1 - f0)
    return float(ks[-1][1])


def _nominal_pose(scene, shot, kf):
    """Put the scene at the shot's keyframe in a CHUNK-INDEPENDENT state: the yacht at its nominal spec pose (its
    keys only cover the frames being rendered) and the camera from the shot's rig function (cam_at) when known.
    Returns (camera matrix_world, vertical fov rad, yacht root or None). Undo with scene.frame_set()."""
    from mathutils import Matrix
    scene.frame_set(kf)
    yr = scene.objects.get("YachtRoot")
    if yr is not None and shot.get("yacht"):
        y = shot["yacht"]
        T = Matrix(((1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))  # spec (Y up) -> Blender
        ym3 = (Matrix.Translation((y["x"], -_keyed(y.get("sink"), kf), y["z"])) @ Matrix.Rotation(y.get("heading", 0.0), 4, "Y")
               @ Matrix.Rotation(-_keyed(y.get("pitch"), kf), 4, "X") @ Matrix.Rotation(_keyed(y.get("roll"), kf), 4, "Z"))
        yr.matrix_world = T @ ym3 @ T.inverted()  # = render_episode's keyed attitude without the buoyancy solve
    bpy.context.view_layer.update()
    cam = scene.camera
    if STATE.get("cam_at") is not None:
        m, fov = STATE["cam_at"](kf)
        return m.copy(), math.radians(fov), yr
    fov = 2 * math.atan((cam.data.sensor_height / 2) / max(cam.data.lens, 1e-3))
    return cam.matrix_world.copy(), fov, yr


def _in_frame(scene, cm, vfov, P):
    pc = cm.inverted() @ P
    if pc.z >= -1e-3:
        return False
    t = math.tan(vfov / 2) * 1.05
    asp = scene.render.resolution_x / max(scene.render.resolution_y, 1)
    return abs(pc.y / -pc.z) <= t and abs(pc.x / -pc.z) <= t * asp


def apply_discovery(scene, shot):
    """Build the reveal light(s) of this shot's discovery-map entries (motivated, light-linked to the detail, faded
    in at entry['at'] over entry['ramp'] frames). Logged in the report as role 'reveal'."""
    spec = STATE.get("spec") or {}
    ents = discovery_for_shot(spec, shot)
    cfg = STATE["cfg"]
    rep = STATE["report"]
    if not ents or scene.camera is None:
        return []
    kf = int(shot.get("keyFrame", (shot["from"] + shot["to"]) // 2))
    cur = scene.frame_current
    cm, _vfov, yr = _nominal_pose(scene, shot, kf)
    cam_pos = cm.translation.copy()
    key_dir = STATE.get("key_dir") or _key_dir_blender(cfg)
    made = []
    for i, e in enumerate(ents):
        rv = e.get("reveal")
        if rv not in REVEALS:
            rep["warnings"].append(f"discovery: unknown reveal {rv}")
            continue
        tgt, objs = _target_world(scene, shot, e)
        if tgt is None:
            rep["warnings"].append(f"discovery: no target for '{e.get('detail')}' ({e.get('match')})")
            continue
        P, N = _surface(scene, cam_pos, tgt, objs)
        gain = float(e.get("gain", REVEAL_GAIN[rv]))
        E_s = gain * cfg["key_energy"]  # irradiance on the detail, x the sequence key: reads, never outshines the hero
        mot = e.get("motivation") or REVEAL_MOTIVATION[rv]
        practical = mot.startswith("practical")
        col = tuple(e.get("color") or (cfg["practical_color"] if practical else
                                        (cfg["key_color"] if rv != "sun_glint" else (1.0, 0.78, 0.6))))
        name = f"reveal_{i}_{rv}"
        if rv in ("moon_glint", "sun_glint"):
            V = (cam_pos - P).normalized()
            R = (2 * N.dot(V) * N - V).normalized()  # mirror direction: the glint points straight down the lens
            d = float(e.get("distance", 2.5))
            ob = _area(name, E_s * math.pi * d * d, float(e.get("size", 0.35)), col, None, tuple(P + R * d))
            ob.rotation_mode = "QUATERNION"
            ob.rotation_quaternion = (-R).to_track_quat("-Z", "Y")
            for attr in ("visible_diffuse", "visible_transmission", "visible_volume_scatter"):
                try:
                    setattr(ob, attr, False)  # specular only: the glint, not a fill
                except AttributeError:
                    pass
        else:
            if rv == "raking_practical":
                T = (cam_pos - P) - N * N.dot(cam_pos - P)  # graze across the surface, from beside the lens side
                if T.length < 1e-4:
                    T = N.orthogonal()
                T = T.normalized()
                side = Vector(e["from"]).normalized() if e.get("from") else None
                a = math.radians(float(e.get("graze_deg", 12.0)))
                d = float(e.get("distance", 1.4))
                L = side if side is not None else (T * math.cos(a) + N * math.sin(a)).normalized()
                cos_i = max(L.dot(N), 0.08)
                cone = math.radians(float(e.get("cone_deg", 34.0)))
            else:  # pools: from the key (moon_pool) or from straight above the detail (practical_pool)
                L = key_dir.normalized() if rv == "moon_pool" else Vector((0.15, 0.1, 1.0)).normalized()
                d = float(e.get("distance", 4.0 if rv == "moon_pool" else 1.6))
                cos_i = max(L.dot(N), 0.2)
                cone = 2 * math.atan(float(e.get("radius", 0.6)) / d)
            ld = bpy.data.lights.new(name, "SPOT")
            ld.color = col
            ld.spot_size = cone
            ld.spot_blend = 0.7
            ld.shadow_soft_size = float(e.get("soft", 0.04 if rv == "raking_practical" else 0.15))
            ld.energy = 4 * math.pi * E_s * d * d / cos_i  # point/spot: I = P / 4pi; E = I cos / d^2
            ob = _link(bpy.data.objects.new(name, ld))
            ob.location = P + L * d
            ob.rotation_mode = "QUATERNION"
            ob.rotation_quaternion = (-L).to_track_quat("-Z", "Y")
        if objs and not e.get("spill", False):  # subordinate: the reveal touches only the detail
            coll = bpy.data.collections.new(f"{name}_recv")
            for o in objs:
                coll.objects.link(o)
            _light_link(ob, coll, shadows=False)
        if e.get("at") is not None:  # the reveal happens when the story wants it
            at, ramp = int(e["at"]), max(int(e.get("ramp", 8)), 1)
            full = ob.data.energy
            keys = [(shot["from"] - 1, 0.0), (at, 0.0), (at + ramp, 1.0)]
            if e.get("until") is not None:  # a brief reveal (a lightning flash, a sweeping torch)
                keys += [(int(e["until"]), 1.0), (int(e["until"]) + ramp, 0.0)]
            for f, k in keys:
                ob.data.energy = full * k
                ob.data.keyframe_insert("energy", frame=f)
            ob.data.energy = full
        if yr is not None and shot.get("yacht") and e.get("space", "yacht") != "world":
            mw = ob.matrix_world.copy()  # ride with the yacht (heave / pitch / roll), like the detail does
            ob.parent = yr
            ob.matrix_parent_inverse = yr.matrix_world.inverted()
            ob.matrix_world = mw
        _tag(ob, mot, "reveal")
        made.append({"detail": e.get("detail"), "reveal": rv, "motivation": mot, "light": ob.name,
                     "target": [round(x, 2) for x in P], "objects": [o.name for o in objs][:6], "E_surface": round(E_s, 3),
                     "at": e.get("at")})
        log(f"discovery: '{e.get('detail')}' <- {rv} ({mot}) on {len(objs)} object(s)")
    scene.frame_set(cur)
    rep["discovery"] = made
    return made


# ---- CAN-L2 (CML 'Filming at night'): the close-up must not feel like daylight next to its wide. A DP's incident
# meter at the hero's eyes, aimed at the lens: sum of every light that reaches the hero (light linking, shadow
# rays) + the sky. Hero-only cheats are trimmed so every hero shot of a sequence lands on one face exposure.
HERO_TRIM_ROLES = ("face_key", "face_fill", "face_wrap")
SHOT_SIZES = ((0.55, "CU"), (1.0, "MCU"), (1.8, "MS"), (3.5, "MLS"), (1e9, "WS"))


def _eye_world(arm):
    from mathutils import Matrix
    hb = head_bone_of(arm)
    if hb is None:
        return None
    bone = arm.data.bones[hb]
    pb = arm.pose.bones[hb]
    tail_m = bone.matrix_local @ Matrix.Translation((0, bone.length, 0))
    local = tail_m.inverted() @ eye_point_rest(arm)
    return arm.matrix_world @ pb.matrix @ Matrix.Translation((0, bone.length, 0)) @ local


def _hero_names(arm):
    base = arm.parent or arm
    return {o.name for o in base.children_recursive} | {base.name}


def _occluded(scene, dg, P, L, dist, hero):
    o = P.copy()
    left = dist
    for _ in range(6):
        ok, loc, _n, _i, ob, _m = scene.ray_cast(dg, o, L, distance=left)
        if not ok:
            return False
        nm = ob.name.lower()
        if ob.name in hero or ob.get("lighting_rig") or "glass" in nm or "haze" in nm or ob.display_type in ("WIRE", "BOUNDS"):
            step = (loc - o).length + 1e-3
            o = loc + L * 1e-3
            left -= step
            if left <= 0:
                return False
            continue
        return True
    return False


def _light_irradiance(scene, dg, ob, P, N, hero):
    ld = ob.data
    if not getattr(ob, "visible_diffuse", True):
        return 0.0
    ll = getattr(ob, "light_linking", None)
    rc = ll.receiver_collection if ll else None
    if rc is not None and not any(o.name in hero for o in rc.all_objects):
        return 0.0
    mw = ob.matrix_world
    if ld.type == "SUN":
        L = (mw.to_3x3() @ Vector((0, 0, 1))).normalized()
        c = N.dot(L)
        e = ld.energy * (max(0.0, 0.5 + 0.5 * c) if ld.angle >= math.radians(90) else max(0.0, c))
        dist = 5000.0
    else:
        v = mw.translation - P
        dist = v.length
        if dist < 1e-4:
            return 0.0
        L = v / dist
        c = N.dot(L)
        if c <= 0:
            return 0.0
        if ld.type == "AREA":
            ne = (mw.to_3x3() @ Vector((0, 0, -1))).normalized()
            I = ld.energy / math.pi * max(0.0, ne.dot(-L))
        else:
            I = ld.energy / (4 * math.pi)
            if ld.type == "SPOT":
                ax = (mw.to_3x3() @ Vector((0, 0, -1))).normalized()
                if math.acos(max(-1.0, min(1.0, ax.dot(-L)))) > ld.spot_size / 2:
                    return 0.0
        e = I * c / (dist * dist)
    if e <= 1e-6:
        return 0.0
    if ld.use_shadow and not (ll is not None and ll.blocker_collection is not None):  # hero-blocked cheats: unshadowed at the eye
        if _occluded(scene, dg, P + N * 0.12, L, dist, hero):
            return 0.0
    return e


def face_meter(scene, shot, normalize=True):
    """Incident face exposure of the hero at the shot's keyframe (stops, incl. view exposure), and - when the
    sequence asks for it - trim the hero-only cheats onto the sequence target. Stored as report['face_meter']."""
    cfg = STATE["cfg"]
    rep = STATE["report"]
    arm = STATE.get("hero_arm")
    cam = scene.camera
    if arm is None or cam is None:
        return None
    kf = int(shot.get("keyFrame", (shot["from"] + shot["to"]) // 2))
    cur = scene.frame_current
    cm, fov, _yr = _nominal_pose(scene, shot, kf)
    dg = bpy.context.evaluated_depsgraph_get()
    P = _eye_world(arm)
    if P is None:
        scene.frame_set(cur)
        return None
    cpos = cm.translation
    N = (cpos - P).normalized()
    hero = _hero_names(arm)
    fwd = (arm.matrix_world.to_3x3() @ Vector((0, -1, 0))).normalized()
    facing = fwd.dot(N)
    in_frame = _in_frame(scene, cm, fov, P)
    d = (cpos - P).length
    frame_h = 2 * d * math.tan(fov / 2)
    size = next(n for lim, n in SHOT_SIZES if frame_h < lim)
    E_amb = math.pi * cfg["hdri_ambient"] * 0.5 * sum(w for _h, w in cfg.get("hdri_mix") or []) if rep.get("hdri") else 0.0
    fixed, trim = E_amb, []
    parts = {"sky": round(E_amb, 4)}
    for ob in scene.objects:
        if ob.type != "LIGHT":
            continue
        e = _light_irradiance(scene, dg, ob, P, N, hero)
        if e <= 0:
            continue
        role = ob.get("lighting_rig")
        parts[ob.name] = round(e, 4)
        if role in HERO_TRIM_ROLES:
            trim.append((ob, e))
        else:
            fixed += e
    E_trim = sum(e for _o, e in trim)
    E0 = fixed + E_trim
    target = cfg["face_target"] * cfg["key_energy"] * 2 ** float(cfg.get("face_ev_offset") or 0.0)
    s = 1.0
    visible = in_frame and facing > -0.2
    normalize = normalize and os.environ.get("LIGHTING_FACE_NORMALIZE", "1") != "0"  # 0: measure only (calibration)
    if normalize and cfg.get("face_normalize") and visible and E_trim > 1e-4:
        s = max(0.3, min(3.0, (target - fixed) / E_trim))
        for ob, _e in trim:
            if not _scale_animated(ob.data, "energy", s):
                ob.data.energy *= s
        for l in rep["lights"]:
            if l["name"] in {o.name for o, _e in trim}:
                l["energy"] = round(l["energy"] * s, 4)
    E = fixed + E_trim * s
    ev = math.log2(max(E, 1e-6)) + scene.view_settings.exposure
    out = {"frame": kf, "shot_size": size, "frame_h_m": round(frame_h, 2), "visible": visible, "facing": round(facing, 2),
           "E_fixed": round(fixed, 4), "E_hero_cheats": round(E_trim, 4), "trim": round(s, 3), "E_face": round(E, 4),
           "E_target": round(target, 4), "face_ev": round(ev, 3),
           "target_ev": round(math.log2(max(target, 1e-6)) + scene.view_settings.exposure, 3),
           "exposure": round(scene.view_settings.exposure, 3), "parts": parts}
    rep["face_meter"] = out
    log(f"face meter: {size} E={E0:.3f}->{E:.3f} (target {target:.3f}, trim x{s:.2f}) face_ev={ev:+.2f}"
        f"{'' if visible else ' (face not visible: not trimmed)'}")
    scene.frame_set(cur)
    return out


def check_face_continuity(spec, reports, tol=None):
    """CAN-L2 measured check from render reports {shot_id: lighting report}. Every close shot (CU/MCU) is compared
    with the nearest wide (WS/MLS/MS) of its sequence (the preceding one, else the following). Returns
    (status, problems, rows). Unmeasured shots are skipped; a shot carrying light_event/cheat_reason may differ."""
    shots = spec.get("shots") or []
    problems, rows = [], []
    seqs = {}
    for s in shots:
        r = (reports.get(str(s["id"])) or {}).get("face_meter")
        if r and r.get("visible"):
            seqs.setdefault(sequence_of(s), []).append((s, r))
    for q, lst in seqs.items():
        wides = [(i, s, r) for i, (s, r) in enumerate(lst) if r["shot_size"] in ("WS", "MLS", "MS")]
        for i, (s, r) in enumerate(lst):
            if r["shot_size"] not in ("CU", "MCU"):
                continue
            prev = [w for w in wides if w[0] < i]
            nxt = [w for w in wides if w[0] > i]
            w = prev[-1] if prev else (nxt[0] if nxt else None)
            if w is None:
                continue
            _wi, ws, wr = w
            cfg = resolve(spec, s) or {}
            t = tol if tol is not None else float(cfg.get("face_ev_tol", 1.0 / 3.0))
            dev = r["face_ev"] - wr["face_ev"]
            wcfg = resolve(spec, ws) or {}
            event = cfg.get("light_event") or cfg.get("cheat_reason") or abs(cfg.get("dawn", 0) - wcfg.get("dawn", 0)) > 0.2
            ok = abs(dev) <= t + 1e-6 or bool(event)
            rows.append({"sequence": q, "close": s["id"], "close_size": r["shot_size"], "wide": ws["id"],
                         "wide_size": wr["shot_size"], "d_ev": round(dev, 3), "ok": ok})
            if not ok:
                problems.append(f"CAN-L2 {s['id']} ({r['shot_size']}) face {dev:+.2f} stops vs wide {ws['id']} "
                                f"({wr['shot_size']}) > {t:.2f}: the close-up reads {'brighter (daylight)' if dev > 0 else 'darker'}")
    if not rows:
        return "MANUAL", ["CAN-L2: no measured wide/close-up pair (render reports without face_meter)"], rows
    return ("FAIL" if problems else "PASS"), problems, rows


def check_face_static(spec):
    """CAN-L2 without renders: continuity holds by construction when every night sequence normalises the face
    exposure and no shot offsets it beyond tolerance without a declared light event / cheat."""
    problems = []
    for s in spec.get("shots") or []:
        cfg = resolve(spec, s)
        if cfg is None:
            continue
        if cfg["family"] == "night" and not cfg.get("face_normalize"):
            problems.append(f"CAN-L2 {s['id']}: face_normalize off on a night shot")
        off = abs(float(cfg.get("face_ev_offset") or 0.0))
        if off > cfg.get("face_ev_tol", 1 / 3) and not (cfg.get("light_event") or cfg.get("cheat_reason")):
            problems.append(f"CAN-L2 {s['id']}: face_ev_offset {off:.2f} stops without light_event/cheat_reason")
        if not cfg.get("key_motivation"):
            problems.append(f"CAN-L2 {s['id']}: key light has no motivation")
    return ("FAIL" if problems else "PASS"), problems


def load_reports(plates):
    """{shot_id: lighting report} from <plates>/<shot>/_render_*.json (latest file per shot)."""
    import glob
    out = {}
    for p in sorted(glob.glob(os.path.join(plates, "*", "_render_*.json")), key=os.path.getmtime):
        try:
            with open(p) as fh:
                m = json.load(fh)
            out[str(m.get("shot"))] = m.get("lighting") or {}
        except (OSError, ValueError):
            continue
    return out


def canon_lighting(spec, plates=None):
    """factory.canon hook: {"CAN-L1": {...}, "CAN-L2": {...}} (status PASS/FAIL/MANUAL + detail)."""
    st1, p1, rows1 = check_discovery(spec)
    res = {"CAN-L1": {"status": st1, "detail": p1 or [f"{r['sequence']}: {r['detail']} <- {r['reveal']} ({r['motivation']}) in {','.join(r['shots'])}" for r in rows1]}}
    st2, p2 = check_face_static(spec)
    _rows, seq_problems = check_sequences(spec)
    p2 = p2 + [p for p in seq_problems if p.startswith("L2")]
    detail = list(p2)
    status = "FAIL" if p2 else st2
    if plates and os.path.isdir(plates):
        stm, pm, rows = check_face_continuity(spec, load_reports(plates))
        detail += pm + [f"{r['close']}({r['close_size']}) vs {r['wide']}({r['wide_size']}): {r['d_ev']:+.2f} stops" for r in rows if r["ok"]]
        if stm == "FAIL":
            status = "FAIL"
    elif status == "PASS":
        detail.append("by construction (face_normalize on every night sequence); pass --plates to measure the renders")
    res["CAN-L2"] = {"status": status, "detail": detail}
    return res
# <<< polish_light CAN-L1/L2


def finalize_shot(scene, shot, centre=(0, 0, 0)):
    """After everything is built: drop the legacy camera-relative fill, warm the practicals, add haze,
    storm flashes, exposure offset, and record the checks in the report."""
    cfg = STATE["cfg"]
    rep = STATE["report"]
    for nm in ("CamFill",):  # legacy operator fill: camera-dependent, breaks sequence continuity
        ob = scene.objects.get(nm)
        if ob is not None:
            bpy.data.objects.remove(ob, do_unlink=True)
            rep.setdefault("removed", []).append(nm)
    if cfg["retint_practicals"]:
        rep["practicals_retinted"] = _retint(scene, cfg)
    rep["practicals_lookdev"] = _practicals(scene, cfg)  # polish_light
    rep["albedo_clamped"] = _albedo_safe(scene)  # polish_light
    rep["look"] = _grade(scene, cfg)  # polish_light: AgX look per sequence family
    cfg["haze_density"] *= float(os.environ.get("LIGHTING_HAZE_SCALE", "1"))  # polish_light: debug/perf knob
    if cfg["haze_density"] > 0:
        _haze(scene, cfg, Vector(centre))
        rep["haze_density"] = cfg["haze_density"]
    key = STATE.get("key")
    if cfg["lightning_per_s"] > 0 and key is not None:
        rep["light_events"] = [f"lightning@{f}" for f in _lightning(cfg, shot, key)]
    if cfg["flicker"] > 0 and key is not None and cfg["key_source"] == "celestial":
        _flicker(key.data, shot, cfg["flicker"])
    scene.view_settings.exposure += cfg["exposure_ev"]
    rep["exposure"] = round(scene.view_settings.exposure, 3)
    rep["discovery"] = apply_discovery(scene, shot)  # polish_light: CAN-L1
    face_meter(scene, shot)  # polish_light: CAN-L2 (after the exposure: the meter reads stops at the lens)
    if not rep.get("checks"):
        _checks(cfg)
    log("rig:", ", ".join(f"{l['role']}={l['energy']}" for l in rep["lights"]),
        "| hdri:", [(h["id"], h["strength"], h["rot_deg"]) for h in rep.get("hdri", [])],
        "| checks:", rep.get("checks"))


# ----------------------------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------------------------
def qa_frame(path):
    """L5 proxy on a rendered (display-referred) plate: share of pixels brighter than middle grey."""
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(path).convert("RGB"), np.float32) / 255.0
    lin = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    lum = lin @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    return {"frame": path, "above_0.18": round(float((lum > 0.18).mean()), 4), "mean_lum": round(float(lum.mean()), 4),
            "p99": round(float(np.percentile(lum, 99)), 4)}


def _main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--list":
        for k in sorted(PRESETS):
            p = dict(BASE)
            p.update(PRESETS[k])
            print(f"{k:24s} family={p['family']:10s} key={p['key_source']:9s} E={p['key_energy']:<5} key:fill={p['fill_ratio']:<5} "
                  f"rim={p['rim_energy']:<4} hdri={p['hdri']} haze={p['haze_density']} ev={p['exposure_ev']}")
        return 0
    if argv[0] == "--check":
        with open(argv[1]) as fh:
            spec = json.load(fh)
        rows, problems = check_sequences(spec)
        for r in rows:
            print(json.dumps(r))
        print(f"{len(problems)} problem(s)")
        for p in problems:
            print("  -", p)
        return 1 if problems else 0
    if argv[0] == "--qa":
        for p in argv[1:]:
            print(json.dumps(qa_frame(p)))
        return 0
    print("unknown command; see --help")
    return 2


if __name__ == "__main__" and bpy is None:
    sys.exit(_main(sys.argv[1:]))
