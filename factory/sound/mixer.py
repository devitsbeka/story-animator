"""ffmpeg mixer: sound.json + narration + SFX + music -> final stereo mix (wav + m4a), EBU R128 normalised.

Pipeline (all audio work is ffmpeg filter graphs; numpy only writes the music score and the duck/silence envelopes):
  1. voice stem      narration, delayed by offsetFrames, mono -> stereo.  V = its integrated loudness.
  2. sfx stem        every cue: atrim around its landmark (onset / peak / active end) -> volume -> fades -> adelay,
                     summed with amix normalize=0.  Level: V + relDB - (file's max momentary loudness).
  3. ambience stem   beds: -stream_loop, trimmed to [from, to], fades; level V + ambienceGapDB + relDB - file I.
  4. music stem      factory/sound/music.py score from the energy map.
  5. ducking         envelope mode: a gain curve built from the word timings (gaps < bridgeGapS stay ducked,
                     attack/release smoothing) multiplied in with ffmpeg amultiply; sidechain mode: ffmpeg
                     sidechaincompress keyed by the voice stem.  P-5 silences are zeroed in the same envelopes.
                     The music and ambience buses are then calibrated in closed loop so that, measured with
                     ebur128 over the speech intervals only, music sits musicSpeechDB and ambience ambienceSpeechDB
                     under the voice.
  6. master          amix -> gain to integratedLUFS -> 4x oversampled alimiter at limiterCeilingDBFS -> re-measure and
                     correct (twice) -> 24-bit wav + AAC m4a, true peak re-checked on the m4a.

Usage: python3 -m factory.sound.mixer --sound episodes/sentinel/sound.json --out episodes/sentinel/audio/mix_v1
"""
import argparse, json, os, shutil, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from audio_util import FFMPEG, SR, run, decode, write_wav, ebur128  # noqa: E402
import sfx_library  # noqa: E402
import music as music_mod  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))


def ff(args):
    return run([FFMPEG, "-hide_banner", "-v", "error", "-y"] + args)


def speech_intervals(words, offset_s, bridge=0.0):
    iv = sorted((w["s"] + offset_s, w["e"] + offset_s) for w in words)
    out = []
    for a, b in iv:
        if out and a - out[-1][1] < bridge:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def aselect_expr(iv):
    return "aselect='" + "+".join(f"between(t\\,{a:.3f}\\,{b:.3f})" for a, b in iv) + "',asetpts=N/SR/TB"


def gap_intervals(iv, total, min_gap):
    out, prev = [], 0.0
    for a, b in iv:
        if a - prev >= min_gap:
            out.append((prev + 0.15, a - 0.05))
        prev = b
    if total - prev >= min_gap:
        out.append((prev + 0.15, total))
    return out


def smooth_gain(target_db, rate, attack_ms, release_ms):
    """Asymmetric one-pole smoothing of a dB gain curve at control rate `rate` (Hz)."""
    a_att = np.exp(-1.0 / (attack_ms / 1000 * rate))
    a_rel = np.exp(-1.0 / (release_ms / 1000 * rate))
    y = np.empty_like(target_db)
    acc = target_db[0]
    for i, v in enumerate(target_db):
        a = a_att if v < acc else a_rel
        acc = a * acc + (1 - a) * v
        y[i] = acc
    return y


def envelope(total_s, iv, depth_db, attack_ms, release_ms, silences=(), rate=1000):
    """Linear gain envelope at SR: depth_db inside speech intervals (pre-rolled by the attack time), 0 dB outside,
    hard zero inside silences (5 ms ramps)."""
    n = int(np.ceil(total_s * rate)) + 1
    tgt = np.zeros(n)
    pre = attack_ms / 1000
    for a, b in iv:
        tgt[max(0, int((a - pre) * rate)):min(n, int(b * rate) + 1)] = depth_db
    g = 10 ** (smooth_gain(tgt, rate, attack_ms, release_ms) / 20)
    for a, b in silences:
        ia, ib = int(a * rate), int(b * rate)
        r = 5
        g[max(0, ia - r):ia] *= np.linspace(1, 0, ia - max(0, ia - r))
        g[ia:ib] = 0.0
        g[ib:ib + r] *= np.linspace(0, 1, len(g[ib:ib + r]))
    ns = int(round(total_s * SR))
    x = np.interp(np.arange(ns) / SR, np.arange(n) / rate, g).astype(np.float32)
    return np.stack([x, x], axis=1)


def landmark(info, anchor):
    return {"start": 0.0, "onset": info["onset"], "peak": info["peak"], "end": info["end"]}[anchor]


