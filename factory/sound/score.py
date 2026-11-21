"""Real-music score: stitch generated / licensed stems onto the sound.json energy map, beat-aligned.

sound.json `music` with engine "stems":
    {"engine": "stems", "manifest": "factory/sound/music_manifest.json", "bpm": 110, "sections": [...]}
music_manifest.json lists stems with a `role` (tension | dark | resolve); each section picks its stem from its mood
(dark -> dark, resolve -> resolve, else tension; falls back to tension).

Planning (per section with energy > 0), source offset chosen by score:
  - hit sections start on a source downbeat (or the strongest beat), so the musical accent lands on the reveal frame;
  - non-hit sections continue the previous section's stem seamlessly when it is the same stem (no splice);
  - every candidate offset is scored on (a) accent at the section start (hits), (b) onset strength at the times the
    section's impacts / whooshes / risers land (picture-locked SFX are fixed, so the music is moved under them),
    (c) loudness match to the section's energy level, (d) a penalty for re-using source audio heard recently.
Render:
  - splices are equal-power crossfades that END on the section boundary (the incoming stem pre-rolls the tail of
    the bar before its downbeat), so the downbeat on the hit frame plays at full level;
  - per-section gain trims follow the energy ladder (smoothed 250 ms ramps inside a continuous segment);
  - energy 0 sections are silent (hard cut, 2 ms de-click), the episode ends with a hard stop at durationFrames;
  - when a section is longer than the usable stem, the stem is extended with bar-aligned loops.
Alignment report: for every impact / whoosh / riser end, distance to the nearest output beat and the accent there,
for the chosen plan and for a naive plan (stems laid back to back from 0) as a baseline.

CLI:
  python3 -m factory.sound.score analyse                       # tempo / beats of every stem in the manifest
  python3 -m factory.sound.score apply --sound episodes/sentinel/sound.json --out episodes/sentinel/sound_v2.json
  python3 -m factory.sound.score render --sound episodes/sentinel/sound_v2.json --out /tmp/score.wav
  python3 -m factory.sound.score register                      # catalog entries for the stems
"""
import argparse, copy, hashlib, json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
STORE = os.environ.get("LIBRARY_STORE", os.path.join(ROOT, "library_store"))
MANIFEST = os.path.join(HERE, "music_manifest.json")
sys.path.insert(0, HERE)
import beats as B  # noqa: E402

SR = 48000
ROLE_OF_MOOD = {"dark": "dark", "resolve": "resolve", "tense": "tension"}
# target RMS (dBFS, 1 s windows) by energy level; the mixer re-levels the whole bus, so only the ladder matters
ENERGY_DB = {1: -26.0, 2: -23.0, 3: -20.0, 4: -17.0, 5: -15.0}
MAX_TRIM_DB = 8.0
XFADE_S = 0.06          # each side of a splice: incoming pre-roll / outgoing fade, ending on the boundary
RAMP_S = 0.25           # gain-trim ramp inside a continuous segment
DECLICK_S = 0.002
CUE_TYPES = ("impact", "whoosh", "riser")


# ----------------------------------------------------------------------------------------------- stems
class Stem:
    def __init__(self, name, x, sr=SR, role="tension", prior_bpm=None, meta=None):
        self.name, self.x, self.sr, self.role, self.meta = name, np.asarray(x, np.float32), sr, role, meta or {}
        a = B.analyse(self.x, sr, prior_bpm)
        self.bpm, self.beats, self.downbeats = a["bpm"], a["beats"], a["downbeats"]
        self.env, self.env_rate, self.loud, self.loud_rate = a["env"], a["env_rate"], a["loud"], a["loud_rate"]
        self.ibi_jitter = a["ibi_jitter"]
        self.dur = len(self.x) / sr
        # usable end: after the last window within 12 dB of the median loudness (drops a generated fade-out tail)
        live = np.nonzero(self.loud > np.median(self.loud) - 12.0)[0]
        self.usable_end = min(self.dur, (live[-1] + 1) / self.loud_rate + 1.0) if len(live) else self.dur

    def window_db(self, t0, length):
        a = int(t0 * self.loud_rate)
        b = max(a + 1, int((t0 + length) * self.loud_rate) - 3)    # loud[i] covers [i*hop, i*hop + 1 s]
        seg = self.loud[a:min(b, len(self.loud))]
        return float(10 * np.log10(np.mean(10 ** (seg / 10)))) if len(seg) else float(self.loud[-1])

    def accent(self, t):
        return B.accent(self.env, self.env_rate, t)

    def summary(self):
        return {"bpm": round(self.bpm, 2), "beats": len(self.beats), "dur": round(self.dur, 3),
                "usable_end": round(self.usable_end, 3), "ibi_jitter": round(self.ibi_jitter, 4),
                "first_downbeat": round(float(self.downbeats[0]), 3) if len(self.downbeats) else None}


