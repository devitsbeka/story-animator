"""Rules on the final mp4: TECH (format), SOUND (loudness, silences), HOOK (motion/audio at t=0),
RETENTION (loop SSIM), PACING (freeze, detected-cut cadence)."""
from __future__ import annotations

import numpy as np

from . import video
from .common import FAIL, PASS, check, rnd, rule, skip


def merge_cuts(cuts, min_gap=0.25):
    """Scene-score hits in consecutive frames (dissolves, flashes) count as one cut."""
    out = []
    for c in sorted(cuts):
        if not out or c - out[-1] > min_gap:
            out.append(c)
    return out


def measure(path):
    m = {"probe": video.probe(path)}
    m["audio"] = video.audio_pass(path) if m["probe"].get("has_audio") else None
    m["video"] = video.video_pass(path)
    m["video"]["cuts_merged"] = merge_cuts(m["video"]["cuts"])
    D = m["probe"]["duration"]
    try:
        f0 = video.frame_at(path, 0.0)
        f15 = video.frame_at(path, 0.5)
        flast = video.frame_at(path, max(0.0, D - 0.1))
        m["motion_0_05"] = float(np.abs(f0 - f15).mean())
        m["loop_ssim"] = video.ssim(f0, flast)
    except RuntimeError as e:
        m["frame_error"] = str(e)
    return m


def video_rules(m, ep=None):
    out = []
    pr = m["probe"]
    fps_e = ep.fps if ep else 30.0
    W, H = (ep.width, ep.height) if ep else (1080, 1920)
    out.append(check("TQ-VIDEO-RES", "TECH", (pr.get("width"), pr.get("height")) == (1080, 1920) and (W, H) == (1080, 1920),
                     f"{pr.get('width')}x{pr.get('height')}", "1080x1920 (9:16)"))
    out.append(check("TQ-VIDEO-FPS", "TECH", abs(pr.get("fps", 0) - fps_e) < 0.01, rnd(pr.get("fps")), f"{fps_e} fps (episode)"))
    if ep:
        D = ep.duration
        out.append(check("TQ-VIDEO-DURATION", "TECH", abs(pr["duration"] - D) <= 0.25, rnd(pr["duration"], 3), f"{rnd(D, 3)} s +- 0.25 (episode durationFrames)"))
        if pr.get("nb_frames"):
            out.append(check("TQ-VIDEO-FRAMES", "TECH", abs(pr["nb_frames"] - ep.frames) <= 3, pr["nb_frames"], f"{ep.frames} +- 3"))
    out.append(check("TQ-VIDEO-AUDIO", "TECH", pr.get("has_audio", False), pr.get("acodec"), "an audio stream"))
    v = m["video"]
    blk = [(a, b) for a, b in v["black"]]
    out.append(check("TQ-VIDEO-BLACK", "TECH", not blk, [rnd(x, 2) for x in blk], "no black segment >= 0.1 s (blackdetect pix_th=0.10)"))
    if v.get("unique_frames") is not None and pr.get("duration"):
        eff = v["unique_frames"] / pr["duration"]
        out.append(check("TQ-VIDEO-EFFECTIVE-FPS", "TECH", eff >= 0.8 * fps_e, {"effective_fps": rnd(eff, 2), "unique_frames": v["unique_frames"]},
                         f">= {rnd(0.8 * fps_e, 1)} distinct frames/s (mpdecimate); held plates read as stepped motion"))
    fz = [(a, b if b is not None else pr["duration"]) for a, b in v["freeze"]]
    out.append(check("P-7.freeze", "PACING", not fz, [rnd(x, 2) for x in fz], "never a fully still screen > 0.5 s (freezedetect n=0.001)"))

    # HOOK: motion in the first 0.5 s, audio from frame 0
    if "motion_0_05" in m:
        out.append(check("H-8.motion", "HOOK", m["motion_0_05"] > 0.004, rnd(m["motion_0_05"], 4), "mean |frame0 - frame15| > 0.004 (something moves by 0.5 s)"))
        out.append(rule("R-7.loop_ssim", "RETENTION", PASS if m["loop_ssim"] >= 0.5 else FAIL, rnd(m["loop_ssim"]), "SSIM(last, first) >= 0.5",
                        "the text-join alternative needs the LLM judge (vision/LLM review)"))
    a = m.get("audio")
    if not a:
        out.append(skip("S-1.integrated", "SOUND", "no audio stream"))
        return out
    st = a["short_term"]
    early = [mm for t, mm, s in st if t <= 0.5]
    loud0 = max(early) if early else -120
    out.append(check("H-9.audio_at_start", "HOOK", loud0 > -40, rnd(loud0, 1), "momentary loudness > -40 LUFS within the first 0.5 s (music bed at frame 0)"))
    I, TP = a["integrated"], a["true_peak"]
    out.append(check("S-1.integrated", "SOUND", I is not None and -15 <= I <= -13, I, "-14 LUFS +- 1"))
    out.append(check("S-1.true_peak", "SOUND", TP is not None and TP <= -1.0, TP, "<= -1.0 dBTP"))
    sil = [(s, e if e is not None else pr["duration"]) for s, e in a["silences"]]
    D = pr["duration"]
    in_sil = lambda t: any(s <= t <= e for s, e in sil)  # noqa: E731
    sts = [s for t, mm, s in st if t >= 3.0 and t <= D - 0.5 and not in_sil(t) and s > -70]
    if sts:
        share = sum(-17 <= s <= -10 for s in sts) / len(sts)
        out.append(check("S-1.short_term", "SOUND", share >= 0.95, {"share_in_range": rnd(share), "min": rnd(min(sts), 1), "max": rnd(max(sts), 1)},
                         ">= 95% of 3 s short-term values in [-17, -10] LUFS outside declared silences"))
    hard = [(s, e) for s, e in sil if 0.3 <= e - s <= 0.8]
    pre_payoff = [(s, e) for s, e in hard if 0.70 * D <= e <= 0.95 * D]
    out.append(check("P-5.silence", "SOUND", len(pre_payoff) == 1 and len(hard) == 1,
                     {"silences_0.3_0.8s": [rnd(x, 2) for x in hard], "before_payoff": [rnd(x, 2) for x in pre_payoff]},
                     "exactly one hard silence (< -40 dB, 0.3-0.8 s), placed before the payoff (0.70-0.95 D)"))
    long_gaps = [(s, e) for s, e in sil if e - s > 1.0]
    out.append(check("S-6.no_gaps", "SOUND", not long_gaps, [rnd(x, 2) for x in long_gaps], "no silence (< -40 dB) longer than 1 s"))
    return out


