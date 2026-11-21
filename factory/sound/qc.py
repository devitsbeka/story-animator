"""Sound QC: the ENGAGEMENT_RECIPE section 6 checklist, measured on sound.json and on the rendered mix + stems.

check(sound_path, mix_report) -> {"pass": bool, "checks": [{name, pass, value, rule}]}
Standalone: python3 -m factory.sound.qc --sound episodes/sentinel/sound.json --report episodes/sentinel/audio/mix_v1.report.json
"""
import argparse, json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from audio_util import SR, decode, ebur128, silences  # noqa: E402
from mixer import speech_intervals, gap_intervals, aselect_expr, ROOT  # noqa: E402


def _rms_db(x):
    return float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12))


def check(sound_path, rep):
    snd = json.load(open(sound_path))
    fps, D = snd["fps"], snd["durationFrames"]
    total = D / fps
    lo, du = snd["loudness"], snd["ducking"]
    out = []

    def add(name, ok, value, rule):
        out.append({"name": name, "pass": bool(ok), "value": value, "rule": rule})

    tgt, tol = lo["integratedLUFS"], lo["toleranceLU"]
    for k in ("wav", "m4a"):
        add(f"integrated loudness ({k})", abs(rep[k]["I"] - tgt) <= tol, f"{rep[k]['I']:.2f} LUFS", f"S-1 {tgt}±{tol}")
        add(f"true peak ({k})", rep[k]["TP"] <= lo["truePeakDBTP"], f"{rep[k]['TP']:.2f} dBTP", f"S-1 <= {lo['truePeakDBTP']}")

    # short-term loudness outside the declared silence (and after the first 3 s window has filled)
    m = ebur128(os.path.join(ROOT, rep["m4a"]["path"]))
    sil = [(s["from"] / fps, s["to"] / fps) for s in snd["silences"]]
    lo_s, hi_s = lo["shortTermRangeLUFS"]
    S = [(t, v) for t, v in m["S"] if t >= 3.0 and not any(a - 0.2 <= t <= b + 3.0 for a, b in sil)]
    inside = [v for _, v in S if lo_s <= v <= hi_s]
    frac = len(inside) / max(1, len(S))
    vals = [v for _, v in S]
    add("short-term loudness in range", frac >= 0.95,
        f"{100*frac:.1f}% of {len(S)} samples in [{lo_s},{hi_s}] (min {min(vals):.1f}, max {max(vals):.1f})",
        "S-1 short-term within -17..-10 outside P-5 (pass at >=95% of 100 ms samples)")

    # stem balance under speech and in gaps
    words = json.load(open(os.path.join(ROOT, snd["voice"]["words"])))
    off = snd["voice"]["offsetFrames"] / fps
    speech = speech_intervals(words, off)
    st = {k: os.path.join(ROOT, v) for k, v in rep["stems"].items()}
    V = ebur128(st["voice"], aselect_expr(speech))["I"]
    Mu = ebur128(st["music"], aselect_expr(speech))["I"]
    Am = ebur128(st["ambience"], aselect_expr(speech))["I"]
    a, b = lo["musicUnderVoiceDB"]
    add("music under voice during speech", a <= V - Mu <= b, f"{V - Mu:.2f} dB", f"S-2 {a}..{b} dB")
    a, b = lo["ambienceUnderVoiceDB"]
    add("ambience under voice during speech", a <= V - Am <= b, f"{V - Am:.2f} dB", f"S-2 {a}..{b} dB")
    bridged = speech_intervals(words, off, du.get("bridgeGapS", 0.8))
    t_last = bridged[-1][1]
    gaps = [(x, y) for x, y in gap_intervals(bridged, total, du.get("bridgeGapS", 0.8))
            if y <= t_last and not any(sa - 0.5 <= y and x <= sb for sa, sb in sil) and y - x > 0.2]
    if gaps:
        Mg = ebur128(st["music"], aselect_expr(gaps))["I"]
        add("music rises in narration gaps", -10.5 <= Mg - V <= -5.5, f"{Mg - V:+.2f} dB vs voice over {len(gaps)} gaps",
            "S-2 music -6..-10 dB vs voice in gaps >= 0.8 s")
    else:
        add("music rises in narration gaps", True, "n/a: the narration has no gap >= 0.8 s before its last word", "S-2")
        out[-1]["pass"] = None
    if "musicOutroDB" in du and total - t_last > 0.8:
        Mo = ebur128(st["music"], aselect_expr([(t_last + 0.3, total)]))["I"]
        add("music carries the outro after the last word", abs((Mo - V) - du["musicOutroDB"]) <= 3.0,
            f"{Mo - V:+.2f} dB vs voice over {total - t_last:.2f} s", f"design target {du['musicOutroDB']} dB (±3)")
    # music start / hard stop
    mus = decode(st["music"])
    f3 = int(3 / fps * SR)
    head = _rms_db(mus[:f3])
    nxt = _rms_db(mus[f3:4 * f3])
    add("music starts at frame 0 (no fade-in > 3 frames)", head > -45 and head > nxt - 12,
        f"first 3 frames {head:.1f} dBFS vs next 9 frames {nxt:.1f}", "S-3/checklist")
    tail = _rms_db(mus[-int(0.1 * SR):])
    before = _rms_db(mus[-int(0.5 * SR):-int(0.2 * SR)])
    add("hard stop at the end (no fade > 6 frames)", tail > before - 6, f"last 100 ms {tail:.1f} dBFS vs {before:.1f}", "S-3 / MrBeast abrupt end")

    sec = snd["music"]["sections"]
    max_gap = max(s["to"] - s["from"] for s in sec) / fps
    add("music section/layer change gap", max_gap <= 15.0, f"max {max_gap:.1f} s over {len(sec)} sections", "S-3 <= 15 s")
    energies = [s["energy"] for s in sec]
    add("energy map: pre-payoff 0 then payoff >= 4", any(s["label"] == "pre_payoff" and s["energy"] == 0 for s in sec)
        and sec[-1]["energy"] >= 4, f"{energies}", "S-3 energy map")

    # cue rules against the episode
    ep = json.load(open(os.path.join(ROOT, snd["source"]["episode"])))
    cuts = [s["from"] for s in sorted(ep["shots"], key=lambda s: s["from"])][1:]
    wh = [c for c in snd["cues"] if c["type"] == "whoosh"]
    on_cut = sum(1 for f in cuts if any(c["at"] == f for c in wh))
    add("whoosh on >= 60% of cuts", on_cut / len(cuts) >= 0.6, f"{on_cut}/{len(cuts)} ({100*on_cut/len(cuts):.0f}%)", "S-4")
    risers = [c for c in snd["cues"] if c["type"] == "riser"]
    miss = [r["id"] for r in snd["reveals"] if r["kind"] != "hook"
            and not any(abs(c["at"] - r["riserEnd"]) <= 1 and c["anchor"] == "end" for c in risers)]
    add("riser ends on each reveal (±1 frame)", not miss, f"missing: {miss}" if miss else f"{len(risers)} risers",
        "S-4 (payoff riser lands on the P-5 drop)")
    need = [r for r in snd["reveals"] if r["kind"] in ("hook", "step", "payoff") or r.get("midpoint")]
    imp = [c for c in snd["cues"] if c["type"] == "impact"]
    miss = [r["id"] for r in need if not any(abs(c["at"] - r["at"]) <= 1 for c in imp)]
    add("impact on hook, midpoint, payoff and steps", not miss, f"missing: {miss}" if miss else f"{len(need)} reveals hit", "S-4")
    tr = sorted(c["at"] for c in snd["cues"] if c.get("transient"))
    per_min = len(tr) / (total / 60)
    add("spot SFX per minute", 25 <= per_min <= 45, f"{per_min:.1f}/min ({len(tr)} transients)", "S-4 25..45")
    worst = max((sum(1 for y in tr if x <= y < x + 0.5 * fps) for x in tr), default=0)
    add("max transients in any 0.5 s window", worst <= 3, f"{worst}", "S-4 <= 3")

    # P-5 silence on the non-voice stem, ambience continuity
    payoff = next(r for r in snd["reveals"] if r["kind"] == "payoff")["at"] / fps
    sl = [(a, b) for a, b in silences(st["background"], -40, 0.3)]
    pre = [(a, b) for a, b in sl if 0.3 <= b - a <= 0.85 and payoff - 1.0 <= b <= payoff + 0.1]
    add("exactly one 0.3-0.8 s silence (< -40 dBFS) right before the payoff", len(pre) == 1 and len(sl) == 1,
        f"background silences: {[(round(a,2), round(b,2)) for a, b in sl]}, payoff at {payoff:.2f}s", "P-5 / S-1")
    gaps_amb = [(a, b) for a, b in silences(st["ambience"], -60, 1.0)
                if not any(sa - 0.1 <= a and b <= sb + 0.1 for sa, sb in sil)]
    add("no ambience gap > 1 s outside the silence", not gaps_amb, f"{gaps_amb}", "S-6")
    add("ASR intelligibility (WER <= 5%)", True, "not run in this stage (no ASR model wired; see report)", "checklist (not measured)")
    out[-1]["pass"] = None
    passed = all(c["pass"] for c in out if c["pass"] is not None)
    return {"pass": passed, "checks": out}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sound", required=True)
    ap.add_argument("--report", required=True)
    a = ap.parse_args()
    r = check(os.path.abspath(a.sound), json.load(open(a.report)))
    for c in r["checks"]:
        print(f"  [{'PASS' if c['pass'] else ('----' if c['pass'] is None else 'FAIL')}] {c['name']}: {c['value']}")
    print("ALL PASS" if r["pass"] else "FAILURES")


if __name__ == "__main__":
    main()
