"""Sound designer: derive sound.json from episode.json + narration word timings, by rule.

Rules (ENGAGEMENT_RECIPE section 6 + P-5):
  - Reveals: hook (frame 0), title card (caption at 'low'), keyword hits ("crunch"), step badges ("Step one..."),
    midpoint (the reveal nearest 0.45 D inside 0.40-0.55 D) and payoff (the last caption card).
  - Whoosh on cuts (peak on the cut frame), skipped on match cuts, inside the payoff silence and when a cut follows
    the previous whoosh by < 0.6 s; file chosen by camera speed (whip / fast / low).
  - Riser of 1.0-2.5 s ending on every reveal except the hook; the payoff riser lands on the start of the silence.
  - Impact on hook, title, keyword hits, steps, midpoint and payoff.
  - P-5: one 0.5 s hard silence of music, ambience and SFX right before the payoff, impact on the reveal frame.
  - Diegetic foley from the episode: engine sputter on "died", switch clicks on actor 'press' verbs, radio static +
    squelches across the radio scene (first radio prop shot -> last radio/beacon prop shot), beacon beeps at 1 Hz from
    the beacon pull, helicopter on the shot whose narration says "helicopter", storm (rain + thunder) from "1981 /
    storm / aground" until the helicopter shot, jungle insects on island-facing shots, fire crackle where fires are lit
    and the camera faces the island; ocean + wind beds under everything.
  - UI ticks on emphasised caption cards (caption.tone set), dropped if another cue is within 4 frames.
  - Density guard: never more than 3 transient onsets in any 0.5 s window (drop ui, then whoosh).
  - Music energy map: hook 4, context 3, escalation 4, pre-midpoint hold 2, midpoint 5, escalation 4 with step
    changes, storm/flashback 3 (dark), pre-payoff 0, payoff 5 with a hard stop; sections split so none exceeds 15 s.

Usage: python3 -m factory.sound.designer --episode episodes/sentinel/episode_v2.json --out episodes/sentinel/sound.json
"""
import argparse, json, math, os, re

