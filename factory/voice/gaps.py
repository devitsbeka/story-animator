"""Reserved narration gaps (canon CAN-N2b/N2c; Rabiger p.447 "open up spaces for featured sound effects").

story.json declares narration_gaps[] {id, after_line, len_s, purpose, filled_by}. The voice engine makes them real:
  1. synthesis is chunked at every gap (one TTS request per block between gaps, Rabiger p.450 "number them") and the
     blocks are joined with exactly the silence the gap still needs (stage.synthesize, `boundary_pads`);
  2. after voicing (any provider: ElevenLabs, the reference VO, the stub) `enforce` measures every gap in the word
     timings and, where a gap is still short, splices presence (very low pink noise, never digital silence) into the
     stem at the gap's midpoint, lengthening it by at most `max_splice_s` (0.8 s) and never shortening anything;
  3. `measure` re-reads the result; the report lands in audio/narration.gaps.json for the canon gate (CAN-N2c).

Word timings ([{w, s, e}], seconds) are shifted by every splice so they stay exact.
"""
import json
import os

from . import audio
from .text import script_words

MAX_SPLICE_S = 0.8
TOL_S = 0.05
PRESENCE = "anoisesrc=c=pink:a=0.0008:r={sr}:d={d:.4f}"


def gap_boundaries(story):
    """[(gap, index of the last word of gap.after_line)] for gaps with a following line, in script-word indices."""
    idx, last = 0, {}
    lines = story.get("narration") or []
    for ln in lines:
        n = len(script_words(ln["text"]))
        idx += n
        last[ln["id"]] = idx - 1
    ids = [ln["id"] for ln in lines]
    out = []
    for g in story.get("narration_gaps") or []:
        a = g.get("after_line")
        if a in last and a in ids and ids.index(a) < len(ids) - 1:
            out.append((g, last[a]))
    return sorted(out, key=lambda x: x[1])


def measure(story, words):
    rows = []
    for g, i in gap_boundaries(story):
        if i + 1 >= len(words):
            continue
        real = words[i + 1]["s"] - words[i]["e"]
        rows.append({"id": g["id"], "after_line": g["after_line"], "purpose": g.get("purpose"), "planned_s": g["len_s"],
                     "measured_s": round(real, 3), "at_s": round(words[i]["e"], 3),
                     "ok": real + 1e-6 >= g["len_s"] - TOL_S})
    return rows


def plan_inserts(story, words, max_splice_s=MAX_SPLICE_S):
    """[(t, dur, gap_id)]: where (stem seconds) and how much presence to splice so each gap reaches its planned length."""
    out = []
    for g, i in gap_boundaries(story):
        if i + 1 >= len(words):
            continue
        real = words[i + 1]["s"] - words[i]["e"]
        if real + 1e-6 >= g["len_s"] - TOL_S:
            continue
        add = round(min(max_splice_s, g["len_s"] - real + 0.01), 3)
        out.append((round(words[i]["e"] + max(0.0, real) / 2, 4), add, g["id"]))
    return out


def shift_words(words, inserts):
    out = []
    for w in words:
        d = sum(dur for t, dur, _ in inserts if t <= w["s"])
        out.append({**w, "s": round(w["s"] + d, 3), "e": round(w["e"] + d, 3)})
    return out


def splice(src, dst, inserts, sr=audio.SR):
    """Insert presence of the given durations at the given times (seconds) into src -> dst (re-encoded)."""
    if not inserts:
        if os.path.abspath(src) != os.path.abspath(dst):
            audio._run([audio.FFMPEG, "-v", "error", "-y", "-i", src, "-ac", "1", "-ar", str(sr)] + audio._encode_args(dst) + [dst])
        return dst
    filt, labels, prev = [], [], 0.0
    for k, (t, d, _) in enumerate(sorted(inserts)):
        filt.append(f"[0:a]aformat=sample_rates={sr}:channel_layouts=mono,atrim=start={prev:.4f}:end={t:.4f},asetpts=PTS-STARTPTS[s{k}]")
        filt.append(PRESENCE.format(sr=sr, d=d) + f",aformat=sample_rates={sr}:channel_layouts=mono[n{k}]")
        labels += [f"[s{k}]", f"[n{k}]"]
        prev = t
    k = len(inserts)
    filt.append(f"[0:a]aformat=sample_rates={sr}:channel_layouts=mono,atrim=start={prev:.4f},asetpts=PTS-STARTPTS[s{k}]")
    labels.append(f"[s{k}]")
    filt.append("".join(labels) + f"concat=n={len(labels)}:v=0:a=1[out]")
    tmp = dst + ".splice" + os.path.splitext(dst)[1]
    audio._run([audio.FFMPEG, "-v", "error", "-y", "-i", src, "-filter_complex", ";".join(filt), "-map", "[out]", "-ac", "1",
                "-ar", str(sr)] + audio._encode_args(tmp) + [tmp])
    os.replace(tmp, dst)
    return dst


def enforce(story, audio_path, words_path, report_path=None, max_splice_s=MAX_SPLICE_S, log=None):
    """Measure the declared gaps in the voiced words; splice presence where short (<= max_splice_s each); rewrite the
    audio + words in place; write the gaps report. Returns the report dict."""
    log = log or (lambda *a: None)
    with open(words_path) as fh:
        words = json.load(fh)
    n_script = sum(len(script_words(ln["text"])) for ln in story.get("narration") or [])
    rep = {"audio": audio_path, "words": words_path, "max_splice_s": max_splice_s, "inserts": [], "gaps": []}
    if len(words) != n_script:
        rep["error"] = f"words.json has {len(words)} words, the script {n_script}: gaps not enforced"
    elif story.get("narration_gaps"):
        before = {r["id"]: r["measured_s"] for r in measure(story, words)}
        ins = plan_inserts(story, words, max_splice_s)
        if ins:
            splice(audio_path, audio_path, ins)
            words = shift_words(words, ins)
            with open(words_path, "w") as fh:
                json.dump(words, fh, indent=0)
            log(f"[voice] gaps: spliced {len(ins)} presence inserts ({sum(d for _, d, _ in ins):.2f} s) into {os.path.basename(audio_path)}")
        rep["inserts"] = [{"gap": g, "at_s": t, "dur_s": d} for t, d, g in ins]
        rep["gaps"] = [dict(r, before_s=before.get(r["id"])) for r in measure(story, words)]
    rep["ok"] = all(r["ok"] for r in rep["gaps"]) and "error" not in rep
    if report_path:
        with open(report_path, "w") as fh:
            json.dump(rep, fh, indent=1)
    return rep


def boundary_pads(chunks, takes_words, durations, story):
    """Silence to put between consecutive chunks: a declared gap gets what it still needs after the takes' own
    trailing/leading silence; other boundaries get stage.CHUNK_GAP_S. chunks: [[line, ...]], takes_words: timed words per
    chunk (chunk-local seconds), durations: chunk audio durations."""
    from .stage import CHUNK_GAP_S
    gaps = {g["after_line"]: g for g in story.get("narration_gaps") or []}
    pads = []
    for i in range(len(chunks) - 1):
        g = gaps.get(chunks[i][-1]["id"])
        if not g:
            pads.append(CHUNK_GAP_S)
            continue
        tail = durations[i] - (takes_words[i][-1]["e"] if takes_words[i] else durations[i])
        lead = takes_words[i + 1][0]["s"] if takes_words[i + 1] else 0.0
        pads.append(round(max(0.0, g["len_s"] + 0.03 - tail - lead), 3))
    return pads