def extend_with_loops(stem, need_s, xf=0.05):
    """Return audio of at least need_s seconds: the stem up to its usable end, then bar-aligned loops of the
    region [downbeat 1, last usable downbeat) joined with short equal-power crossfades."""
    sr = stem.sr
    x = stem.x[:int(stem.usable_end * sr)]
    if len(x) / sr >= need_s:
        return x
    dbs = stem.downbeats[stem.downbeats < stem.usable_end - 0.1]
    if len(dbs) >= 3:
        a, b = dbs[1], dbs[-1]
    else:
        a, b = 0.0, stem.usable_end
    loop = stem.x[int(a * sr):int(b * sr)]
    n = int(xf * sr)
    th = np.linspace(0, np.pi / 2, n)[:, None]
    out = x[:int(b * sr)].copy()
    while len(out) / sr < need_s:
        head = loop[:n] * np.sin(th)
        out[-n:] = out[-n:] * np.cos(th) + head
        out = np.concatenate([out, loop[n:]])
    return out


# ----------------------------------------------------------------------------------------------- planning
def stem_for(section, stems):
    role = ROLE_OF_MOOD.get(section.get("mood", "tense"), "tension")
    by_role = {s.role: s for s in stems.values()}
    return by_role.get(role) or by_role.get("tension") or next(iter(stems.values()))


def cue_times(cues, fps, a_s, b_s):
    return [c["at"] / fps for c in cues if c.get("type") in CUE_TYPES and a_s <= c["at"] / fps < b_s]


def _dedupe(ts, tol=1e-4):
    out = []
    for t in sorted(ts):
        if not out or t - out[-1] > tol:
            out.append(t)
    return out


def split_on_whooshes(sections, cues, fps, min_len_s=3.0):
    """Music-editor trick: a whoosh on a picture cut masks a music edit, so a long section may be re-spliced at a
    whoosh to put a beat under it. Splits each section at whoosh cues that leave >= min_len_s on both sides; the
    new sub-sections are 'soft hits' (beat-aligned start preferred, seamless continuation still allowed)."""
    out = []
    wh = sorted(c["at"] for c in cues if c.get("type") == "whoosh")
    m = int(round(min_len_s * fps))
    for s in sections:
        if int(s.get("energy", 0)) <= 0:
            out.append(s)
            continue
        cur = dict(s)
        for f in wh:
            if cur["from"] + m <= f <= s["to"] - m:
                a = dict(cur, to=f)
                out.append(a)
                cur = dict(s, id=f"{s['id']}@{f}", **{"from": f}, hit=False, soft_hit=True)
        out.append(cur)
    return out