def build_bus(items, total, out_path, work):
    """items: list of dicts {path, loop, seg_start, seg_end, place, gain_db, fade_in, fade_out}. Sums with amix."""
    if not items:
        write_wav(out_path, np.zeros((int(total * SR), 2), np.float32))
        return out_path
    args, chains = [], []
    for k, it in enumerate(items):
        if it.get("loop"):
            args += ["-stream_loop", "-1"]
        args += ["-i", it["path"]]
        L = it["seg_end"] - it["seg_start"]
        ch = (f"[{k}:a]aformat=sample_fmts=fltp:sample_rates={SR}:channel_layouts=stereo,"
              f"atrim=start={it['seg_start']:.4f}:end={it['seg_end']:.4f},asetpts=PTS-STARTPTS,"
              f"volume={it['gain_db']:.2f}dB")
        fi = max(0.002, it.get("fade_in", 0.002))
        ch += f",afade=t=in:st=0:d={fi:.3f}"
        fo = it.get("fade_out", 0.0)
        if fo > 0:
            ch += f",afade=t=out:st={max(0.0, L - fo):.4f}:d={fo:.3f}"
        ms = int(round(it["place"] * 1000))
        if ms > 0:
            ch += f",adelay={ms}:all=1"
        chains.append(ch + f"[c{k}]")
    graph = ";".join(chains) + ";" + "".join(f"[c{k}]" for k in range(len(items))) + \
        f"amix=inputs={len(items)}:normalize=0:duration=longest:dropout_transition=0,apad,atrim=0:{total:.4f}[out]"
    gpath = os.path.join(work, os.path.basename(out_path) + ".graph.txt")
    with open(gpath, "w") as fh:
        fh.write(graph)
    ff(args + ["-filter_complex_script", gpath, "-map", "[out]", "-c:a", "pcm_f32le", "-ar", str(SR), out_path])
    return out_path


def multiply(a_path, env_path, out_path):
    ff(["-i", a_path, "-i", env_path, "-filter_complex", "[0:a][1:a]amultiply[o]", "-map", "[o]", "-c:a", "pcm_f32le", out_path])
    return out_path


def gain_file(in_path, db, out_path):
    ff(["-i", in_path, "-af", f"volume={db:.3f}dB", "-c:a", "pcm_f32le", out_path])
    return out_path


def level_in(path, iv):
    return ebur128(path, pre_filter=aselect_expr(iv))["I"]