NUMBER_WORDS = {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"}
WHOOSHES = ["whoosh_fast", "whoosh_low", "whoosh_whip"]
RISERS = ["riser_noise", "riser_reverse"]

# relDB: cue max-momentary loudness vs voice integrated loudness; bed loudness vs ambience bus reference.
LEVEL = {
    "whoosh": -9.0, "whoosh_low": -8.0, "whoosh_whip": -11.0,
    "riser": -7.0, "impact": -3.0, "impact_big": 0.0, "crunch": 1.0, "thunder": -4.0,
    "engine": -5.0, "click": -12.0, "squelch": -13.0, "beep": -15.0, "ui": -20.0,
}


def clean(w):
    return re.sub(r"[^a-z0-9']", "", w.lower())


def word_frames(words, fps, offset):
    return [{"w": w["w"], "c": clean(w["w"]), "f0": int(round(w["s"] * fps)) + offset,
             "f1": int(round(w["e"] * fps)) + offset} for w in words]


def shot_at(shots, f):
    for s in shots:
        if s["from"] <= f < s["to"]:
            return s
    return shots[-1]


def shot_words(shot, wf):
    return [w for w in wf if shot["from"] <= w["f0"] < shot["to"]]


def cam_speed(shot, n=6):
    """Camera translation speed (units/frame) over the first n frames: separates whip/crash moves from drifts."""
    keys = shot["camera"]["keys"]
    k0 = keys[0]
    k1 = next((k for k in keys if k["f"] >= k0["f"] + n), keys[-1])
    if k1 is k0:
        return 0.0
    # translation normalised by subject distance (so yacht-space and world-space moves compare), plus zoom
    dist = max(0.5, math.dist(k0["cam"], k0.get("look", k0["cam"])))
    d = math.dist(k0["cam"], k1["cam"]) / dist
    fov = abs(k1.get("fov", 0) - k0.get("fov", 0)) / max(1.0, k0.get("fov", 30))
    return (d + fov) / max(1, k1["f"] - k0["f"])


def is_match_cut(prev, nxt):
    """Continuous camera across the cut (same space, camera within 0.5 units): no whoosh."""
    a, b = prev["camera"], nxt["camera"]
    if a.get("space") != b.get("space"):
        return False
    return math.dist(a["keys"][-1]["cam"], b["keys"][0]["cam"]) < 0.5


def faces_island(shot):
    cam = shot["camera"]
    if cam.get("space") == "world":
        return True
    look = cam["keys"][0].get("look", [0, 0, 0])
    return look[2] > 1.0   # yacht space: +z is the bow, which points at the island in this rig


def has_prop(shot, name):
    return any(p.get("prop") == name for p in shot.get("props", []))


def perf_events(shot, kind):
    out = []
    for a in shot.get("actors", []):
        perf = a.get("perf", {})
        for v in perf.get("verbs", []):
            if kind in v["verb"]:
                out.append(v)
        for p in perf.get("poses", []):
            if kind in p["pose"]:
                out.append(p)
    return out


# --- style system hook (factory/styles): music palette + SFX density from episode.style.music --------------
HOUSE_MUSIC = {"engine": "procedural", "bpm": 110, "key": "D minor", "energy_max": 5,
               "sfx_density": {"max_transients": 3, "window_s": 0.5, "whoosh_on_cuts": True, "ui_ticks": True}}


def music_palette(ep):
    m = dict(HOUSE_MUSIC)
    sty = (ep.get("style") or {}).get("music") or {}
    m.update({k: v for k, v in sty.items() if k != "sfx_density"})
    m["sfx_density"] = {**HOUSE_MUSIC["sfx_density"], **(sty.get("sfx_density") or {})}
    m["style"] = (ep.get("style") or {}).get("id")
    return m
# --- end style system hook ---------------------------------------------------------------------------------


def design(ep, words, episode_path="", words_path=""):
    fps = ep["fps"]
    pal = music_palette(ep)  # style system hook
    D = ep["durationFrames"]
    offset = ep.get("audio", {}).get("offsetFrames", 0)
    shots = sorted(ep["shots"], key=lambda s: s["from"])
    wf = word_frames(words, fps, offset)
    caps = sorted(ep.get("captions", []), key=lambda c: c["from"])
    cues, beds, notes = [], [], []

    def cue(type_, sfx, at, anchor, rel, **kw):
        c = {"id": f"{type_}_{len(cues):03d}", "type": type_, "sfx": sfx, "at": int(at), "anchor": anchor,
             "relDB": rel, "transient": type_ in ("whoosh", "impact", "spot", "ui"), "shot": shot_at(shots, at)["id"]}
        c.update(kw)
        cues.append(c)
        return c

    # ---------------- reveals ----------------
    reveals = [{"id": "hook", "kind": "hook", "at": 0}]
    title = next((c for c in caps if c.get("at") == "low"), None)
    if title:
        reveals.append({"id": "title", "kind": "title", "at": title["from"], "word": title.get("big", "")})
    for i, w in enumerate(wf):
        if w["c"] == "step" and i + 1 < len(wf) and wf[i + 1]["c"] in NUMBER_WORDS:
            reveals.append({"id": f"step_{wf[i+1]['c']}", "kind": "step", "at": w["f0"], "word": f"{w['w']} {wf[i+1]['w']}"})
        if w["c"] == "crunch":
            reveals.append({"id": "crunch", "kind": "keyword", "at": w["f0"], "word": w["w"]})
    payoff_at = caps[-1]["from"] if caps else shots[-1]["from"]
    reveals.append({"id": "payoff", "kind": "payoff", "at": payoff_at, "word": caps[-1].get("big", "") if caps else ""})
    reveals.sort(key=lambda r: r["at"])
    mids = [r for r in reveals if r["kind"] in ("step", "keyword", "title") and 0.40 * D <= r["at"] <= 0.55 * D]
    if mids:
        m = min(mids, key=lambda r: abs(r["at"] - 0.45 * D))
        m["midpoint"] = True
        notes.append(f"midpoint reveal = {m['id']} at frame {m['at']} ({m['at']/D:.2f} D)")

    # ---------------- P-5 silence ----------------
    sil_len = int(round(0.5 * fps))
    silence = {"from": payoff_at - sil_len, "to": payoff_at, "buses": ["music", "ambience", "sfx"],
               "reason": "P-5 hard silence before the payoff reveal"}
    for r in reveals:
        r["riserEnd"] = silence["from"] if r["kind"] == "payoff" else r["at"]

    def in_silence(f, pad=0):
        return silence["from"] - pad <= f < silence["to"]

    # ---------------- risers + impacts on reveals ----------------
    prev_end = 0
    for i, r in enumerate(reveals):
        if r["kind"] != "hook":
            end = r["riserEnd"]
            room = (end - prev_end) / fps
            dur = min(2.5, room - 0.1)
            if dur >= 1.0:
                cue("riser", RISERS[i % 2], end, "end", LEVEL["riser"], dur=round(dur, 2), reveal=r["id"],
                    reason=f"riser into {r['id']}")
            else:
                notes.append(f"no riser before {r['id']}: only {room:.2f} s since the previous reveal")
        big = r.get("midpoint") or r["kind"] in ("payoff", "hook")
        if r["id"] == "crunch":
            cue("impact", "coral_crunch", r["at"], "onset", LEVEL["crunch"], reveal=r["id"], reason="hull hits the reef")
            cue("impact", "impact_boom", r["at"], "onset", LEVEL["impact"], reveal=r["id"], reason="sub hit under the crunch")
        else:
            cue("impact", "impact_boom", r["at"], "onset", LEVEL["impact_big" if big else "impact"], reveal=r["id"],
                reason=f"impact on {r['kind']}")
        prev_end = r["at"]

    # ---------------- whooshes on cuts ----------------
    speeds = [cam_speed(s) for s in shots]
    fast_thr = sorted(speeds)[int(0.75 * (len(speeds) - 1))]
    last_whoosh = -10**9
    n_cuts = 0
    for prev, nxt, sp in zip(shots, shots[1:], speeds[1:]):
        f = nxt["from"]
        n_cuts += 1
        if not pal["sfx_density"]["whoosh_on_cuts"]:  # style system hook
            continue
        if in_silence(f, pad=3):
            continue
        if is_match_cut(prev, nxt):
            notes.append(f"match cut {prev['id']}->{nxt['id']}: no whoosh")
            continue
        if f - last_whoosh < 0.6 * fps:
            continue
        if sp >= fast_thr and sp > 0:
            name = "whoosh_whip"
        elif nxt["camera"].get("space") == "world" or prev["camera"].get("space") != nxt["camera"].get("space"):
            name = "whoosh_low"
        else:
            name = "whoosh_fast"
        cue("whoosh", name, f, "peak", LEVEL.get(name, LEVEL["whoosh"]), dur=0.6, fadeOutMs=80,
            reason=f"cut {prev['id']}->{nxt['id']}")
        last_whoosh = f

    # ---------------- diegetic foley ----------------
    for w in wf:
        if w["c"] == "died":
            s = shot_at(shots, w["f0"])
            cue("spot", "engine_die", max(s["from"], w["f0"] - 25), "onset", LEVEL["engine"], dur=2.6, fadeOutMs=300,
                reason="engine sputters and dies on 'died'")
            break
    for s in shots:
        for v in perf_events(s, "press"):
            if "at" not in v:
                continue
            taps = [0.3, 0.7] if "twice" in v["verb"] else [0.5]
            for t in taps:
                cue("spot", "switch_click", v["at"] + int(v.get("dur", 10) * t), "onset", LEVEL["click"],
                    reason=f"{v['verb']} on {s['id']}")

    radio_shots = [s for s in shots if has_prop(s, "radio") or has_prop(s, "beacon")]
    if radio_shots and any(has_prop(s, "radio") for s in radio_shots):
        first = next(s for s in shots if has_prop(s, "radio"))
        last = radio_shots[-1]
        beds.append({"id": "bed_radio", "sfx": "radio_static", "from": first["from"], "to": last["to"], "relDB": -2.0,
                     "fadeIn": 3, "fadeOut": 12, "bus": "ambience",
                     "shots": [s["id"] for s in shots if first["from"] <= s["from"] < last["to"]],
                     "reason": "VHF static under the radio scene"})
        squelch = [first["from"] + 2]
        may = next((w for w in wf if w["c"] == "mayday"), None)
        if may:
            squelch.append(may["f1"] + 2)
        for s in shots:
            if has_prop(s, "radio") and s is not first:
                squelch.append(s["from"] + 6)
        kept = []
        for f in sorted(squelch):
            if kept and f - kept[-1] < 10:
                continue
            kept.append(f)
        for f in kept:
            cue("spot", "radio_static", f, "start", LEVEL["squelch"], dur=0.22, fadeOutMs=30, reason="PTT squelch")
    beacon = [s for s in shots if has_prop(s, "beacon")]
    if beacon:
        pulls = [p for s in beacon for p in perf_events(s, "beacon_pull")]
        start = (pulls[0]["to"] if pulls else beacon[0]["from"] + 15)
        f = start
        while f < beacon[-1]["to"] - 5:
            cue("spot", "beacon_beep", f, "onset", LEVEL["beep"], dur=0.28, fadeOutMs=40, reason="EPIRB strobe beep")
            f += fps

    heli_shot = None
    for s in shots:
        if any(w["c"].startswith("helicopter") for w in shot_words(s, wf)):
            heli_shot = s
            beds.append({"id": "bed_heli", "sfx": "helicopter", "from": s["from"], "to": s["to"], "relDB": 2.0,
                         "fadeIn": 20, "fadeOut": 6, "bus": "ambience", "shots": [s["id"]],
                         "reason": "helicopters lift the crew out"})
            break
    storm_start = next((s for s in shots if any(w["c"] in ("1981", "storm", "aground") for w in shot_words(s, wf))), None)
    storm_shots = []
    if storm_start:
        storm_end = heli_shot["from"] if heli_shot and heli_shot["from"] > storm_start["from"] else storm_start["to"]
        storm_shots = [s for s in shots if storm_start["from"] <= s["from"] < storm_end]
        beds.append({"id": "bed_storm", "sfx": "rain_storm", "from": storm_start["from"], "to": storm_end, "relDB": 1.0,
                     "fadeIn": 6, "fadeOut": 20, "bus": "ambience", "shots": [s["id"] for s in storm_shots],
                     "reason": "1981 storm on the reef"})
        cue("impact", "thunder", storm_start["from"] + 4, "onset", LEVEL["thunder"], reason="storm establishes")
        if len(storm_shots) > 1:
            cue("impact", "thunder", storm_shots[1]["from"] + 20, "onset", LEVEL["thunder"] - 3, reason="storm rumble")

    def runs(pred):
        out, cur = [], None
        for s in shots:
            if pred(s):
                if cur and cur[-1]["to"] == s["from"]:
                    cur.append(s)
                else:
                    cur = [s]
                    out.append(cur)
        return out

    storm_ids = {s["id"] for s in storm_shots} | ({heli_shot["id"]} if heli_shot else set())  # flashback scene
    for k, run_ in enumerate(runs(lambda s: faces_island(s) and s["id"] not in storm_ids)):
        dawn = run_[0].get("env", {}).get("dawn", 0)
        beds.append({"id": f"bed_jungle_{k}", "sfx": "jungle_night", "from": run_[0]["from"], "to": run_[-1]["to"],
                     "relDB": -3.0 - 6.0 * dawn, "fadeIn": 8, "fadeOut": 8, "bus": "ambience",
                     "shots": [s["id"] for s in run_], "reason": "island jungle at night (insects)"})
    for k, run_ in enumerate(runs(lambda s: "fires" in s and faces_island(s) and s["id"] not in storm_ids)):
        beds.append({"id": f"bed_fire_{k}", "sfx": "fire_crackle", "from": run_[0]["from"], "to": run_[-1]["to"],
                     "relDB": -4.0, "fadeIn": 10, "fadeOut": 8, "bus": "ambience",
                     "shots": [s["id"] for s in run_], "reason": "fires burning in the trees"})
    beds.insert(0, {"id": "bed_ocean", "sfx": "ocean_waves", "from": 0, "to": D, "relDB": 0.0, "fadeIn": 0, "fadeOut": 0,
                    "bus": "ambience", "shots": ["*"], "reason": "S-6 continuous world bed"})
    beds.insert(1, {"id": "bed_wind", "sfx": "wind_sea", "from": 0, "to": D, "relDB": -4.0, "fadeIn": 0, "fadeOut": 0,
                    "bus": "ambience", "shots": ["*"], "reason": "S-6 night wind"})

    # ---------------- UI ticks on emphasised captions ----------------
    for c in caps if pal["sfx_density"]["ui_ticks"] else []:  # style system hook
        if c.get("tone") and not any(abs(x["at"] - c["from"]) <= 4 and x["transient"] for x in cues) and not in_silence(c["from"]):
            cue("ui", "ui_tick", c["from"], "onset", LEVEL["ui"], reason=f"caption emphasis '{c.get('big','')}'")

    # ---------------- density guard (S-4) ----------------
    win = max(1, int(round(pal["sfx_density"]["window_s"] * fps)))  # style system hook (house: 0.5 s)
    max_tr = int(pal["sfx_density"]["max_transients"])
    prio = {"ui": 0, "whoosh": 1, "spot": 2, "impact": 3}
    while True:
        tr = sorted((c for c in cues if c["transient"]), key=lambda c: c["at"])
        bad = None
        for i in range(len(tr)):
            group = [c for c in tr[i:] if c["at"] < tr[i]["at"] + win]
            if len(group) > max_tr:
                bad = group
                break
        if not bad:
            break
        drop = min(bad, key=lambda c: (prio[c["type"]], -c["at"]))
        notes.append(f"density guard dropped {drop['id']} ({drop['sfx']} @ {drop['at']})")
        cues.remove(drop)

    # ---------------- music energy map (S-3) ----------------
    mid = next((r for r in reveals if r.get("midpoint")), None)
    steps = [r for r in reveals if r["kind"] == "step"]
    first_hit = next((r for r in reveals if r["kind"] == "keyword"), None)
    hook_end = next((s["from"] for s in shots if s["from"] >= 3 * fps), shots[0]["to"])
    bounds = {0: ("hook", 4, True), hook_end: ("context", 3, False)}
    if title:
        bounds[title["from"]] = ("context_title", 3, True)
    if first_hit:
        bounds[first_hit["at"]] = ("escalation_1", 4, True)
    if mid:
        hold = mid["at"] - int(1.5 * fps)
        bounds[hold] = ("pre_midpoint_hold", 2, False)
        bounds[mid["at"]] = ("midpoint", 5, True)
        bounds[mid["at"] + int(6 * fps)] = ("escalation_2", 4, False)
    for r in steps:
        if not mid or r["at"] > mid["at"]:
            bounds.setdefault(r["at"], ("escalation_2", 4, True))
    if storm_shots:
        bounds[storm_shots[0]["from"]] = ("flashback", 3, True)
        after = (heli_shot["to"] if heli_shot else storm_shots[-1]["to"])
        if heli_shot:
            bounds[heli_shot["from"]] = ("rescue", 4, False)
        bounds.setdefault(after, ("escalation_2", 4, False))
    bounds[silence["from"]] = ("pre_payoff", 0, False)
    bounds[payoff_at] = ("payoff", 5, True)
    starts = sorted(f for f in bounds if 0 <= f < D)
    sections = []
    for a, b in zip(starts, starts[1:] + [D]):
        label, energy, hit = bounds[a]
        energy = min(energy, int(pal["energy_max"]))  # style system hook
        n = max(1, math.ceil((b - a) / (15 * fps - 1)))
        for k in range(n):
            fa, fb = a + (b - a) * k // n, a + (b - a) * (k + 1) // n
            sections.append({"id": f"m{len(sections):02d}_{label}", "from": fa, "to": fb, "energy": energy,
                             "label": label, "hit": hit and k == 0, "layer": k,
                             "mood": "dark" if label == "flashback" else ("resolve" if label == "payoff" else "tense")})

    cues.sort(key=lambda c: (c["at"], c["type"]))
    for i, c in enumerate(cues):
        c["id"] = f"{c['type']}_{i:03d}"
    whooshed = sum(1 for c in cues if c["type"] == "whoosh")
    notes.append(f"whoosh on {whooshed}/{n_cuts} cuts ({100*whooshed/max(1,n_cuts):.0f}%)")
    return {
        "$schema": "../../factory/sound/sound.schema.json",
        "version": 1,
        "episode": ep.get("id", ""),
        "fps": fps,
        "durationFrames": D,
        "sampleRate": 48000,
        "source": {"episode": episode_path, "words": words_path, "generator": "factory/sound/designer.py"},
        "loudness": {"integratedLUFS": -14.0, "toleranceLU": 1.0, "truePeakDBTP": -1.0, "limiterCeilingDBFS": -2.0,
                     "shortTermRangeLUFS": [-17.0, -10.0], "musicUnderVoiceDB": [18.0, 22.0], "ambienceUnderVoiceDB": [24.0, 30.0]},
        "voice": {"file": ep.get("audio", {}).get("narration", ""), "words": ep.get("audio", {}).get("wordsJson", words_path),
                  "offsetFrames": offset, "gainDB": 0.0,
                  "leveler": {"maxBoostDB": 6.0, "maxCutDB": 4.0, "smoothS": 1.2}},
        "ducking": {"mode": "envelope", "attackMs": 75, "releaseMs": 320, "bridgeGapS": 0.8,
                    "musicSpeechDB": -20.0, "musicGapDB": -8.0, "musicOutroDB": -1.0, "ambienceSpeechDB": -27.0, "ambienceGapDB": -21.0},
        "beds": beds,
        "cues": cues,
        "music": {"engine": pal["engine"], "bpm": pal["bpm"], "key": pal["key"], "sections": sections,  # style system hook
                  **({"style": pal["style"]} if pal["style"] else {}),
                  **({k: pal[k] for k in ("moods", "instrumentation") if pal.get(k)})},
        "silences": [silence],
        "reveals": reveals,
        "notes": notes,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", required=True)
    ap.add_argument("--words", help="defaults to episode.audio.wordsJson")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    root = os.getcwd()
    ep = json.load(open(a.episode))
    wp = a.words or ep["audio"]["wordsJson"]
    words = json.load(open(os.path.join(root, wp) if not os.path.isabs(wp) else wp))
    snd = design(ep, words, os.path.relpath(a.episode, root), os.path.relpath(wp, root) if os.path.isabs(wp) else wp)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as fh:
        json.dump(snd, fh, indent=1)
    kinds = {}
    for c in snd["cues"]:
        kinds[c["type"]] = kinds.get(c["type"], 0) + 1
    print(f"wrote {a.out}: {len(snd['beds'])} beds, {len(snd['cues'])} cues {kinds}, {len(snd['music']['sections'])} music sections")
    for n in snd["notes"]:
        print("  note:", n)


if __name__ == "__main__":
    main()