def plan(sections, fps, stems, cues=(), naive=False, weights=None):
    """Returns a list of placements {section, stem, dst_start, dst_end, src_start, gain_db, splice, score}."""
    w = {"start": 2.0, "cues": 1.0, "energy": 1.0, "reuse": 1.5, "continue": 1.2}
    w.update(weights or {})
    out, used = [], {}
    prev = None
    naive_pos = {}
    for s in sections:
        e = int(s.get("energy", 0))
        a_s, b_s = s["from"] / fps, s["to"] / fps
        L = b_s - a_s
        if e <= 0 or L <= 0:
            out.append({"section": s["id"], "stem": None, "dst_start": a_s, "dst_end": b_s, "energy": e})
            prev = None
            continue
        st = stem_for(s, stems)
        target = ENERGY_DB.get(e, ENERGY_DB[5] if e > 5 else ENERGY_DB[1])
        if naive:
            o = naive_pos.get(st.name, 0.0)
            naive_pos[st.name] = o + L
            out.append({"section": s["id"], "stem": st.name, "dst_start": a_s, "dst_end": b_s, "src_start": o,
                        "gain_db": 0.0, "splice": True, "energy": e})
            prev = out[-1]
            continue
        cont = None
        if prev is not None and prev["stem"] == st.name and abs(prev["dst_end"] - a_s) < 1e-6:
            cont = prev["src_start"] + (prev["dst_end"] - prev["dst_start"])
        limit = st.usable_end - L
        hit = s.get("hit") or s.get("soft_hit")
        if s.get("hit"):
            cands = list(st.downbeats) + list(st.beats)
        elif s.get("soft_hit"):
            cands = list(st.beats) + ([cont] if cont is not None else [])
        else:
            cands = list(st.beats) + ([cont] if cont is not None else [])
        cands = _dedupe([float(c) for c in cands if 0.0 <= c <= max(0.0, limit)])
        if not cands:
            # longer than the usable stem: start at the first downbeat and loop (extend_with_loops at render)
            cands = [float(st.downbeats[0]) if len(st.downbeats) else 0.0]
        ct = cue_times(cues, fps, a_s, b_s)
        best = None
        for o in cands:
            sc = 0.0
            if hit:
                sc += w["start"] * float(st.accent(o)[0])
                if len(st.downbeats) and np.min(np.abs(st.downbeats - o)) < 0.02:
                    sc += 0.5 * w["start"]
            if ct:
                sc += w["cues"] * float(np.mean(st.accent([o + (t - a_s) for t in ct])))
            if o + L <= st.usable_end:
                sc -= w["energy"] * abs(st.window_db(o, L) - target) / 6.0
            for (u0, u1) in used.get(st.name, []):
                ov = max(0.0, min(u1, o + L) - max(u0, o))
                sc -= w["reuse"] * ov / L
            if cont is not None and abs(o - cont) < 1e-3:
                sc += w["continue"]
            if best is None or sc > best[0]:
                best = (sc, o)
        sc, o = best
        splice = not (cont is not None and abs(o - cont) < 1e-3)
        if not splice:
            o = cont                       # exact continuation (candidates are de-duplicated to 0.1 ms)
        lvl = st.window_db(o, min(L, max(0.5, st.usable_end - o)))
        gain = float(np.clip(target - lvl, -MAX_TRIM_DB, MAX_TRIM_DB))
        used.setdefault(st.name, []).append((o, o + L))
        out.append({"section": s["id"], "stem": st.name, "dst_start": a_s, "dst_end": b_s, "src_start": float(o),
                    "gain_db": gain, "splice": splice, "energy": e, "score": round(float(sc), 3)})
        prev = out[-1]
    return out


def segments(placements):
    """Merge consecutive placements that continue the same stem without a splice."""
    segs = []
    for p in placements:
        if p["stem"] is None:
            segs.append({"stem": None, "dst_start": p["dst_start"], "dst_end": p["dst_end"], "parts": [p]})
            continue
        if segs and not p["splice"] and segs[-1]["stem"] == p["stem"]:
            segs[-1]["dst_end"] = p["dst_end"]
            segs[-1]["parts"].append(p)
        else:
            segs.append({"stem": p["stem"], "dst_start": p["dst_start"], "dst_end": p["dst_end"],
                         "src_start": p["src_start"], "parts": [p]})
    return segs


