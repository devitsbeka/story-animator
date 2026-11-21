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
}

DAWN = {"family": "dawn", "key_energy": 2.2, "key_color": (1.0, 0.70, 0.52), "fill_ratio": 3.0,
        "fill_color": (0.55, 0.55, 0.75), "rim_energy": 0.9, "rim_color": (1.0, 0.78, 0.62),
        "hdri": "ph:kloppenheim_02_puresky", "hdri_ambient": 0.11, "hdri_saturation": 0.7,
        "hdri_tint": (1.0, 0.86, 0.80), "exposure_ev": -0.3, "shadow_softness": 2.5,
        "key_motivation": "sun", "rim_motivation": "sun", "retint_practicals": False}

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
    "moonlight": _p(),
    "moonlight_practical_mix": _p(fill_ratio=6.5),
    "low_key_portrait": _p(fill_ratio=10.0, rim_energy=1.3),
    "rim_silhouette": _p(fill_ratio=14.0, rim_energy=2.2, key_energy=1.2, eye_light=False),
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
          "hdri_saturation", "hdri_tint", "exposure_ev", "shadow_softness")

DEFAULT_PRESET = "moonlight_practical_mix"
LEGACY = ("legacy", "off", "none")


# ----------------------------------------------------------------------------------------------
# pure-python resolution
# ----------------------------------------------------------------------------------------------
def sequence_of(shot):
    if shot.get("sequence"):
        return str(shot["sequence"])
    sid = str(shot.get("id", ""))
    lead = "".join(ch for ch in sid if ch.isalpha())
    return lead or sid


def _lerp(a, b, t):
    if isinstance(a, (tuple, list)):
        return tuple(x + (y - x) * t for x, y in zip(a, b))
    return a + (b - a) * t


def shot_env(spec, shot):
    env = dict(spec.get("world") or {})
    env.update(shot.get("env") or {})
    return env


def resolve(spec, shot, override=None):
    """Merged lighting config for one shot (dict), or None for the legacy rig."""
    env = shot_env(spec, shot)
    wl = dict((spec.get("world") or {}).get("lighting") or {})
    seq = sequence_of(shot)
    layers = [wl, dict((wl.get("sequences") or {}).get(seq) or {}),
              dict((shot.get("env") or {}).get("lighting") or {}), dict(shot.get("lighting") or {})]
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


def build_hero_rig(idx, holder, arm, actor, camera, shot):
    """Hero lights for the sequence rig: world-direction face fill, camera-aware rim cheat, eye light.
    Replaces the legacy hero-parented 'GAFFER moonlight portrait' lights."""
    cfg = STATE["cfg"]
    key_dir = STATE.get("key_dir") or _key_dir_blender(cfg)
    head_bone = next((b.name for b in arm.data.bones if b.name.lower() in ("head", "mixamorig:head")), None)
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
    head_w = fol.matrix_world.translation if head_bone is None else (arm.matrix_world @ arm.data.bones[head_bone].head_local)
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
    # --- eye light (spec only), only when the camera is close (MCU or tighter)
    cam_dist = (cam_mean - head_w).length
    if cfg["eye_light"] and cam_dist < 3.0:
        e = _area(f"hero_eyelight_{idx}", 1.0, 0.25, (1.0, 1.0, 1.0), camera, (0.12, 0.08, 0.0))
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
