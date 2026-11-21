"""Tests for the sound stage.  Run: python3 -m unittest factory/sound/test_sound.py -v   (or python3 factory/sound/test_sound.py)

- designer rules on the real Sentinel episode (no audio needed)
- envelope / ducking maths
- an end-to-end mix of a tiny synthetic episode using only procedural placeholder SFX (an empty LIBRARY_STORE),
  which proves the mixer runs without the ElevenLabs files and lands on -14 LUFS / <= -1 dBTP.
"""
import json, os, subprocess, sys, tempfile, unittest
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)


class DesignerSentinel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import designer
        cls.ep = json.load(open(os.path.join(ROOT, "episodes/sentinel/episode_v2.json")))
        words = json.load(open(os.path.join(ROOT, "episodes/sentinel/audio/narration.words.json")))
        cls.snd = designer.design(cls.ep, words, "episodes/sentinel/episode_v2.json", "episodes/sentinel/audio/narration.words.json")

    def cues(self, **kw):
        return [c for c in self.snd["cues"] if all(c.get(k) == v for k, v in kw.items())]

    def test_schema_required_fields(self):
        schema = json.load(open(os.path.join(HERE, "sound.schema.json")))
        for k in schema["required"]:
            self.assertIn(k, self.snd)
        for c in self.snd["cues"]:
            for k in schema["properties"]["cues"]["items"]["required"]:
                self.assertIn(k, c)

    def test_whoosh_on_most_cuts(self):
        cuts = [s["from"] for s in self.ep["shots"]][1:]
        hit = sum(1 for f in cuts if any(c["at"] == f for c in self.cues(type="whoosh")))
        self.assertGreaterEqual(hit / len(cuts), 0.6)

    def test_crunch_impact_near_690(self):
        crunch = self.cues(sfx="coral_crunch")
        self.assertEqual(len(crunch), 1)
        self.assertTrue(680 <= crunch[0]["at"] <= 700, crunch[0]["at"])

    def test_radio_and_beacon_in_C13_C16(self):
        radio = [b for b in self.snd["beds"] if b["sfx"] == "radio_static"]
        self.assertEqual(radio[0]["shots"], ["C13", "C14", "C15", "C16"])
        beeps = self.cues(sfx="beacon_beep")
        self.assertGreaterEqual(len(beeps), 3)
        self.assertTrue(all(c["shot"] in ("C15", "C16") for c in beeps))

    def test_helicopter_storm_island_beds(self):
        beds = {b["id"]: b for b in self.snd["beds"]}
        self.assertEqual(beds["bed_heli"]["shots"], ["D26"])
        self.assertEqual(beds["bed_storm"]["shots"], ["D23", "D24", "D25"])
        jungle = [s for b in self.snd["beds"] if b["sfx"] == "jungle_night" for s in b["shots"]]
        self.assertIn("A08", jungle)
        self.assertNotIn("B10", jungle)
        fires = [s for b in self.snd["beds"] if b["sfx"] == "fire_crackle" for s in b["shots"]]
        self.assertIn("A09", fires)

    def test_risers_end_on_reveals_and_payoff_silence(self):
        sil = self.snd["silences"][0]
        self.assertTrue(0.3 <= (sil["to"] - sil["from"]) / 30 <= 0.8)
        payoff = next(r for r in self.snd["reveals"] if r["kind"] == "payoff")
        self.assertEqual(sil["to"], payoff["at"])
        for r in self.snd["reveals"]:
            if r["kind"] != "hook":
                self.assertTrue(any(c["at"] == r["riserEnd"] for c in self.cues(type="riser")), r["id"])
        # nothing transient inside the silence
        self.assertFalse([c for c in self.snd["cues"] if sil["from"] <= c["at"] < sil["to"] and c["transient"]])

    def test_density(self):
        tr = sorted(c["at"] for c in self.snd["cues"] if c["transient"])
        self.assertLessEqual(max(sum(1 for y in tr if x <= y < x + 15) for x in tr), 3)
        per_min = len(tr) / (self.snd["durationFrames"] / 30 / 60)
        self.assertTrue(25 <= per_min <= 45, per_min)

    def test_music_map(self):
        sec = self.snd["music"]["sections"]
        self.assertEqual(sec[0]["from"], 0)
        self.assertEqual(sec[-1]["to"], self.snd["durationFrames"])
        self.assertLessEqual(max(s["to"] - s["from"] for s in sec), 450)
        for a, b in zip(sec, sec[1:]):
            self.assertEqual(a["to"], b["from"])