# ----------------------------------------------------------------------------------------------- render
def render(placements, stems, total_s, sr=SR, xfade=XFADE_S):
    n = int(round(total_s * sr))
    out = np.zeros((n, 2), np.float32)
    segs = segments(placements)
    xn, dn = int(xfade * sr), max(1, int(DECLICK_S * sr))
    for i, sg in enumerate(segs):
        if sg["stem"] is None:
            continue
        st = stems[sg["stem"]]
        prev_live = i > 0 and segs[i - 1]["stem"] is not None
        next_live = i + 1 < len(segs) and segs[i + 1]["stem"] is not None
        d0, d1 = int(round(sg["dst_start"] * sr)), min(n, int(round(sg["dst_end"] * sr)))
        s0 = int(round(sg["src_start"] * sr))
        pre = min(xn, d0, s0) if prev_live else 0
        L = d1 - d0
        src = extend_with_loops(st, (s0 + L) / sr + 0.01)
        if src.ndim == 1:
            src = np.stack([src, src], axis=1)
        chunk = src[s0 - pre:s0 + L].astype(np.float32).copy()
        if len(chunk) < pre + L:
            chunk = np.pad(chunk, ((0, pre + L - len(chunk)), (0, 0)))
        # gain curve: per part trims, linear-in-dB ramps of RAMP_S centred on internal part boundaries
        tt = (np.arange(len(chunk)) - pre) / sr + sg["dst_start"]
        g_db = np.full(len(chunk), sg["parts"][0]["gain_db"])
        for p in sg["parts"][1:]:
            r = np.clip((tt - (p["dst_start"] - RAMP_S / 2)) / RAMP_S, 0, 1)
            g_db = g_db + r * (p["gain_db"] - g_db)
        chunk *= (10 ** (g_db / 20)).astype(np.float32)[:, None]
        if pre > 0:
            chunk[:pre] *= np.sin(np.linspace(0, np.pi / 2, pre))[:, None]
        else:
            m = min(dn, len(chunk))
            chunk[:m] *= np.linspace(0, 1, m)[:, None]
        if next_live and segs[i + 1].get("src_start", 0) * sr >= 1:
            # outgoing fade ends on the boundary, overlapping the next segment's pre-roll
            nx = segs[i + 1]
            npre = min(xn, int(round(nx["dst_start"] * sr)), int(round(nx["src_start"] * sr)))
            if npre > 0:
                chunk[-npre:] *= np.cos(np.linspace(0, np.pi / 2, npre))[:, None]
        else:
            m = min(dn, len(chunk))
            chunk[-m:] *= np.linspace(1, 0, m)[:, None]   # hard stop / hard cut into silence
        a = d0 - pre
        out[a:a + len(chunk)] += chunk[:n - a]
    return out


def output_beats(placements, stems):
    """Beat times (s, episode clock) of the rendered score, with the source accent at each."""
    bt, ac = [], []
    for p in placements:
        if p["stem"] is None:
            continue
        st = stems[p["stem"]]
        L = p["dst_end"] - p["dst_start"]
        sb = st.beats[(st.beats >= p["src_start"] - 1e-3) & (st.beats < p["src_start"] + L - 1e-3)]
        bt += list(sb - p["src_start"] + p["dst_start"])
        ac += list(st.accent(sb))
    return np.array(bt), np.array(ac)


def alignment(placements, stems, cues, fps, sfx_info=None):
    """Per cue: nearest output beat distance (ms) and music accent at the cue's landing time."""
    rows = []
    bt, _ = output_beats(placements, stems)
    for c in cues:
        if c.get("type") not in CUE_TYPES:
            continue
        t = c["at"] / fps
        p = next((p for p in placements if p["dst_start"] <= t < p["dst_end"]), None)
        if p is None or p["stem"] is None:
            continue
        st = stems[p["stem"]]
        acc = float(st.accent(p["src_start"] + t - p["dst_start"])[0])
        d = float(np.min(np.abs(bt - t))) * 1000 if len(bt) else float("nan")
        rows.append({"id": c["id"], "type": c["type"], "t": round(t, 3), "beat_dist_ms": round(d, 1), "accent": round(acc, 3)})
    return rows


def summarise(rows, tol_ms=50.0):
    if not rows:
        return {"n": 0}
    d = np.array([r["beat_dist_ms"] for r in rows])
    a = np.array([r["accent"] for r in rows])
    out = {"n": len(rows), "on_beat_frac": round(float(np.mean(d <= tol_ms)), 3), "median_beat_dist_ms": round(float(np.median(d)), 1),
           "mean_accent": round(float(a.mean()), 3)}
    for typ in CUE_TYPES:
        sel = [r for r in rows if r["type"] == typ]
        if sel:
            dd = np.array([r["beat_dist_ms"] for r in sel])
            out[typ] = {"n": len(sel), "on_beat_frac": round(float(np.mean(dd <= tol_ms)), 3),
                        "mean_accent": round(float(np.mean([r["accent"] for r in sel])), 3)}
    return out


# ----------------------------------------------------------------------------------------------- manifest glue
def manifest(path=MANIFEST):
    return json.load(open(path))


