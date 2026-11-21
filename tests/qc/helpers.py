"""Synthetic episodes for QC tests."""
from factory.qc.episode import Episode, Word


def cam_keys(cam, look, n=4, f0=0, step=10, fov=30.0):
    return [{"f": f0 + i * step, "cam": list(cam), "look": list(look), "fov": fov, "ease": "linear"} for i in range(n)]


def hero_shot(sid="S1", f0=0, f1=30, look=None, cam=(0.0, 3.2, 6.0), space="yacht"):
    eye = [0.0, 1.0 + 1.8 * 0.90, 0.0]  # local [0,1,0] + 0.90 * height
    return {
        "id": sid, "from": f0, "to": f1,
        "yacht": {"x": 0, "z": 0, "heading": 0.0},
        "actors": [{"asset": "hero", "space": "yacht", "local": [0.0, 1.0, 0.0], "height": 1.8}],
        "camera": {"space": space, "handheld": 0.0, "drift": 0.0, "keys": cam_keys(cam, look or eye, f0=f0)},
    }


def make_episode(shots=None, captions=None, words=None, frames=None, fps=30):
    shots = shots or [hero_shot()]
    data = {"id": "t", "fps": fps, "width": 1080, "height": 1920, "durationFrames": frames or max(s["to"] for s in shots),
            "shots": shots, "captions": captions or []}
    return Episode(path="/tmp/qc_test_episode.json", root="/tmp", data=data, words=words or [])


def words_from(text, t0=0.1, dt=0.33):
    out, t = [], t0
    for w in text.split():
        out.append(Word(w, t, t + dt * 0.9))
        t += dt
    return out
