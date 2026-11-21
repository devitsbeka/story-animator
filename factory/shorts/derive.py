"""Derive vertical shorts from a finished long-form docuseries episode (factory/ARCHITECTURE.md, "Deriving shorts
from long-form").

For each short_candidate beat (episode.json `shorts`, compiled by factory/director from story.json chapters):
  1. pick:     candidates whose beat is fully covered by dual-frame shots (cameras.vertical), ranked by intensity;
  2. hook:     a new 1-3 s cold open, re-cut from the beat's climax line (picture + VO), or a VO pickup of the
               candidate's hook line in the same voice when factory.voice is available (`voice="auto"`);
  3. re-cut:   the beat's narration with dead air trimmed (gaps > 0.35 s), then shots split to the shorts pacing of
               ENGAGEMENT_RECIPE section 4 (ASL 1.8-2.6 s, a visual change every <= 2.6 s: a cut or a 115% punch-in);
  4. captions: 1-3 word kinetic pages in the 9:16 style (factory/finish/captions.py), re-timed to the short;
  5. loop:     the short ends on the hook's opening frames (R-7 frame_match), so the replay is seamless;
  6. outputs:  shorts/<SC>/edit.json (the edit decision list), episode.json (a 1080x1920 QC-able episode whose shots
               carry the re-timed VERTICAL cameras), words.json, props.json (Remotion Finish inputs: plates from
               plates_vertical/, re-cut shots with plate/src/zoom), audio.wav (ffmpeg cut of the narration, when the
               narration exists).
Finish (Remotion) and QC (factory.qc, the shorts checklist) run on top of these (see __main__.py / finish.py).

Frames: `src` frames are absolute film frames of the long-form; `dst` frames are frames of the short.
"""
import copy
import json
import math
import os
import re

from factory.director import docuseries as doc
from factory.director import text as tx
from factory.director.paths import ROOT

FPS = 30
HOOK_MIN_S, HOOK_MAX_S = 1.0, 3.0
MAX_GAP_S = 0.35                       # longer pauses inside the beat are trimmed (tighter re-cut)
LEAD_PAD_S, TAIL_PAD_S = 0.08, 0.12
END_BREATH_S = 0.25
LOOP_FRAMES = 15                       # tail: the hook's first 0.5 s, so the last frame flows into frame 0
MIN_PIECE_F = 18                       # PIXAR C9: no shot shorter than 18 frames
SHOT_MAX_S = 2.6                       # ENGAGEMENT P-1 overall ASL 1.8-2.6 s / P-2 visual change cadence
HOOK_SHOT_MAX_S = 1.5                  # ENGAGEMENT P-1 HOOK row: ASL 1.0-1.5 s, 2-3 shots in the first 3 s
PUNCH_IN = 1.15                        # ENGAGEMENT P-2: a >= 115% punch-in counts as a visual change
SNAP_F = 10


# ------------------------------------------------------------------ inputs
def load_episode_dir(ep_dir):
    def rd(name):
        p = os.path.join(ep_dir, name)
        if not os.path.exists(p):
            return None
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    story, ep = rd("story.json"), rd("episode.json")
    if not story or not ep:
        raise FileNotFoundError(f"{ep_dir}: needs story.json and episode.json (run factory.director first)")
    if ep.get("format") != "docuseries" or not ep.get("shorts"):
        raise ValueError(f"{ep_dir}: episode.json is not a docuseries with shorts[] (format={ep.get('format')!r})")
    words, wsrc = rd("audio/narration.words.json"), "audio/narration.words.json"
    if words is None:
        words, wsrc = words_from_story(story), "story.json narration timing (synthetic word split)"
    audio = os.path.join(ep_dir, "audio", "narration.mp3")
    return {"dir": ep_dir, "story": story, "episode": ep, "words": words, "words_source": wsrc,
            "narration": audio if os.path.exists(audio) else None}