class Envelope(unittest.TestCase):
    def test_duck_depth_and_silence(self):
        from mixer import envelope
        env = envelope(4.0, [(1.0, 2.0)], -12.0, 75, 320, silences=[(3.0, 3.5)])[:, 0]
        sr = 48000
        db = lambda t: 20 * np.log10(env[int(t * sr)] + 1e-12)
        self.assertAlmostEqual(db(0.5), 0.0, delta=0.1)
        self.assertAlmostEqual(db(1.5), -12.0, delta=0.2)      # fully ducked mid-word
        self.assertLess(db(1.0), -6.0)                          # attack pre-rolled before the word
        self.assertGreater(db(2.9), -1.0)                       # released
        self.assertEqual(env[int(3.2 * sr)], 0.0)               # hard silence


class EndToEndProcedural(unittest.TestCase):
    def test_tiny_episode_mix(self):
        import designer
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, LIBRARY_STORE=os.path.join(td, "store"))
            voice = os.path.join(td, "vo.wav")
            # "narration": 6 syllable-ish tone bursts at speech-like loudness
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "aevalsrc='0.3*sin(2*PI*180*t)*(0.6+0.4*sin(2*PI*4*t))*gt(sin(2*PI*0.5*t+0.3),-0.2)':d=9:s=48000",
                            voice], check=True)
            words = [{"w": f"w{i}", "s": 0.5 + i * 1.3, "e": 1.5 + i * 1.3} for i in range(6)]
            words[3]["w"] = "crunch."
            wpath = os.path.join(td, "w.json")
            json.dump(words, open(wpath, "w"))
            cam = lambda z: {"space": "yacht", "keys": [{"f": 0, "cam": [0, 2, z], "look": [0, 1, 0], "fov": 30}, {"f": 30, "cam": [0, 2, z + 1], "look": [0, 1, 0], "fov": 30}]}
            ep = {"id": "tiny", "fps": 30, "durationFrames": 300, "audio": {"narration": voice, "wordsJson": wpath, "offsetFrames": 15},
                  "shots": [{"id": "S1", "from": 0, "to": 100, "camera": cam(-5)}, {"id": "S2", "from": 100, "to": 200, "camera": cam(5)},
                            {"id": "S3", "from": 200, "to": 300, "camera": cam(-9)}],
                  "captions": [{"from": 10, "to": 90, "big": "a"}, {"from": 240, "to": 300, "big": "end", "tone": "red"}]}
            epath = os.path.join(td, "ep.json")
            json.dump(ep, open(epath, "w"))
            snd = designer.design(ep, words, epath, wpath)
            spath = os.path.join(td, "sound.json")
            json.dump(snd, open(spath, "w"))
            out = os.path.join(td, "mix")
            code = ("import sys,json; sys.path.insert(0,%r); import mixer, qc; r=mixer.mix(%r,%r,%r,log=lambda *a:None);"
                    "r['qc']=qc.check(%r,r); print(json.dumps(r))") % (HERE, spath, out, os.path.join(td, "work"), spath)
            p = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr[-3000:])
            rep = json.loads(p.stdout.strip().splitlines()[-1])
            self.assertEqual(set(rep["sources"].values()), {"procedural"})
            self.assertLessEqual(abs(rep["m4a"]["I"] + 14.0), 1.0)
            self.assertLessEqual(rep["m4a"]["TP"], -1.0)
            self.assertTrue(os.path.getsize(out + ".m4a") > 10000)
            checks = {c["name"]: c for c in rep["qc"]["checks"]}
            self.assertTrue(checks["music under voice during speech"]["pass"], checks["music under voice during speech"])
            self.assertTrue(checks["exactly one 0.3-0.8 s silence (< -40 dBFS) right before the payoff"]["pass"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
