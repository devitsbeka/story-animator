"""SFX library for the sound stage.

resolve(name) returns a playable file for an SFX name:
  1. $LIBRARY_STORE/sfx/<name>.mp3 (ElevenLabs generations, see sfx_manifest.json), else
  2. a procedural placeholder synthesised with ffmpeg noise/tone filters into $LIBRARY_STORE/sfx/_proc/<name>.wav,
so the mixer always runs end to end, even on a machine without the generated files.

CLI:
  python3 -m factory.sound.sfx_library list              # what resolves where
  python3 -m factory.sound.sfx_library synth [--force]   # build every procedural placeholder
  python3 -m factory.sound.sfx_library register          # add the ElevenLabs SFX to factory/library/catalog.json
"""
import argparse, hashlib, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
STORE = os.environ.get("LIBRARY_STORE", os.path.join(ROOT, "library_store"))
SFX_DIR = os.path.join(STORE, "sfx")
PROC_DIR = os.path.join(SFX_DIR, "_proc")
MANIFEST = os.path.join(HERE, "sfx_manifest.json")

sys.path.insert(0, HERE)
from audio_util import FFMPEG, run, decode, analyse, ebur128, SR  # noqa: E402


def manifest():
    return json.load(open(MANIFEST))


def kind_of(name):
    m = manifest()
    e = m["sfx"].get(name) or m["procedural"].get(name)
    if not e:
        raise KeyError(f"unknown sfx {name!r}")
    return e["kind"]


# Procedural placeholders: ffmpeg lavfi sources + filters. Each yields 48 kHz stereo.
# They are deliberately simple (filtered noise, tones, envelopes) - stand-ins, not final sound design.
PROC = {
    "ocean_waves":   ("anoisesrc=c=brown:a=0.5:d=20", "lowpass=f=900,volume='0.55+0.45*sin(2*PI*t/5.5)':eval=frame,highpass=f=40"),
    "wind_sea":      ("anoisesrc=c=pink:a=0.35:d=20", "bandpass=f=500:width_type=h:w=400,volume='0.7+0.3*sin(2*PI*t/7.3)':eval=frame"),
    "jungle_night":  ("aevalsrc='0.25*sin(2*PI*4300*t)*(0.5+0.5*sin(2*PI*38*t))*gt(sin(2*PI*1.7*t),0)+0.15*sin(2*PI*5200*t)*(0.5+0.5*sin(2*PI*45*t))':d=15:s=48000", "highpass=f=2500"),
    "fire_crackle":  ("anoisesrc=c=white:a=0.6:d=10", "volume='if(lt(random(0),0.004),1,0.06)':eval=frame,highpass=f=1500,lowpass=f=9000"),
    "rain_storm":    ("anoisesrc=c=white:a=0.4:d=15", "lowpass=f=6000,highpass=f=300"),
    "helicopter":    ("anoisesrc=c=brown:a=0.8:d=6", "lowpass=f=400,volume='0.25+0.75*pow(abs(sin(2*PI*5.5*t)),6)':eval=frame"),
    "radio_static":  ("anoisesrc=c=white:a=0.5:d=2.5", "bandpass=f=1800:width_type=h:w=1500,afade=t=in:d=0.01,afade=t=out:st=2.45:d=0.05"),
    "coral_crunch":  ("anoisesrc=c=brown:a=1:d=2.5", "lowpass=f=1600,afade=t=out:st=0.02:d=1.4:curve=exp"),
    "engine_die":    ("aevalsrc='0.6*sin(2*PI*(38-10*t)*t)*(0.5+0.5*sin(2*PI*9*t))*exp(-0.9*t)':d=3:s=48000", "lowpass=f=900"),
    "beacon_beep":   ("aevalsrc='0.6*sin(2*PI*3150*t)*lt(t,0.18)':d=0.3:s=48000", "afade=t=in:d=0.003,afade=t=out:st=0.17:d=0.01"),
    "thunder":       ("anoisesrc=c=brown:a=1:d=4", "lowpass=f=700,afade=t=in:d=0.02,afade=t=out:st=0.2:d=3.6:curve=exp"),
    "impact_boom":   ("aevalsrc='0.9*sin(2*PI*(55*t-15*t*t))*exp(-3.5*t)':d=2:s=48000", "lowpass=f=300"),
    "whoosh_fast":   ("anoisesrc=c=pink:a=0.8:d=0.5", "bandpass=f=2500:width_type=h:w=2000,afade=t=in:d=0.2:curve=qsin,afade=t=out:st=0.2:d=0.3:curve=qsin"),
    "whoosh_low":    ("anoisesrc=c=brown:a=0.9:d=0.7", "lowpass=f=500,afade=t=in:d=0.35:curve=qsin,afade=t=out:st=0.35:d=0.35:curve=qsin"),
    "whoosh_whip":   ("anoisesrc=c=white:a=0.8:d=0.3", "bandpass=f=4000:width_type=h:w=3000,afade=t=in:d=0.08,afade=t=out:st=0.08:d=0.22"),
    "riser_noise":   ("anoisesrc=c=pink:a=0.6:d=2.5", "highpass=f=800,afade=t=in:d=2.45:curve=exp"),
    "riser_reverse": ("aevalsrc='0.5*sin(2*PI*(200*t+220*t*t))':d=2:s=48000", "afade=t=in:d=1.98:curve=exp"),
    "switch_click":  ("aevalsrc='0.9*sin(2*PI*2400*t)*exp(-180*t)+0.5*sin(2*PI*900*t)*exp(-120*(t-0.012))*gte(t,0.012)':d=0.12:s=48000", "highpass=f=300"),
    "ui_tick":       ("aevalsrc='0.7*sin(2*PI*1800*t)*exp(-90*t)':d=0.08:s=48000", "highpass=f=600"),
}