def words_from_story(story):
    """[{w, s, e}] from the planned line timing: each line's duration split over its words by length."""
    out = []
    for ln in story["narration"]:
        toks = [t for t in re.sub(r"\[[^\]]*\]", "", ln["text"]).split() if tx.words(t)]
        if not toks:
            continue
        wts = [len(t) + 2 for t in toks]
        tot, dur, acc = sum(wts), ln["t1"] - ln["t0"], 0.0
        for t, w in zip(toks, wts):
            s = ln["t0"] + dur * acc / tot
            acc += w
            out.append({"w": t, "s": round(s, 3), "e": round(ln["t0"] + dur * acc / tot - 0.02, 3)})
    return out


# ------------------------------------------------------------------ 1. pick
def _intensity(story, sc):
    lines = [ln for ln in story["narration"] if ln["t0"] >= sc["in"] - 0.01 and ln["t1"] <= sc["out"] + 0.01]
    txt = " ".join(ln["text"] for ln in lines)
    n = max(1, len(tx.words(txt)))
    score = (tx.count_lexicon(txt, tx.lex("tension")) + tx.count_lexicon(txt, tx.lex("threat"), stems=True)) / n * 100
    score += 2 * sum(1 for ln in lines if ln.get("rehook")) + txt.count("?")
    return round(score, 3)


def vertical_coverage(ep, f0, f1):
    """Frames of [f0, f1) not covered by a shot with cameras.vertical."""
    missing = 0
    for s in ep["shots"]:
        a, b = max(f0, s["from"]), min(f1, s["to"])
        if a < b and not (s.get("cameras") or {}).get("vertical"):
            missing += b - a
    return missing


def pick(ctx, n=None):
    ep, story = ctx["episode"], ctx["story"]
    by_id = {sc["id"]: sc for sc in doc.candidates(story)}
    ranked = []
    for item in ep["shorts"]:
        sc = by_id.get(item["id"])
        if not sc or vertical_coverage(ep, item["from"], item["to"]):
            continue
        ranked.append({**item, "in": sc["in"], "out": sc["out"], "score": _intensity(story, sc)})
    ranked.sort(key=lambda c: -c["score"])
    return ranked[:n] if n else ranked


# ------------------------------------------------------------------ 2. hook
def climax_line(story, cand):
    """The beat's peak line (tension/threat lexicon, re-hook, tag energy), preferring its second half."""
    mid = (cand["in"] + cand["out"]) / 2
    best, bs = None, -1.0
    for ln in story["narration"]:
        if ln["t0"] < cand["in"] - 0.01 or ln["t1"] > cand["out"] + 0.01:
            continue
        t = ln["text"]
        s = 2 * tx.count_lexicon(t, tx.lex("tension")) + 2 * tx.count_lexicon(t, tx.lex("threat"), stems=True)
        s += 3 * bool(ln.get("rehook")) + ("?" in t or "!" in t) + {"excited": 2.0, "dramatic": 1.5}.get(ln["tag"].lower(), 0.0)
        s += 1.0 if ln["t0"] >= mid else 0.0
        if s > bs:
            best, bs = ln, s
    return best


def hook_words(words, line):
    """Words of the climax line that fit HOOK_MIN..HOOK_MAX s, ending on a sentence end, else a clause end."""
    ws = [w for w in words if w["s"] >= line["t0"] - 0.05 and w["e"] <= line["t1"] + 0.05]
    budget = HOOK_MAX_S - LEAD_PAD_S - TAIL_PAD_S
    fit = [w for w in ws if w["e"] - ws[0]["s"] <= budget]
    if not fit:
        return ws[:1]
    for pat in (r"[.!?]$", r"[,;:]$"):
        ends = [i for i, w in enumerate(fit) if re.search(pat, w["w"]) and w["e"] - fit[0]["s"] >= HOOK_MIN_S - 0.2]
        if ends:
            return fit[: ends[-1] + 1]
    return fit


def try_voice_pickup(text, out_dir):
    """VO pickup of the hook line in the series voice via factory.voice (if that stage exists); else None."""
    try:
        from factory import voice  # noqa: F401  (factory/voice is built by the voice stage)
    except ImportError:
        return None
    story = {"id": "pickup", "format": "short", "narration": [{"id": "L01", "beat": "B0", "tag": "excited", "text": text, "t0": 0.0,
                                                                 "t1": len(tx.words(text)) / 2.9}]}
    try:
        res = voice.synthesize(story, out_dir)
        with open(res["words"]) as fh:
            ws = json.load(fh)
        dur = max(w["e"] for w in ws) + 0.1
        return {"audio": res["audio"], "words": ws, "duration": dur} if HOOK_MIN_S <= dur <= HOOK_MAX_S else None
    except Exception as e:  # noqa: BLE001 - a failed pickup falls back to the re-cut hook
        return {"error": str(e)}