def load_stems(man, store=STORE, decode=None):
    if decode is None:
        from audio_util import decode
    stems = {}
    for name, e in man["stems"].items():
        p = os.path.join(store, e["file"])
        if not os.path.exists(p):
            raise FileNotFoundError(f"music stem {name}: {p} (see {MANIFEST})")
        stems[name] = Stem(name, decode(p), SR, e["role"], prior_bpm=e.get("bpm"), meta=e)
    return stems


def render_music(music, fps, duration_frames, cues=(), root=ROOT, store=STORE):
    """Mixer entry point for engine 'stems'. Returns (audio (n, 2) float32, report dict)."""
    man = manifest(os.path.join(root, music.get("manifest", os.path.relpath(MANIFEST, ROOT))))
    stems = load_stems(man, store)
    total = duration_frames / fps
    secs = split_on_whooshes(music["sections"], cues, fps, music.get("whooshSpliceMinS", 3.0)) \
        if music.get("whooshSplices", True) else music["sections"]
    pl = plan(secs, fps, stems, cues)
    x = render(pl, stems, total)
    naive = plan(music["sections"], fps, stems, cues, naive=True)
    rows = alignment(pl, stems, cues, fps)
    rep = {"engine": "stems", "manifest": music.get("manifest"), "stems": {k: s.summary() for k, s in stems.items()},
           "placements": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in p.items()} for p in pl],
           "splices": sum(1 for p in pl if p.get("splice") and p["stem"]),
           "alignment": summarise(rows), "alignment_naive": summarise(alignment(naive, stems, cues, fps)),
           "cues": rows}
    return x, rep


def apply(sound, manifest_rel="factory/sound/music_manifest.json"):
    """sound.json dict -> copy whose music bus uses the stems engine (sections untouched)."""
    s = copy.deepcopy(sound)
    man = manifest(os.path.join(ROOT, manifest_rel))
    s["music"]["engine"] = "stems"
    s["music"]["manifest"] = manifest_rel
    s["music"]["bpm"] = man.get("bpm", s["music"].get("bpm"))
    s["music"]["key"] = man.get("key", s["music"].get("key"))
    return s


def _sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def register_all():
    sys.path.insert(0, os.path.join(ROOT, "factory", "library", "sources"))
    from common import register
    m = manifest()
    n = 0
    for name, e in m["stems"].items():
        p = os.path.join(STORE, e["file"])
        if not os.path.exists(p):
            print("skip (not downloaded):", name)
            continue
        register({
            "id": f"el:music_{name}", "kind": "music", "provider": m["provider"], "source_id": e["generation"],
            "name": name.replace("_", " "), "licence": m["licence"], "authors": ["ElevenLabs " + m["model"] + " (generated)"],
            "url": None,
            "provenance": {"model": m["model"], "flow_id": m["flow_id"], "node_id": e["node"], "session_id": e["session"],
                           "generation_id": e["generation"], "prompt": e["prompt"], "duration_s": e["duration_s"],
                           "instrumental": True, "credits": e.get("credits"), "generated": m["generated"]},
            "files": [{"path": e["file"], "sha256": _sha256(p), "role": "audio"}],
            "tags": list(dict.fromkeys(e["tags"] + ["music", e["role"]])), "episodes": ["sentinel"],
            "music": {"role": e["role"], "bpm_nominal": e["bpm"], "bpm_measured": e.get("bpm_measured"), "key": m.get("key"),
                      "mood": [{"tension": "tense"}.get(e["role"], e["role"])], "duration_s": e["duration_s"]},
            "build": "factory/sound/music_manifest.json",
        })
        n += 1
    print("registered", n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["analyse", "apply", "render", "register"])
    ap.add_argument("--sound")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.cmd == "analyse":
        for k, s in load_stems(manifest()).items():
            print(k, s.role, json.dumps(s.summary()))
    elif a.cmd == "apply":
        s = apply(json.load(open(a.sound)))
        with open(a.out, "w") as fh:
            json.dump(s, fh, indent=1)
        print("wrote", a.out)
    elif a.cmd == "render":
        from audio_util import write_wav
        snd = json.load(open(a.sound))
        x, rep = render_music(snd["music"], snd["fps"], snd["durationFrames"], snd["cues"])
        write_wav(a.out, x)
        print(json.dumps({k: rep[k] for k in ("stems", "splices", "alignment", "alignment_naive")}, indent=1))
    else:
        register_all()


if __name__ == "__main__":
    main()
