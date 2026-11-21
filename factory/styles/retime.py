"""Retime an episode.json to another frame rate (e.g. 30 -> 24 fps for documentary_naturalistic).

Every frame-valued field of the episode spec (cloud/spec/episode.schema.json plus the v4 extensions: direction,
perf, props, overlays, weather) is mapped with the same function f -> round(f * new / old), so shot boundaries stay
contiguous, narration sync is kept in seconds (audio.offsetFrames is retimed too; word timings are in seconds) and
keyed lists stay sorted. Frame DURATIONS (blend, in/out, dur, tau) are scaled and kept >= 1. Sentinel "before the
start" keys (frame <= -1000, e.g. stance [[-10000, "helm"]]) are kept as they are.
"""
from __future__ import annotations

import copy
import math

SENTINEL = -1000


def _fr(f, r):
    if not isinstance(f, (int, float)) or isinstance(f, bool):
        return f
    if f <= SENTINEL:
        return f
    return int(math.floor(f * r + 0.5))


def _dur(d, r):
    if not isinstance(d, (int, float)) or isinstance(d, bool):
        return d
    return max(1, int(math.floor(d * r + 0.5))) if d > 0 else d


def _is_keyed(v):
    return (isinstance(v, list) and v and all(isinstance(k, list) and len(k) == 2 and isinstance(k[0], (int, float))
                                              and not isinstance(k[0], bool) for k in v))


def _keys(v, r):
    """[[f, value], ...] -> retimed, strictly increasing where the source was (steps written as f, f+1 survive)."""
    if not _is_keyed(v):
        return v
    out = []
    for i, (f, val) in enumerate(v):
        nf = _fr(f, r)
        if out and f > v[i - 1][0] and nf <= out[-1][0] and out[-1][0] > SENTINEL:
            nf = out[-1][0] + 1
        out.append([nf, val])
    return out


def _span(d, r, a="from", b="to"):
    if a in d:
        d[a] = _fr(d[a], r)
    if b in d:
        d[b] = _fr(d[b], r)
        if a in d and d[b] <= d[a]:
            d[b] = d[a] + 1


def retime_episode(ep: dict, fps: int) -> dict:
    """Deep copy of `ep` at `fps`. No-op copy when the rate already matches."""
    out = copy.deepcopy(ep)
    old = float(ep.get("fps", 30))
    if int(fps) == int(old):
        return out
    r = float(fps) / old
    out["fps"] = int(fps)
    if "durationFrames" in out:
        out["durationFrames"] = max(1, _fr(out["durationFrames"], r))
    au = out.get("audio") or {}
    if "offsetFrames" in au:
        au["offsetFrames"] = _fr(au["offsetFrames"], r)
    for c in out.get("captions") or []:
        _span(c, r)
    for s in out.get("shots") or []:
        _retime_shot(s, r)
    src = out.setdefault("source", {})
    if isinstance(src, dict):
        src["retimed"] = {"from_fps": int(old), "to_fps": int(fps), "by": "factory/styles/retime.py"}
    return out


def _retime_shot(s, r):
    _span(s, r)
    if "keyFrame" in s:
        s["keyFrame"] = min(max(_fr(s["keyFrame"], r), s["from"]), s["to"] - 1)
    cam = s.get("camera") or {}
    keys = cam.get("keys") or []
    prev = None
    for k in keys:
        nf = _fr(k["f"], r)
        if prev is not None and nf <= prev:
            nf = prev + 1
        k["f"] = prev = nf
    for sh in cam.get("shakes") or []:
        sh["at"] = _fr(sh.get("at"), r)
        if "tau" in sh:
            sh["tau"] = round(sh["tau"] * r, 4)
    for name in ("handheld", "drift"):
        cam[name] = _keys(cam.get(name), r) if _is_keyed(cam.get(name)) else cam.get(name)
        if cam[name] is None:
            cam.pop(name)
    y = s.get("yacht")
    if isinstance(y, dict):
        for k, v in list(y.items()):
            if _is_keyed(v):
                y[k] = _keys(v, r)
        if "hit_frame" in y:
            y["hit_frame"] = _fr(y["hit_frame"], r)
    if _is_keyed(s.get("fires")):
        s["fires"] = _keys(s["fires"], r)
    for a in s.get("actors") or []:
        perf = a.get("perf") or {}
        if _is_keyed(perf.get("stance")):
            perf["stance"] = _keys(perf["stance"], r)
        if "blend" in perf:
            perf["blend"] = _dur(perf["blend"], r)
        for p in perf.get("poses") or []:
            _span(p, r)
            for k in ("in", "out"):
                if k in p:
                    p[k] = _dur(p[k], r)
        for v in perf.get("verbs") or []:
            v["at"] = _fr(v.get("at"), r)
            if "dur" in v:
                v["dur"] = _dur(v["dur"], r)
        for k, v in list(perf.items()):
            if k not in ("stance",) and _is_keyed(v):
                perf[k] = _keys(v, r)
        for t in a.get("tracks") or []:
            if "from" in t:
                t["from"] = _fr(t["from"], r)
            if "to" in t:
                t["to"] = _fr(t["to"], r)
    for p in s.get("props") or []:
        for k, v in list(p.items()):
            if _is_keyed(v):
                p[k] = _keys(v, r)
        if "strobe" in p:
            p["strobe"] = _fr(p["strobe"], r)
    for o in s.get("overlays") or []:
        _span(o, r)
    d = s.get("direction") or {}
    if "centre_from" in d:
        d["centre_from"] = _fr(d["centre_from"], r)
    subj = d.get("subject") or {}
    if _is_keyed(subj.get("track")):
        subj["track"] = _keys(subj["track"], r)
    w = (s.get("env") or {}).get("weather") or {}
    if isinstance(w.get("lightning"), list):
        w["lightning"] = [_fr(f, r) for f in w["lightning"]]