# ------------------------------------------------------------------ 3. segments
def f_of(t, off):
    return off + round(t * FPS)


def body_segments(words, cand, off):
    """Narration-time spans of the beat with long pauses trimmed, as film-frame segments [{src0, src1, a0, a1}]."""
    ws = [w for w in words if w["s"] >= cand["in"] - 0.05 and w["e"] <= cand["out"] + 0.05]
    spans, cur = [], [ws[0]["s"] - LEAD_PAD_S, ws[0]["e"]]
    for prev, w in zip(ws, ws[1:]):
        if w["s"] - prev["e"] > MAX_GAP_S and (prev["e"] + TAIL_PAD_S - cur[0]) * FPS >= 15:
            spans.append([cur[0], prev["e"] + TAIL_PAD_S])
            cur = [w["s"] - LEAD_PAD_S, w["e"]]
        else:
            cur[1] = w["e"]
    spans.append([cur[0], min(cur[1] + END_BREATH_S, cand["out"] + 0.3)])
    return [{"kind": "body", "src0": f_of(a, off), "src1": f_of(b, off), "audio": [round(a, 3), round(b, 3)]} for a, b in spans]


def build_edit(ctx, cand, voice="auto", out_dir=None):
    ep, story, words = ctx["episode"], ctx["story"], ctx["words"]
    off = ep["audio"]["offsetFrames"]
    line = climax_line(story, cand)
    hw = hook_words(words, line)
    h0, h1 = hw[0]["s"] - LEAD_PAD_S, hw[-1]["e"] + TAIL_PAD_S
    hook = {"kind": "hook", "src0": f_of(h0, off), "src1": f_of(h1, off), "audio": [round(h0, 3), round(h1, 3)],
            "source": "recut", "line": line["id"], "text": " ".join(w["w"] for w in hw)}
    pickup = None
    if voice == "auto" and out_dir:
        pickup = try_voice_pickup(cand["hook_line"], os.path.join(out_dir, "pickup"))
    if pickup and "audio" in pickup:
        n = round(pickup["duration"] * FPS)
        hook.update(source="vo_pickup", src1=hook["src0"] + n, audio=None, pickup=pickup["audio"], text=cand["hook_line"],
                    pickup_words=pickup["words"])
    body = body_segments(words, cand, off)
    tail = {"kind": "tail", "src0": hook["src0"], "src1": hook["src0"] + LOOP_FRAMES, "audio": None}
    segs = [hook] + body + [tail]
    d = 0
    for s in segs:
        s["dst0"], s["dst1"] = d, d + s["src1"] - s["src0"]
        d = s["dst1"]
    return {"candidate": cand, "segments": segs, "pickup_error": (pickup or {}).get("error"),
            "loop": {"method": "frame_match", "tail_frames": LOOP_FRAMES, "src": [tail["src0"], tail["src1"]]}}


# ------------------------------------------------------------------ 4. shots + pacing
def _pieces(ep, segs):
    """Each segment cut by the long-form's shot boundaries -> [{dst0, dst1, src, plate}] (tiny pieces absorbed)."""
    out = []
    for g in segs:
        for s in ep["shots"]:
            a, b = max(g["src0"], s["from"]), min(g["src1"], s["to"])
            if a >= b:
                continue
            p = {"dst0": g["dst0"] + a - g["src0"], "dst1": g["dst0"] + b - g["src0"], "src": a, "plate": s["id"], "seg": g["kind"]}
            if p["dst1"] - p["dst0"] < MIN_PIECE_F and out and out[-1]["dst1"] == p["dst0"]:
                out[-1]["dst1"] = p["dst1"]          # hold the previous plate stream a few frames (no flash cut)
                continue
            out.append(p)
    if len(out) > 1 and out[0]["dst1"] - out[0]["dst0"] < MIN_PIECE_F:
        first = out.pop(0)
        out[0]["src"] -= out[0]["dst0"] - first["dst0"]
        out[0]["dst0"] = first["dst0"]
    return out