def mix(sound_path, out_prefix, work=None, keep_stems=True, log=print):
    t0 = time.time()
    snd = json.load(open(sound_path))
    fps, D = snd["fps"], snd["durationFrames"]
    total = D / fps
    work = work or os.path.join("/tmp", "sound_mix_" + snd["episode"])
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    lo, du = snd["loudness"], snd["ducking"]
    vo = snd["voice"]
    off_s = vo["offsetFrames"] / fps
    words = json.load(open(os.path.join(ROOT, vo["words"])))
    speech = speech_intervals(words, off_s)
    bridged = speech_intervals(words, off_s, du.get("bridgeGapS", 0.8))
    sil = [(s["from"] / fps, s["to"] / fps, s["buses"]) for s in snd.get("silences", [])]
    report = {"sound": os.path.relpath(sound_path, ROOT), "sources": {}}

    # 1. voice
    voice = os.path.join(work, "voice.wav")
    ff(["-i", os.path.join(ROOT, vo["file"]), "-af",
        f"aformat=sample_fmts=fltp:sample_rates={SR}:channel_layouts=stereo,volume={vo.get('gainDB', 0):.2f}dB,"
        f"adelay={int(round(off_s*1000))}:all=1,apad,atrim=0:{total:.4f}", "-c:a", "pcm_f32le", voice])
    lev = vo.get("leveler", {"maxBoostDB": 6.0, "maxCutDB": 4.0, "smoothS": 1.2})
    if lev:
        # slow VO level rider: pull 3 s short-term loudness of the narration toward its median (S-1 short-term range)
        m = ebur128(voice)
        ts = np.array([t for t, _ in m["S"]]) - 1.5          # ebur128 S is a trailing 3 s window: centre it
        sv = np.array([v for _, v in m["S"]])
        live = np.array([any(a <= t <= b for a, b in bridged) for t in ts]) & (sv > -60)
        ref = float(np.median(sv[live]))
        g = np.where(live, np.clip(ref - sv, -lev["maxCutDB"], lev["maxBoostDB"]), np.nan)
        for i in range(len(g)):                              # hold the last gain across gaps
            if np.isnan(g[i]):
                g[i] = g[i - 1] if i else 0.0
        rate = 1.0 / max(1e-3, np.median(np.diff(ts)))
        g = smooth_gain(g, rate, lev["smoothS"] * 1000, lev["smoothS"] * 1000)
        ns = int(round(total * SR))
        lin = (10 ** (np.interp(np.arange(ns) / SR, ts, g) / 20)).astype(np.float32)
        env_v = write_wav(os.path.join(work, "env_voice.wav"), np.stack([lin, lin], axis=1))
        raw = os.path.join(work, "voice_raw.wav")
        os.replace(voice, raw)
        multiply(raw, env_v, voice)
        report["voice_leveler"] = {"refS": ref, "gain_dB_min": float(g.min()), "gain_dB_max": float(g.max())}
        log(f"voice leveler: ref S {ref:.1f} LUFS, gain {g.min():+.1f}..{g.max():+.1f} dB")
    V = level_in(voice, speech)      # voice loudness over the speech intervals only (same gate the QC uses)
    log(f"voice loudness over speech {V:.2f} LUFS")

    # 2. sfx bus
    items = []
    for c in snd["cues"]:
        info = sfx_library.info(c["sfx"])
        report["sources"][c["sfx"]] = info["source"]
        t_anchor = landmark(info, c["anchor"])
        if c["anchor"] == "end":
            seg_end = t_anchor
            seg_start = max(0.0, seg_end - c.get("dur", seg_end))
        else:
            seg_start = max(0.0, t_anchor - 0.4) if c["anchor"] == "peak" else (max(0.0, t_anchor - 0.004) if c["anchor"] == "onset" else 0.0)
            seg_end = min(info["dur"], seg_start + c["dur"]) if c.get("dur") else info["dur"]
        place = c["at"] / fps - (t_anchor - seg_start)
        if place < 0:
            seg_start -= place
            place = 0.0
        if seg_end - seg_start < 0.01:
            continue
        items.append({"path": info["path"], "seg_start": seg_start, "seg_end": seg_end, "place": place,
                      "gain_db": V + c["relDB"] - info["M_max"],
                      "fade_in": 0.06 if c["type"] == "riser" else 0.002, "fade_out": c.get("fadeOutMs", 10) / 1000})
    sfx_raw = build_bus(items, total, os.path.join(work, "sfx_raw.wav"), work)

    # 3. ambience bus
    amb_ref = V + du["ambienceGapDB"]
    items = []
    for b in snd["beds"]:
        info = sfx_library.info(b["sfx"])
        report["sources"][b["sfx"]] = info["source"]
        L = (b["to"] - b["from"]) / fps
        items.append({"path": info["path"], "loop": True, "seg_start": 0.0, "seg_end": L, "place": b["from"] / fps,
                      "gain_db": amb_ref + b["relDB"] - info["I"],
                      "fade_in": b.get("fadeIn", 0) / fps, "fade_out": b.get("fadeOut", 0) / fps})
    amb_raw = build_bus(items, total, os.path.join(work, "amb_raw.wav"), work)

    # 4. music
    m = snd["music"]
    music_raw = os.path.join(work, "music_raw.wav")
    if m["engine"] == "procedural":
        write_wav(music_raw, music_mod.render(m["sections"], fps, D, bpm=m.get("bpm", 110), key=m.get("key", "D minor")))
    # --- music_score: real stems stitched on the energy map, beat-aligned to the cues (factory/sound/score.py)
    elif m["engine"] == "stems":
        import score as score_mod
        xm, report["music_score"] = score_mod.render_music(m, fps, D, snd["cues"])
        write_wav(music_raw, xm)
        report["sources"].update({f"music:{k}": "elevenlabs" for k in report["music_score"]["stems"]})
        log(f"score: {report['music_score']['splices']} splices, cues on beat "
            f"{report['music_score']['alignment'].get('on_beat_frac')} (naive {report['music_score']['alignment_naive'].get('on_beat_frac')})")
    # --- end music_score
    else:
        ff(["-i", os.path.join(ROOT, m["file"]), "-af", f"aformat=sample_fmts=fltp:sample_rates={SR}:channel_layouts=stereo,apad,atrim=0:{total:.4f}",
            "-c:a", "pcm_f32le", music_raw])
    Im = ebur128(music_raw)["I"]
    music_lvl = os.path.join(work, "music_lvl.wav")
    gain_file(music_raw, V + du["musicGapDB"] - Im, music_lvl)

    # 5. ducking + silences
    def sil_for(bus):
        return [(a, b) for a, b, buses in sil if bus in buses]
    music_d = os.path.join(work, "music.wav")
    amb_d = os.path.join(work, "ambience.wav")
    sfx_d = os.path.join(work, "sfx.wav")
    def outro(env):
        # after the last word the music carries the sting at musicOutroDB vs voice (keeps short-term loudness up);
        # the ramp starts from whatever level the music is at, so it applies to both ducking modes
        if "musicOutroDB" not in du:
            return env
        t_last = bridged[-1][1] + 0.05
        tt = np.arange(len(env)) / SR
        ramp = np.clip((tt - t_last) / (du["attackMs"] / 1000), 0, 1)
        return env * (10 ** ((du["musicOutroDB"] - du["musicGapDB"]) * ramp / 20)).astype(np.float32)[:, None]
    env_m = write_wav(os.path.join(work, "env_music.wav"), outro(
        envelope(total, bridged, du["musicSpeechDB"] - du["musicGapDB"], du["attackMs"], du["releaseMs"], sil_for("music"))))
    env_a = write_wav(os.path.join(work, "env_amb.wav"),
                      envelope(total, bridged, du["ambienceSpeechDB"] - du["ambienceGapDB"], du["attackMs"], du["releaseMs"], sil_for("ambience")))
    env_s = write_wav(os.path.join(work, "env_sfx.wav"), envelope(total, [], 0.0, 1, 1, sil_for("sfx")))
    if du["mode"] == "sidechain":
        tmp = os.path.join(work, "music_sc.wav")
        ff(["-i", music_lvl, "-i", voice, "-filter_complex",
            f"[0:a][1:a]sidechaincompress=threshold=0.02:ratio=8:attack={du['attackMs']}:release={du['releaseMs']}:knee=4[o]",
            "-map", "[o]", "-c:a", "pcm_f32le", tmp])
        env_sil = write_wav(os.path.join(work, "env_music_sil.wav"), outro(envelope(total, [], 0.0, 1, 1, sil_for("music"))))
        multiply(tmp, env_sil, music_d)
    else:
        multiply(music_lvl, env_m, music_d)
    multiply(amb_raw, env_a, amb_d)
    multiply(sfx_raw, env_s, sfx_d)

    # closed-loop calibration of bus levels under speech
    cal = {}
    for name, path, target in (("music", music_d, du["musicSpeechDB"]), ("ambience", amb_d, du["ambienceSpeechDB"])):
        for _ in range(2):
            diff = level_in(path, speech) - V
            corr = target - diff
            if abs(corr) < 0.3:
                break
            tmp = path + ".tmp.wav"
            gain_file(path, corr, tmp)
            os.replace(tmp, path)
        cal[name] = level_in(path, speech) - V
    log(f"under speech: music {cal['music']:+.2f} dB, ambience {cal['ambience']:+.2f} dB vs voice")
    # --- music_score: closed-loop outro level. A real score's payoff cue can be several dB hotter (or softer) than
    # the bed it was calibrated on under speech, so trim the post-last-word ramp toward musicOutroDB as well.
    if "musicOutroDB" in du and total - bridged[-1][1] > 0.8:
        t_last = bridged[-1][1] + 0.05
        win = [(t_last + 0.3, total)]
        for _ in range(2):
            corr = du["musicOutroDB"] - (level_in(music_d, win) - V)
            if abs(corr) < 0.5:
                break
            tt = np.arange(int(round(total * SR))) / SR
            ramp = np.clip((tt - t_last) / (du["attackMs"] / 1000), 0, 1)
            g = (10 ** (corr * ramp / 20)).astype(np.float32)
            env_o = write_wav(os.path.join(work, "env_music_outro.wav"), np.stack([g, g], axis=1))
            tmp = music_d + ".tmp.wav"
            multiply(music_d, env_o, tmp)
            os.replace(tmp, music_d)
        cal["music_outro"] = level_in(music_d, win) - V
        log(f"outro: music {cal['music_outro']:+.2f} dB vs voice (target {du['musicOutroDB']:+.1f})")
    # --- end music_score

    # 6. master
    premix = os.path.join(work, "premix.wav")
    ff(["-i", voice, "-i", music_d, "-i", amb_d, "-i", sfx_d, "-filter_complex",
        "[0:a][1:a][2:a][3:a]amix=inputs=4:normalize=0:duration=longest[o]", "-map", "[o]", "-c:a", "pcm_f32le", premix])
    target = lo["integratedLUFS"]
    ceiling = lo.get("limiterCeilingDBFS", -2.0)
    I_pre = ebur128(premix)["I"]
    gain = target - I_pre
    out_wav = out_prefix + ".wav"
    out_m4a = out_prefix + ".m4a"
    os.makedirs(os.path.dirname(os.path.abspath(out_wav)), exist_ok=True)
    for attempt in range(4):
        lim = 10 ** (ceiling / 20)
        ff(["-i", premix, "-af",
            f"volume={gain:.3f}dB,aresample={4*SR},alimiter=limit={lim:.4f}:level=false:attack=2:release=80:asc=1,aresample={SR}",
            "-c:a", "pcm_s24le", "-ar", str(SR), out_wav])
        meas = ebur128(out_wav)
        # --- music_score: band-limit before AAC. ffmpeg's aac encoder drops the top octave and the resulting
        # reconstruction overshoot on dense real music reached +1.5..+3.5 dB over the wav's true peak.
        lp = lo.get("m4aLowpassHz", 16000)
        ff(["-i", out_wav] + (["-af", f"lowpass=f={lp}:poles=2"] if lp else []) +
           ["-c:a", "aac", "-b:a", "256k", "-ar", str(SR), "-movflags", "+faststart", out_m4a])
        # --- end music_score
        meas_m4a = ebur128(out_m4a)
        log(f"master pass {attempt}: gain {gain:+.2f} dB ceiling {ceiling:.1f} dBFS -> wav I {meas['I']:.2f} TP {meas['TP']:.2f}; "
            f"m4a I {meas_m4a['I']:.2f} TP {meas_m4a['TP']:.2f}")
        ok_i = abs(meas_m4a["I"] - target) <= 0.3 and abs(meas["I"] - target) <= 0.3
        ok_tp = meas["TP"] <= lo["truePeakDBTP"] and meas_m4a["TP"] <= lo["truePeakDBTP"]
        if ok_i and ok_tp:
            break
        gain += target - meas["I"]
        if not ok_tp:
            ceiling -= max(0.3, max(meas["TP"], meas_m4a["TP"]) - lo["truePeakDBTP"] + 0.1)

    # mixed-in stems at master gain, for QC / finishing
    stems = {}
    if keep_stems:
        sd = out_prefix + "_stems"
        os.makedirs(sd, exist_ok=True)
        for name, p in (("voice", voice), ("music", music_d), ("ambience", amb_d), ("sfx", sfx_d)):
            stems[name] = gain_file(p, gain, os.path.join(sd, name + ".wav"))
        # everything but the voice: the P-5 silence check runs on this
        bg = os.path.join(sd, "background.wav")
        ff(["-i", stems["music"], "-i", stems["ambience"], "-i", stems["sfx"], "-filter_complex",
            "[0:a][1:a][2:a]amix=inputs=3:normalize=0[o]", "-map", "[o]", "-c:a", "pcm_f32le", bg])
        stems["background"] = bg
    report.update({
        "voice_LUFS_premaster": V, "master_gain_dB": gain, "limiter_ceiling_dBFS": ceiling,
        "wav": {"path": os.path.relpath(out_wav, ROOT), "I": meas["I"], "TP": meas["TP"], "LRA": meas["LRA"]},
        "m4a": {"path": os.path.relpath(out_m4a, ROOT), "I": meas_m4a["I"], "TP": meas_m4a["TP"], "LRA": meas_m4a["LRA"]},
        "under_speech_dB": cal, "stems": {k: os.path.relpath(v, ROOT) for k, v in stems.items()},
        "seconds": round(time.time() - t0, 1),
    })
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sound", required=True)
    ap.add_argument("--out", required=True, help="output prefix, e.g. episodes/sentinel/audio/mix_v1")
    ap.add_argument("--work", default=None)
    ap.add_argument("--no-qc", action="store_true")
    a = ap.parse_args()
    rep = mix(os.path.abspath(a.sound), os.path.abspath(a.out), a.work)
    if not a.no_qc:
        import qc
        rep["qc"] = qc.check(os.path.abspath(a.sound), rep)
    with open(os.path.abspath(a.out) + ".report.json", "w") as fh:
        json.dump(rep, fh, indent=1)
    print(json.dumps({k: rep[k] for k in ("wav", "m4a", "under_speech_dB")}, indent=1))
    if "qc" in rep:
        for c in rep["qc"]["checks"]:
            print(f"  [{'PASS' if c['pass'] else ('----' if c['pass'] is None else 'FAIL')}] {c['name']}: {c['value']}")


if __name__ == "__main__":
    main()