def synth(name, force=False):
    if name not in PROC:
        raise KeyError(f"no procedural recipe for {name!r}")
    out = os.path.join(PROC_DIR, name + ".wav")
    if os.path.exists(out) and not force:
        return out
    os.makedirs(PROC_DIR, exist_ok=True)
    src, filt = PROC[name]
    run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", src, "-af", filt + ",aformat=sample_rates=48000:channel_layouts=stereo",
         "-c:a", "pcm_s16le", out])
    return out


def resolve(name, allow_proc=True):
    """Return (path, source) where source is 'elevenlabs' or 'procedural'."""
    p = os.path.join(SFX_DIR, name + ".mp3")
    if os.path.exists(p) and os.path.getsize(p) > 0:
        return p, "elevenlabs"
    if not allow_proc:
        raise FileNotFoundError(p)
    return synth(name), "procedural"


_ANALYSIS = {}


def info(name):
    """Timing + loudness landmarks used to place and level a cue."""
    path, source = resolve(name)
    key = (path, os.path.getmtime(path))
    if key in _ANALYSIS:
        return _ANALYSIS[key]
    x = decode(path)
    a = analyse(x)
    m = ebur128(path, pre_filter="apad=pad_dur=0.5")   # pad so sub-400 ms one-shots get a momentary value
    if not (m["M_max"] > -100 and m["I"] > -100):
        raise ValueError(f"{name}: unmeasurable loudness ({m['M_max']}, {m['I']}) in {path}")
    a.update({"path": path, "source": source, "kind": kind_of(name), "I": m["I"], "M_max": m["M_max"]})
    _ANALYSIS[key] = a
    return a


def _sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def register_all():
    sys.path.insert(0, os.path.join(ROOT, "factory", "library", "sources"))
    from common import register  # shared catalog writer (sorted keys, provenance fields)
    m = manifest()
    n = 0
    for name, e in m["sfx"].items():
        p = os.path.join(SFX_DIR, name + ".mp3")
        if not os.path.exists(p):
            print("skip (not downloaded):", name)
            continue
        register({
            "id": f"el:sfx_{name}", "kind": "sfx", "provider": "elevenlabs", "source_id": e["generation"],
            "name": name.replace("_", " "), "licence": m["licence"], "authors": ["ElevenLabs " + m["model"] + " (generated)"],
            "url": None,
            "provenance": {"model": m["model"], "flow_id": m["flow_id"], "node_id": e["node"], "generation_id": e["generation"],
                           "prompt": e["prompt"], "duration_s": e["duration_s"], "loop": e["loop"], "generated": m["generated"]},
            "files": [{"path": os.path.relpath(p, STORE), "sha256": _sha256(p), "role": "audio"}],
            "tags": e["tags"] + [e["kind"]], "episodes": ["sentinel"],
            "build": "factory/sound/sfx_manifest.json",
        })
        n += 1
    print("registered", n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "synth", "register"])
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    names = list(manifest()["sfx"]) + list(manifest()["procedural"])
    if a.cmd == "list":
        for n in names:
            p, s = resolve(n)
            print(f"{n:15s} {s:11s} {p}")
    elif a.cmd == "synth":
        for n in PROC:
            print(n, synth(n, force=a.force))
    else:
        register_all()


if __name__ == "__main__":
    main()