def _split(p, word_starts):
    """Split a piece longer than SHOT_MAX_S (the hook: HOOK_SHOT_MAX_S) at word starts near even cut points;
    alternate a 115% punch-in."""
    n_f = p["dst1"] - p["dst0"]
    limit = HOOK_SHOT_MAX_S if p["seg"] == "hook" else SHOT_MAX_S
    if n_f <= limit * FPS:
        return [dict(p, zoom=1.0)]
    k = math.ceil(n_f / (limit * FPS))          # as few parts as fit the ceiling
    cuts = []
    for i in range(1, k):
        want = p["dst0"] + round(i * n_f / k)
        near = [w for w in word_starts if abs(w - want) <= SNAP_F and p["dst0"] + 18 <= w <= p["dst1"] - 18]
        c = min(near, key=lambda w: abs(w - want)) if near else want
        if not cuts or c - cuts[-1] >= 18:
            cuts.append(c)
    bounds = [p["dst0"]] + cuts + [p["dst1"]]
    return [dict(p, dst0=a, dst1=b, src=p["src"] + a - p["dst0"], zoom=PUNCH_IN if i % 2 else 1.0)
            for i, (a, b) in enumerate(zip(bounds, bounds[1:]))]


def short_words(edit, words, off):
    """Words of the short in short-time seconds (hook words, body words; none on the silent loop tail)."""
    out = []
    for g in edit["segments"]:
        if g["kind"] == "hook" and g.get("source") == "vo_pickup":
            out += [{"w": w["w"], "s": round(g["dst0"] / FPS + w["s"], 3), "e": round(g["dst0"] / FPS + w["e"], 3)} for w in g["pickup_words"]]
            continue
        if not g.get("audio"):
            continue
        a0, a1 = g["audio"]
        for w in words:
            if w["s"] >= a0 - 1e-6 and w["e"] <= a1 + 1e-6:
                shift = g["dst0"] / FPS - (g["src0"] - off) / FPS
                out.append({"w": w["w"], "s": round(w["s"] + shift, 3), "e": round(w["e"] + shift, 3)})
    return out


def edit_shots(ep, edit, swords):
    starts = [round(w["s"] * FPS) for w in swords]
    shots = []
    for p in _pieces(ep, edit["segments"]):
        for q in _split(p, starts):
            shots.append({"id": f"S{len(shots):03d}", "from": q["dst0"], "to": q["dst1"], "plate": q["plate"], "src": q["src"],
                          "zoom": q["zoom"], "transition": "cut", "title": f"{q['seg']} {q['plate']}@{q['src']}"})
    return shots


# ------------------------------------------------------------------ re-timed QC episode (vertical cameras)
def _shift_keys(ks, d):
    return [[k[0] + d] + list(k[1:]) for k in ks] if isinstance(ks, list) else ks


def retime_shot(src_shot, d, f0, f1, sid, zoom=1.0):
    """Copy of a long-form shot moved by d frames onto [f0, f1) of the short, with its VERTICAL camera."""
    s = copy.deepcopy(src_shot)
    cam = s.pop("cameras")["vertical"]
    s.pop("short_candidate", None)
    s.pop("vertical", None)
    cam["keys"] = [{**k, "f": k["f"] + d} for k in cam["keys"]]
    if cam["keys"][0]["f"] > f0:                      # an absorbed sliver can reach past the source shot: hold keys
        cam["keys"].insert(0, {**cam["keys"][0], "f": f0})
    if cam["keys"][-1]["f"] < f1 - 1:
        cam["keys"].append({**cam["keys"][-1], "f": f1 - 1})
    for sh in cam.get("shakes") or []:
        sh["at"] += d
    if isinstance(cam.get("handheld"), list):
        cam["handheld"] = _shift_keys(cam["handheld"], d)
    s["camera"] = cam
    s.update({"id": sid, "from": f0, "to": f1, "keyFrame": max(f0, min(f1 - 1, s.get("keyFrame", f0) + d))})
    y = s.get("yacht")
    if y:
        for k in ("lights", "pitch", "roll", "sink", "hatch"):
            if isinstance(y.get(k), list):
                y[k] = _shift_keys(y[k], d)
    for a in s.get("actors") or []:
        perf = a.get("perf") or {}
        perf["stance"] = [[st[0] + d if st[0] > -10000 else st[0], st[1]] for st in perf.get("stance", [])]
        for p in perf.get("poses", []):
            p["from"] += d
            p["to"] += d
        for v in perf.get("verbs", []):
            v["at"] += d
        for t in a.get("tracks") or []:
            t["from"] = t.get("from", 0) + d
    for p in s.get("props") or []:
        for k in ("light", "show"):
            if k in p:
                p[k] = _shift_keys(p[k], d)
        if "strobe" in p:
            p["strobe"] += d
    if s.get("fires"):
        s["fires"] = [[f + d, v] for f, v in s["fires"]]
    if zoom != 1.0:
        s["zoom"] = zoom
    return s


