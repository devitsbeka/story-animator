"""Procedural underscore rendered from sound.json music sections (S-3 energy map).

FALLBACK ONLY. The real score path is engine "stems" (factory/sound/score.py: ElevenLabs Music stems from
factory/sound/music_manifest.json, or licensed tracks via factory/sound/music_library.py, stitched on the energy map
and beat-aligned to the SFX cues). This placeholder stays so the mixer runs on a machine without the stems.

No music model and no library track: a tempo-locked D-minor score built from sines and filtered noise so the mix
always has a music bus whose energy follows the map. Layers by energy:
  1 pad (minor triad, slow swell)   2 + sub drone   3 + kick on the beat   4 + off-beat hats, 8th bass pulse
  5 + accent toms each bar, brighter pad.  0 = silence (P-5).  A section with hit=true starts on a downbeat boom.
The last section ends with a hard stop (no fade), which supports the loop.
"""
import numpy as np

SR = 48000
A4 = 440.0
# D minor progression (i - VI - III - VII), roots as MIDI notes, triads as semitone offsets.
PROG = [(50, (0, 3, 7)), (46, (0, 4, 7)), (53, (0, 4, 7)), (48, (0, 4, 7))]
DARK = [(50, (0, 3, 7)), (51, (0, 4, 7)), (50, (0, 3, 6)), (49, (0, 4, 7))]   # flashback: i - bII - dim - VII-ish


def mtof(m):
    return A4 * 2 ** ((m - 69) / 12)


def render(sections, fps, duration_frames, bpm=110, seed=7):
    n = int(round(duration_frames / fps * SR))
    out = np.zeros((n, 2), np.float32)
    rng = np.random.default_rng(seed)
    beat = 60.0 / bpm
    t_all = np.arange(n) / SR
    hat = rng.standard_normal(int(0.04 * SR)).astype(np.float32)
    hat = np.diff(hat, prepend=0) * np.exp(-np.arange(len(hat)) / (0.008 * SR))
    for si, s in enumerate(sections):
        a, b = int(round(s["from"] / fps * SR)), int(round(s["to"] / fps * SR))
        e = int(s.get("energy", 0))
        if b <= a or e <= 0:
            continue
        t = t_all[a:b]
        seg = np.zeros((b - a, 2), np.float32)
        prog = DARK if s.get("mood") == "dark" else PROG
        bar = 4 * beat
        # chord changes every 2 bars, continuing through the episode clock so sections stay on the grid
        chord_idx = (np.floor(t / (2 * bar)).astype(int) + si) % len(prog)
        bright = 1.0 + 0.5 * (e >= 5)
        for ci, (root, triad) in enumerate(prog):
            m = chord_idx == ci
            if not m.any():
                continue
            tt = t[m]
            pad = np.zeros_like(tt)
            for k, off in enumerate(triad):
                f = mtof(root + off)
                for det, pan in ((-0.15, 0), (0.15, 1)):
                    ph = 2 * np.pi * (f + det) * tt
                    pad += (np.sin(ph) + 0.25 * bright * np.sin(2 * ph) + 0.1 * bright * np.sin(3 * ph)) / (k + 1.5)
            swell = 0.6 + 0.4 * np.sin(2 * np.pi * tt / (2 * bar) - np.pi / 2)
            pad *= 0.10 * swell
            seg[m, 0] += pad * 0.9
            seg[m, 1] += pad * 1.1
            if e >= 2:
                drone = 0.16 * np.sin(2 * np.pi * mtof(root - 12) * tt) + 0.06 * np.sin(2 * np.pi * mtof(root - 5) * tt)
                seg[m] += drone[:, None]
            if e >= 4:
                # 8th-note bass pulse
                ph8 = (tt / (beat / 2)) % 1.0
                env = np.exp(-ph8 * 6.0)
                bass = 0.12 * env * np.sign(np.sin(2 * np.pi * mtof(root - 12) * tt)) * 0.6
                seg[m] += bass[:, None]
        # percussion on the absolute beat grid
        first_beat = int(np.ceil((a / SR) / beat))
        last_beat = int(np.floor((b / SR) / beat))
        kick_len = int(0.35 * SR)
        kt = np.arange(kick_len) / SR
        kick = (np.sin(2 * np.pi * (50 * kt + 60 * (1 - np.exp(-kt * 30)) / 30)) * np.exp(-kt * 9)).astype(np.float32)
        tom = (np.sin(2 * np.pi * (110 * kt + 80 * (1 - np.exp(-kt * 20)) / 20)) * np.exp(-kt * 7)).astype(np.float32)
        for bi in range(first_beat, last_beat + 1):
            pos = int(round(bi * beat * SR)) - a
            if e >= 3 and 0 <= pos < len(seg):
                L = min(kick_len, len(seg) - pos)
                seg[pos:pos + L] += 0.45 * kick[:L, None]
            if e >= 5 and bi % 4 == 3 and 0 <= pos < len(seg):
                L = min(kick_len, len(seg) - pos)
                seg[pos:pos + L, 0] += 0.25 * tom[:L]
                seg[pos:pos + L, 1] += 0.18 * tom[:L]
            if e >= 4:
                hp = pos + int(beat / 2 * SR)
                if 0 <= hp < len(seg):
                    L = min(len(hat), len(seg) - hp)
                    seg[hp:hp + L, 0] += 0.20 * hat[:L]
                    seg[hp:hp + L, 1] += 0.26 * hat[:L]
        if s.get("hit"):
            L = min(int(1.2 * SR), len(seg))
            ht = np.arange(L) / SR
            boom = 0.6 * np.sin(2 * np.pi * (45 * ht + 40 * (1 - np.exp(-ht * 15)) / 15)) * np.exp(-ht * 3.5)
            seg[:L] += boom[:, None].astype(np.float32)
        # 3 ms de-click ramps at section edges (well under the 3-frame no-fade rule), except a hard stop at the end
        r = int(0.003 * SR)
        seg[:r] *= np.linspace(0, 1, r)[:, None]
        if s["to"] < duration_frames:
            seg[-r:] *= np.linspace(1, 0, r)[:, None]
        out[a:b] += seg
    return out