def detected_cut_rules(m, ep=None):
    """PACING cadence from the detected cuts, plus TECH agreement with the episode edit."""
    out = []
    pr = m["probe"]
    D = pr["duration"]
    cuts = [c for c in m["video"]["cuts_merged"] if 0.2 < c < D - 0.1]
    n_shots = len(cuts) + 1
    asl = D / n_shots
    out.append(check("P-1.asl_detected", "PACING", 1.8 <= asl <= 2.6, {"asl_s": rnd(asl, 2), "detected_shots": n_shots}, "overall ASL 1.8-2.6 s (ffmpeg scene > 0.3)"))
    bounds = [0.0] + cuts + [D]
    gap = max(b - a for a, b in zip(bounds, bounds[1:]))
    out.append(check("P-2.major_gap_detected", "PACING", gap <= 10.0, rnd(gap, 2), "detected cut (major interrupt proxy) at least every 10 s"))
    if ep:
        eb = [s["from"] / ep.fps for s in ep.shots if s["from"] > 0]
        tol = 3 / ep.fps
        hit = sum(1 for b in eb if any(abs(b - c) <= tol for c in cuts))
        recall = hit / len(eb) if eb else 1.0
        status = PASS if recall >= 0.8 else FAIL
        out.append(rule("TQ-VIDEO-EDIT-MATCH", "TECH", status, {"episode_cuts": len(eb), "detected_cuts": len(cuts), "matched": hit, "recall": rnd(recall)},
                        ">= 80% of episode shot boundaries visible as a detected cut (+-3 f)",
                        "low recall means the mp4 is not the cut described by episode.json, or cuts are too soft to detect"))
    return out