def caption_anchors(pages):
    """QC caption records ({from,to,small,big,box}) laid out like studio/src/finish/Captions.tsx on 1080x1920."""
    out = []
    for p in pages:
        ws = [w["t"] for w in p["words"]]
        text = " ".join(ws)
        size = max(72 / 0.727, min(92 / 0.727, 800 / max(0.1, 0.62 * len(text) * 1.04)))
        width = min(803, 0.62 * len(text) * size)
        cx = (65 + 888) / 2
        out.append({"from": p["from"], "to": p["to"], "small": " ".join(ws[:-1]).lower(), "big": ws[-1].lower(), "at": "mid",
                    "box": [round(cx - width / 2), round(1180 - size * 0.98), round(cx + width / 2), round(1180 + size * 0.27)]})
    return out


def hook_title(text, hook_seg):
    """ENGAGEMENT H-5/C-6: the candidate's hook line as an on-screen title in the hook band (y 300-520 on 1080x1920)
    from frame 0 for >= 2 s (at least the whole hook). Returns the Finish prop and the QC caption record."""
    to = max(round(2.2 * FPS), hook_seg["dst1"])
    ws = text.split()
    width = min(800, 0.6 * len(text) * 56)
    cx = (65 + 888) / 2
    return {"finish": {"text": text, "from": 0, "to": to},
            "anchor": {"kind": "title", "from": 0, "to": to, "small": " ".join(ws[:-1]).lower(), "big": ws[-1].lower(), "at": "top",
                       "box": [round(cx - width / 2), 330, round(cx + width / 2), 500]}}


def qc_episode(ep, edit, shots, short_id, title, rel):
    by_id = {s["id"]: s for s in ep["shots"]}
    qshots = [retime_shot(by_id[s["plate"]], s["from"] - s["src"], s["from"], s["to"], s["id"], s["zoom"]) for s in shots]
    return {"version": 1, "id": short_id, "title": title, "fps": FPS, "width": doc.VERTICAL[0], "height": doc.VERTICAL[1],
            "format": "short", "durationFrames": shots[-1]["to"],
            "audio": {"narration": rel("audio.wav"), "wordsJson": rel("words.json"), "offsetFrames": 0},
            "world": ep["world"], "assets": ep["assets"], "captions": [], "shots": qshots,
            "source": {"builder": "factory/shorts", "episode": ep["id"], "candidate": edit["candidate"]["id"]}}


# ------------------------------------------------------------------ audio (ffmpeg)
def cut_audio(narration, edit, out_path, fps=FPS):
    """Concatenate the narration spans of the edit (silence on the loop tail; the VO pickup on a pickup hook),
    loudness-normalised to -14 LUFS / -1.5 dBTP. Returns the command for provenance."""
    import subprocess
    inputs, filt, labels = ["-i", narration], [], []
    for i, g in enumerate(edit["segments"]):
        dur = (g["dst1"] - g["dst0"]) / fps
        lab = f"a{i}"
        if g["kind"] == "hook" and g.get("source") == "vo_pickup":
            inputs += ["-i", g["pickup"]]
            filt.append(f"[{len(inputs) // 2 - 1}:a]apad,atrim=0:{dur:.4f},asetpts=PTS-STARTPTS[{lab}]")
        elif g.get("audio"):
            a0 = (g["src0"] - edit["offset"]) / fps
            filt.append(f"[0:a]atrim={max(0.0, a0):.4f}:{a0 + dur:.4f},asetpts=PTS-STARTPTS,apad,atrim=0:{dur:.4f}[{lab}]")
        else:
            filt.append(f"anullsrc=r=44100:cl=mono,atrim=0:{dur:.4f}[{lab}]")
        labels.append(f"[{lab}]")
    filt.append("".join(labels) + f"concat=n={len(labels)}:v=0:a=1,loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[out]")
    cmd = ["ffmpeg", "-y", "-loglevel", "error"] + inputs + ["-filter_complex", ";".join(filt), "-map", "[out]", "-ac", "2", out_path]
    subprocess.run(cmd, check=True)
    return cmd


# ------------------------------------------------------------------ driver
def derive_one(ctx, cand, out_root, voice="auto"):
    from factory.finish.captions import build_pages
    ep = ctx["episode"]
    off = ep["audio"]["offsetFrames"]
    short_id = f"{ep['id']}_{cand['id'].lower()}"
    d = os.path.join(out_root, cand["id"])
    os.makedirs(d, exist_ok=True)
    edit = build_edit(ctx, cand, voice=voice, out_dir=d)
    edit["offset"] = off
    swords = short_words(edit, ctx["words"], off)
    shots = edit_shots(ep, edit, swords)
    pages = build_pages(swords, fps=FPS, offset=0)

    def rel(name):
        p = os.path.abspath(os.path.join(d, name))
        return os.path.relpath(p, ROOT) if p.startswith(ROOT + os.sep) else p

    qep = qc_episode(ep, edit, shots, short_id, cand["hook_line"], rel)
    title = hook_title(cand["hook_line"], edit["segments"][0])
    qep["captions"] = [title["anchor"]] + caption_anchors(pages)
    audio = None
    if ctx["narration"]:
        audio = os.path.join(d, "audio.wav")
        edit["audio_cmd"] = cut_audio(ctx["narration"], edit, audio)
    else:
        qep["audio"].pop("narration")
    finish_ep = {"id": short_id, "title": cand["hook_line"], "fps": FPS, "width": doc.VERTICAL[0], "height": doc.VERTICAL[1],
                 "durationFrames": shots[-1]["to"], "audio": {"offsetFrames": 0},
                 "shots": [{k: s[k] for k in ("id", "from", "to", "title", "transition", "plate", "src", "zoom")} for s in shots]}
    props = {"episodeJson": finish_ep, "platesDir": f"finish/{short_id}/plates", "manifest": {}, "audio": None,
             "captions": pages, "steps": [], "title": title["finish"]}
    edit_doc = {
        "schema": "factory.shorts.edit/1", "id": short_id, "episode": ep["id"], "candidate": cand["id"], "chapter": cand["chapter"],
        "hook_line": cand["hook_line"], "score": cand["score"], "durationFrames": shots[-1]["to"],
        "hook": {k: v for k, v in edit["segments"][0].items() if k != "pickup_words"},
        "pickup_error": edit["pickup_error"], "loop": edit["loop"], "segments": [
            {k: v for k, v in g.items() if k not in ("pickup_words", "text")} for g in edit["segments"]],
        "shots": shots, "words_source": ctx["words_source"], "audio": "audio.wav" if audio else None,
        "plates": "plates_vertical/<plate>/<src frame>.png (render_episode.py --camera vertical)",
    }
    for name, obj in (("edit.json", edit_doc), ("episode.json", qep), ("words.json", swords), ("props.json", props)):
        with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
    return {"id": short_id, "dir": d, "edit": edit_doc, "episode": qep, "words": swords, "props": props, "pages": pages}


def derive(ep_dir, n=None, out_root=None, voice="auto"):
    ctx = load_episode_dir(ep_dir)
    out_root = out_root or os.path.join(ep_dir, "shorts")
    return ctx, [derive_one(ctx, c, out_root, voice) for c in pick(ctx, n)]
