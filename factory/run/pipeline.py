"""The episode DAG: idea -> ... -> QC, resumable, with per-stage artifacts / status / cost / time in run.json.

    develop ──► breakdown ──► library ──┐
       └──────► voice ──────────────────┴─► direct ──► previs [APPROVAL GATE] ──► render ──┐
                  └──────────────────────────────┴───► sound ────────────────────────────┴─► finish ──► qc (+ retry loop)

voice only needs story.json, so it runs in parallel with breakdown/library, and direct (stage 4) gets the real word
timings for its cut-on-word check. Stages whose dependencies are done run concurrently (threads; the heavy work is in
subprocesses). A stage that is `done` with its artifacts on disk is skipped on --resume.
"""
import dataclasses
import json
import os
import re
import shutil
import threading
import time
import concurrent.futures as cf

from factory.director.paths import ROOT

from . import costs, finish as finish_mod, previs as previs_mod, render as render_mod, voice as voice_mod
from .state import (AWAITING, DONE, FAILED, PENDING, RUNNING, R_AWAITING, R_BUDGET, R_FAILED, R_PUBLISHED, R_RETURNED,
                    R_RUNNING, RunState)

DEPS = {
    "develop": [], "breakdown": ["develop"], "library": ["breakdown"], "voice": ["develop"],
    "direct": ["library", "voice"], "sound": ["direct", "voice"], "previs": ["direct", "voice"],
    "render": ["previs"], "finish": ["render", "sound"], "qc": ["finish"],
}
ORDER = ["develop", "breakdown", "library", "voice", "direct", "sound", "previs", "render", "finish", "qc"]
NUMBER = {"develop": "1", "breakdown": "2", "library": "3", "direct": "4", "voice": "5a", "sound": "5b", "previs": "6",
          "render": "7", "finish": "8", "qc": "9"}
STUBBABLE = {"voice", "mix", "previs", "render", "finish"}
DEFAULT_EPISODES = os.environ.get("FACTORY_EPISODES_DIR", os.path.join(ROOT, "episodes"))


class AwaitingApproval(Exception):
    pass


class BudgetExceeded(Exception):
    pass


class CostCeilingExceeded(BudgetExceeded):  # quality_gate (L014): one stage over its own ceiling
    pass


class RegressionBlocked(Exception):  # quality_gate: lessons/goldens regress check failed at a gate
    pass


@dataclasses.dataclass
class Options:
    idea: str = ""
    fmt: str = "short"
    style: str = "pixar_night_survival"
    render: str = "local"            # local | farm
    quality: str = "preview"         # preview | final
    offline: bool = False
    auto_approve: bool = False
    stubs: frozenset = frozenset()
    episodes_dir: str = DEFAULT_EPISODES
    fixtures: str = os.path.join(ROOT, "factory", "director", "fixtures", "sentinel")
    model: str = os.environ.get("DIRECTOR_MODEL", "claude-opus-5-5")
    effort: str = "high"
    voice: str = "auto"              # auto | stub | module
    workers: int = 1                 # local render processes
    render_res: str = None           # e.g. 270x480 for a cheap local render
    render_samples: int = None
    render_engine: str = None
    blender: str = None
    previs_res: str = "144x256"
    previs_samples: int = 4
    previs_shots: tuple = ()
    budget: float = None             # USD ceiling for this episode
    max_qc_fixes: int = 1
    shot_gate_pose: str = "warn"     # quality_gate: Blender pose QC in the per-shot gate: enforce | warn | off (auto-off when stubbed / no Blender)
    regress: str = "enforce"         # quality_gate: lessons/goldens regress check at previs + publish: enforce | warn | off
    deliver: bool = True             # quality_gate (L006): PUBLISH produces final/delivery/{episode,episode_mobile}.mp4
    parallel_stages: int = 2
    farm_poll_s: int = 60

    def to_dict(self):
        d = dataclasses.asdict(self)
        d["stubs"] = sorted(self.stubs)
        d["previs_shots"] = list(self.previs_shots)
        return d

    @classmethod
    def from_dict(cls, d):
        names = {f.name for f in dataclasses.fields(cls)}
        o = cls(**{k: v for k, v in d.items() if k in names})
        o.stubs = frozenset(o.stubs or ())
        o.previs_shots = tuple(o.previs_shots or ())
        return o

    def meta(self):
        return {"idea": self.idea, "format": self.fmt, "style": self.style, "render": self.render, "quality": self.quality,
                "offline": self.offline, "stubs": sorted(self.stubs), "autoApprove": self.auto_approve}


def slug(idea, n=6):
    import hashlib
    words = re.findall(r"[a-z0-9]+", idea.lower())[:5]
    return ("-".join(words)[:40].strip("-") or "episode") + "-" + hashlib.sha1(idea.encode()).hexdigest()[:n]


def _rel(p):
    p = os.path.abspath(p)
    return os.path.relpath(p, ROOT) if p.startswith(ROOT + os.sep) else p


def _read(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def _write(p, doc):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".part"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, p)


class Pipeline:
    def __init__(self, opts, episode_id=None, resume=False, fresh=False, from_stage=None, log=print, hooks=None):
        self.o = opts
        self.id = episode_id or slug(opts.idea)
        self.dir = os.path.abspath(os.path.join(opts.episodes_dir, self.id))
        self.hooks = hooks or {}          # tests: {"qc": fn, "farm": obj, "director_client": fn}
        self._log = log
        self._force = set()
        path = os.path.join(self.dir, "run.json")
        if os.path.exists(path) and not fresh:
            if not resume:
                raise FileExistsError(f"{path} exists: pass --resume to continue it (or --fresh to start over)")
            self.st = RunState.load(path)
            if not opts.idea:
                opts.idea = self.st.doc["idea"]
            self.st.set_status(R_RUNNING, options=opts.to_dict())
        else:
            if not opts.idea:
                raise ValueError("an idea is required to start a new run")
            if fresh:
                self._force = {"develop", "breakdown", "direct"}
            self.st = RunState.create(path, {"episodeId": self.id, **opts.meta(), "options": opts.to_dict()}, ORDER)
        if opts.budget is not None:
            self.st.doc["cost"]["budgetUSD"] = opts.budget
        if from_stage:
            self.reset_from(from_stage)
        self.st.save()

    # ------------------------------------------------------------------ utils
    def log(self, msg):
        line = f"[{self.id}] {msg}"
        self._log(line)
        with open(os.path.join(self.dir, "run.log"), "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%H:%M:%S ") + line + "\n")

    def p(self, *a):
        return os.path.join(self.dir, *a)

    def descendants(self, name):
        out, todo = set(), [name]
        while todo:
            n = todo.pop()
            for k, deps in DEPS.items():
                if n in deps and k not in out:
                    out.add(k)
                    todo.append(k)
        return out

    def reset_from(self, name):
        if name not in DEPS:
            raise ValueError(f"unknown stage {name!r}; stages: {ORDER}")
        for s in {name} | self.descendants(name):
            self.st.update_stage(s, status=PENDING)
        if name in ("develop", "breakdown", "direct"):
            self._force.add(name)
        if name in ("previs", "develop", "breakdown", "library", "direct", "voice"):
            self.st.doc["approval"] = None
        self.st.event(f"reset from {name}")

    def stub(self, what):
        return what in self.o.stubs

    def check_budget(self, stage):
        b = self.o.budget
        if b is not None and self.st.spent > b:
            raise BudgetExceeded(f"spent ${self.st.spent:.2f} > budget ${b:.2f} before stage {stage}")
        self.check_ceiling(stage)

    # >>> quality_gate (L014): per-stage cost ceiling + attempts alert
    def check_ceiling(self, stage, after=False):
        cap = costs.stage_ceilings().get(stage)
        spent = float(self.st.stage(stage).get("costUSD") or 0)
        self.st.doc.setdefault("costCeilings", {})[stage] = cap
        if cap is not None and (spent > cap if after else spent >= cap and spent > 0):
            self.st.update_stage(stage, ceilingExceeded={"spentUSD": round(spent, 4), "ceilingUSD": cap})
            raise CostCeilingExceeded(f"stage {stage} spent ${spent:.2f} {'>' if after else '>='} its ceiling ${cap:.2f}")

    def shot_gate(self, gate, max_tries=2):
        """Per-shot checks (factory/direction/shot_checks.py: FRAME-CROP, FRAME-EYES, COLLIDE, VIS, + TIER at final
        quality) on EVERY shot before previs approval and before render. Failing shots go back to stage 4 with the
        failing rules as feedback (max `max_tries` re-directs), then the gate blocks (enforce) or records (warn)."""
        if self.o.regress == "off":
            return {"ok": True, "skipped": True}
        import sys as _sys
        d = os.path.join(ROOT, "factory", "direction")
        if d not in _sys.path:
            _sys.path.insert(0, d)
        import shot_checks
        quality = "final" if (gate == "render" and self.o.quality == "final") else "preview"
        hist = self.st.doc.setdefault("shotGate", {}).setdefault(gate, {"tries": 0, "history": []})
        while True:
            ep = _read(self.p("episode.json"))
            res = shot_checks.check_episode(ep, quality)
            fails = {s: r for s, r in res["failing"].items()}
            pose = self.shot_gate_pose(gate, hist["tries"])
            if pose is not None:
                hist.setdefault("pose", []).append({"try": hist["tries"], "failing": pose["failing"], "mode": self.o.shot_gate_pose,
                                                    "report": pose.get("report"), "error": pose.get("error")})
                if self.o.shot_gate_pose == "enforce":
                    for sid, rules in pose["failing"].items():
                        fails.setdefault(sid, []).extend(rules)
                    res["findings"] = res["findings"] + pose["findings"]
                elif pose["failing"]:
                    self.log(f"shot gate [{gate}] pose QC (warn): {len(pose['failing'])} shot(s): {dict(list(pose['failing'].items())[:4])}")
            hist["history"].append({"try": hist["tries"], "failing": fails})
            hist["ok"] = not fails
            self.st.save()
            if not fails:
                self.log(f"shot gate [{gate}]: all {len(ep['shots'])} shots pass")
                return res
            self.log(f"shot gate [{gate}]: {len(fails)} failing shot(s): {dict(list(fails.items())[:6])}")
            if self.o.regress != "enforce":
                return res
            if hist["tries"] >= max_tries:
                raise RegressionBlocked(f"shot gate before {gate}: {len(fails)} shot(s) still failing after {max_tries} "
                                        f"re-direct(s): {dict(list(fails.items())[:8])}")
            hist["tries"] += 1
            t0 = time.time()
            fb = {"qc_decision": f"SHOT_GATE_{gate.upper()}", "score": None,
                  "failing_rules": [{"id": f["rule"], "section": "FRAMING", "measured": f["measured"], "expected": f["expected"],
                                     "detail": f"shot {f['shot']}"} for f in res["findings"] if f["status"] == "fail"][:40],
                  "shots_to_fix": sorted(fails)}
            self.log(f"shot gate [{gate}]: re-directing {sorted(fails)} (try {hist['tries']}/{max_tries})")
            r = self.stage_direct(t0, feedback=fb)
            self.st.add_cost("direct", r.get("usd", 0.0), time.time() - t0)
            self.check_ceiling("direct", after=True)

    def shot_gate_pose(self, gate, attempt):
        """Blender pose QC (cloud/blender/test/pose_qc.py: seat contact, spine, palms, wrists, finger curl, feet flat +
        natural ankle, grip contact; at the render gate over the full clip with FACE-LIFE) on every hero shot.
        -> {"failing": {shot: [rules]}, "findings": [...]} or None when off / the stage is stubbed / no Blender."""
        mode = self.o.shot_gate_pose
        stage = "previs" if gate == "previs" else "render"
        blender = self.o.blender or os.environ.get("BLENDER", "/opt/blender/blender-4.2.3-linux-x64/blender")
        if mode == "off" or self.stub(stage) or not os.path.exists(blender.split()[0]):
            return None
        out = self.p("qc", f"pose_qc_{gate}_{attempt}.json")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        cmd = [*blender.split(), "-b", "--python-exit-code", "1", "--factory-startup", "-P",
               os.path.join(ROOT, "cloud", "blender", "test", "pose_qc.py"), "--", "--spec", self.p("episode.json"),
               "--max-frames", "1", "--out", out] + (["--full-clip"] if gate == "render" else [])
        try:
            import subprocess as _sp
            p = _sp.run(cmd, capture_output=True, text=True, timeout=3600, cwd=ROOT)
            if p.returncode or not os.path.exists(out):
                raise RuntimeError(f"rc={p.returncode}: {(p.stdout + p.stderr)[-600:]}")
            doc = _read(out)
        except Exception as e:  # noqa: BLE001 - a pose QC that cannot run is recorded, never silently 'ok'
            self.log(f"shot gate [{gate}] pose QC did not run: {e}")
            return {"failing": {}, "findings": [], "error": str(e)[:800]}
        fs = [dict(f, expected=f.get("expected"), measured=f.get("measured")) for f in doc.get("findings") or [] if f.get("status") == "fail"]
        failing = {}
        for f in fs:
            failing.setdefault(f["shot"], [])
            if f["rule"] not in failing[f["shot"]]:
                failing[f["shot"]].append(f["rule"])
        return {"failing": failing, "findings": fs, "report": _rel(out)}

    def regress(self, gate):
        """Lessons + canon + goldens regress check (factory/lessons/regress.py) at the previs approval gate and before publish.
        Options.regress: enforce (blocking rules stop the gate) | warn (record only) | off."""
        if self.o.regress == "off":
            return {"ok": True, "skipped": True}
        from factory.lessons import regress as lreg
        # the film-craft canon pass (python3 -m factory.canon pass) runs inside episode_regress; at publish it also
        # sees the plates and the final video
        kw = {}
        if gate == "publish":
            vid, pl = self.p("final", "episode.mp4"), self.p("plates")
            kw = {"video": vid if os.path.exists(vid) else None, "plates": pl if os.path.isdir(pl) else None}
        rep = lreg.episode_regress(self.p("episode.json"), gate=gate, quality=self.o.quality, **kw)
        self.st.doc.setdefault("regress", {})[gate] = {k: rep.get(k) for k in ("ok", "mode", "blocking", "warnings", "lessons", "canon")}
        self.st.save()
        for w in rep["warnings"]:
            self.log(f"regress[{gate}] warn {w[:160]}")
        if not rep["ok"]:
            self.log(f"regress[{gate}] BLOCKING: {rep['blocking']}")
            if self.o.regress == "enforce":
                raise RegressionBlocked(f"regress check before {gate} failed: {rep['blocking']}")
        return rep

    def attempts_alert(self, stage, res):
        s = self.st.stage(stage)
        n = max(int(s.get("attempts") or 0), int((res or {}).get("llmAttempts") or 0))
        if n >= costs.ATTEMPT_ALERT:
            alerts = self.st.doc.setdefault("alerts", [])
            alerts.append({"stage": stage, "attempts": n, "costUSD": s.get("costUSD"), "kind": "attempts"})
            self.st.event(f"ALERT: stage {stage} took {n} attempts (cost ${float(s.get('costUSD') or 0):.2f}); "
                          f"check the cache TTL / drafting checklist (L014)", level="warn")
            self.log(f"ALERT: stage {stage} took {n} attempts")
    # <<< quality_gate

    # ------------------------------------------------------------------ executor
    def run(self):
        st = self.st
        lock = threading.Lock()
        running = {}
        stop = {"err": None, "gate": False}

        def ready(name):
            s = st.stage(name)["status"]
            if s == DONE and self._artifacts_ok(name):
                return False
            if s == AWAITING and not self.approved():
                return False
            return all(st.stage(d)["status"] == DONE for d in DEPS[name])

        def runnable():
            return [n for n in ORDER if n not in running and ready(n)]

        # stages marked done whose artifacts vanished are re-run
        for n in ORDER:
            if st.stage(n)["status"] == DONE and not self._artifacts_ok(n):
                self.log(f"stage {n}: artifacts missing, re-running")
                st.update_stage(n, status=PENDING)
            if st.stage(n)["status"] == RUNNING:   # crashed mid-stage last time
                st.update_stage(n, status=PENDING)

        with cf.ThreadPoolExecutor(max_workers=max(1, self.o.parallel_stages)) as ex:
            while True:
                with lock:
                    if stop["err"] is None:
                        for n in runnable():
                            try:
                                self.check_budget(n)
                            except BudgetExceeded as e:
                                stop["err"] = e
                                break
                            running[n] = ex.submit(self._run_stage, n)
                    if not running:
                        break
                done, _ = cf.wait(list(running.values()), return_when=cf.FIRST_COMPLETED)
                with lock:
                    for n, fut in list(running.items()):
                        if fut not in done:
                            continue
                        del running[n]
                        try:
                            fut.result()
                        except AwaitingApproval:
                            stop["gate"] = True
                        except Exception as e:  # noqa: BLE001 - recorded in run.json, surfaced as the run status
                            if stop["err"] is None:
                                stop["err"] = e
        if isinstance(stop["err"], BudgetExceeded):
            st.set_status(R_BUDGET, error=str(stop["err"]))
        elif stop["err"] is not None:
            st.set_status(R_FAILED, error=f"{type(stop['err']).__name__}: {stop['err']}")
        elif stop["gate"] or st.stage("previs")["status"] == AWAITING:
            st.set_status(R_AWAITING)
            self.log(f"AWAITING APPROVAL: review {self.p('boards', 'contact_sheet.png')} and {self.p('boards', 'animatic.mp4')}, "
                     f"then `python -m factory.run approve --episode-id {self.id}` and `--resume`")
        elif st.stage("qc")["status"] == DONE:
            dec = st.doc["qc"].get("decision")
            st.set_status(R_PUBLISHED if dec == "PUBLISH" else R_RETURNED)
        self.log(f"run status: {st.doc['status']}  cost ${st.spent:.2f}  time {st.doc['time']['totalSeconds']:.0f}s")
        return st.doc

    def _run_stage(self, name):
        st = self.st
        t0 = time.time()
        attempts = int(st.stage(name).get("attempts") or 0) + 1
        st.update_stage(name, status=RUNNING, started=time.strftime("%Y-%m-%dT%H:%M:%S"), attempts=attempts, error=None)
        self.log(f"stage {NUMBER[name]} {name}: start")
        try:
            res = getattr(self, "stage_" + name)(t0) or {}
            usd = float(res.pop("usd", 0.0) or 0.0)
            arts = [_rel(a) for a in res.pop("artifacts", [])]
            json.dumps(res, default=str)
        except AwaitingApproval:
            st.add_cost(name, 0.0, time.time() - t0)
            st.update_stage(name, status=AWAITING)
            raise
        except Exception as e:
            st.add_cost(name, 0.0, time.time() - t0)
            st.update_stage(name, status=FAILED, error=f"{type(e).__name__}: {e}", finished=time.strftime("%Y-%m-%dT%H:%M:%S"))
            self.log(f"stage {name}: FAILED {type(e).__name__}: {e}")
            raise
        st.add_cost(name, usd, time.time() - t0)
        st.update_stage(name, status=DONE, finished=time.strftime("%Y-%m-%dT%H:%M:%S"), artifacts=arts, info=res)
        self.log(f"stage {name}: done in {time.time() - t0:.1f}s (${usd:.3f})")
        self.attempts_alert(name, res)   # quality_gate (L014)
        self.check_ceiling(name, after=True)

    def _artifacts_ok(self, name):
        arts = self.st.stage(name).get("artifacts") or []
        return all(os.path.exists(a if os.path.isabs(a) else os.path.join(ROOT, a)) for a in arts)

    def approved(self):
        a = self.st.doc.get("approval")
        return bool(a and a.get("approved"))

    # ------------------------------------------------------------------ director stages (1-4)
    def _client(self):
        if "director_client" in self.hooks:
            return self.hooks["director_client"]()
        from factory.director.llm import AnthropicClient, FixtureClient
        if self.o.offline:
            return FixtureClient(self.o.fixtures)
        return AnthropicClient(self.o.model, self.o.effort)

    def _runner(self, words=None, force=False, cls=None):
        from factory.director import librarian
        from factory.director.runner import Runner
        ph = librarian.PolyHavenSearch(os.path.join(self.o.fixtures, "polyhaven_search.json"),
                                       mode="offline" if self.o.offline else "live")
        cls = cls or Runner
        return cls(self.dir, self._client(), self.o.idea, self.o.fmt, ph=ph, words=words, force=force,
                   log=lambda m: self.log(m), style=self.o.style)  # style system: the run's --style drives every director stage

    def _llm_result(self, stage, art, t0):
        c = costs.llm_stage_cost(self.dir, stage, since=t0)
        return {"artifacts": [self.p(art)], "usd": c["usd"], "tokens": c["tokens"], "llmAttempts": c["attempts"]}

    def stage_develop(self, t0):
        _write(self.p("idea.json"), {"idea": self.o.idea, "format": self.o.fmt, "style": self.o.style})
        style_file = os.path.join(ROOT, "factory", "styles", f"{self.o.style}.json")
        if not os.path.isfile(style_file):
            self.log(f"note: style {self.o.style!r} has no factory/styles/{self.o.style}.json yet (recorded, not applied)")
        r = self._runner(force="develop" in self._force)
        r.develop()
        self._force.discard("develop")
        return self._llm_result("develop", "story.json", t0)

    def stage_breakdown(self, t0):
        r = self._runner(force="breakdown" in self._force)
        r.breakdown(_read(self.p("story.json")))
        self._force.discard("breakdown")
        return self._llm_result("breakdown", "breakdown.json", t0)

    def stage_library(self, t0):
        r = self._runner()
        man = r.library(_read(self.p("story.json")), _read(self.p("breakdown.json")))
        return {"artifacts": [self.p("manifest.json")], "summary": man.get("summary")}

    def stage_direct(self, t0, feedback=None):
        words = _read(self.p("audio", "narration.words.json")) if os.path.exists(self.p("audio", "narration.words.json")) else None
        force = "direct" in self._force or feedback is not None
        r = self._runner(words=words, force=force, cls=_feedback_runner_cls() if feedback else None)
        if feedback:
            r.qc_feedback = feedback
        story, bd, man = (_read(self.p(n)) for n in ("story.json", "breakdown.json", "manifest.json"))
        _, ep = r.direct(story, bd, man)
        self._force.discard("direct")
        ep = self._patch_episode(ep)
        out = self._llm_result("direct", "episode.json", t0)
        out["artifacts"].append(self.p("shotplan.json"))
        out.update(shots=len(ep["shots"]), durationFrames=ep["durationFrames"], storyId=story.get("id"))
        return out

    def _patch_episode(self, ep):
        """Make episode.json point at this run: id = episode id (unique per run: Finish stages into
        studio/public/finish/<id>), audio = this run's narration (stage 5a output)."""
        v = self.st.stage("voice").get("info") or {}
        ep["id"] = self.id
        if v.get("audio"):
            ep["audio"]["narration"] = v["audio"]
            ep["audio"]["wordsJson"] = v["words"]
        ep.setdefault("source", {})["orchestrator"] = "factory/run"
        _write(self.p("episode.json"), ep)
        return ep

    # ------------------------------------------------------------------ 5a voice / 5b sound
    def stage_voice(self, t0):
        mode = "stub" if self.stub("voice") else self.o.voice
        res = voice_mod.synthesize(self.p("story.json"), self.dir, offline=self.o.offline, mode=mode, log=self.log)
        return {"artifacts": [res["audio"], res["words"]], "usd": res["usd"], "audio": _rel(res["audio"]),
                "words": _rel(res["words"]), "provider": res["provider"], "chars": res["chars"]}

    def stage_sound(self, t0):
        from factory.sound import designer
        ep = _read(self.p("episode.json"))
        words = _read(self.p("audio", "narration.words.json"))
        snd = designer.design(ep, words, _rel(self.p("episode.json")), _rel(self.p("audio", "narration.words.json")))
        snd["voice"]["file"] = ep["audio"]["narration"]
        snd["voice"]["words"] = ep["audio"]["wordsJson"]
        sp = self.p("sound.json")
        _write(sp, snd)
        prefix = self.p("audio", "mix_v1")
        if self.stub("mix"):
            narr = ep["audio"]["narration"]
            narr = narr if os.path.isabs(narr) else os.path.join(ROOT, narr)
            off = ep["audio"].get("offsetFrames", 0) / ep["fps"]
            import subprocess
            subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-i", narr, "-af",
                            f"adelay={int(off * 1000)}:all=1,apad,atrim=0:{ep['durationFrames'] / ep['fps']:.3f},loudnorm=I=-14:TP=-1.5",
                            "-ac", "2", "-ar", "48000", "-c:a", "aac", "-b:a", "160k", prefix + ".m4a"], check=True)
            return {"artifacts": [sp, prefix + ".m4a"], "mix": "stub", "cues": len(snd["cues"])}
        from factory.sound import mixer
        rep = mixer.mix(sp, prefix, work=self.p("_work", "mix"), log=lambda *a: self.log(" ".join(map(str, a))))
        try:
            from factory.sound import qc as sound_qc
            rep["qc"] = sound_qc.check(sp, rep)
        except Exception as e:  # noqa: BLE001 - sound QC is advisory here; stage 9 re-measures the final mix
            rep["qc"] = {"error": str(e)}
        _write(prefix + ".report.json", rep)
        shutil.rmtree(self.p("_work", "mix"), ignore_errors=True)
        qc = rep.get("qc") or {}
        return {"artifacts": [sp, prefix + ".m4a", prefix + ".report.json"], "mix": "ffmpeg", "cues": len(snd["cues"]),
                "soundQC": qc.get("pass"), "underSpeechDB": rep.get("under_speech_dB")}

    # ------------------------------------------------------------------ 6 previs + gate
    def stage_previs(self, t0):
        self.shot_gate("previs")   # quality_gate: every shot passes the per-shot checks (or is re-directed) before boards
        ep = _read(self.p("episode.json"))
        bdir = self.p("boards")
        # keyframes already on disk are reused (render_keys skips them), so re-entering after approval is cheap
        info = previs_mod.run(ep, self.p("episode.json"), bdir, audio=self._abs(ep["audio"]["narration"]),
                              shots=list(self.o.previs_shots) or None, stub=self.stub("previs"), res=self.o.previs_res,
                              samples=self.o.previs_samples, workers=self.o.workers, blender=self.o.blender, log=self.log)
        self.st.update_stage("previs", info={k: v for k, v in info.items() if k != "keys_dir"},
                             artifacts=[_rel(info["contact_sheet"]), _rel(info["animatic"])])
        if info.get("missing"):  # quality_gate (L012): every shot renders; a board with holes is not reviewable
            raise RuntimeError(f"previs: {len(info['missing'])} keyframe(s) did not render: {info['missing'][:8]} "
                               f"(logs in {os.path.join(bdir, 'logs')}) - no silent render failures (L012)")
        self.regress("previs")   # quality_gate: lessons + goldens regress check before the approval gate
        if self.o.auto_approve and not self.approved():
            self.approve(by="auto (--auto-approve)")
        if not self.approved():
            raise AwaitingApproval()
        info = _read(os.path.join(bdir, "previs.json"))
        return {"artifacts": [info["contact_sheet"], info["animatic"]], "keys": info.get("keys"),
                "missing": info.get("missing"), "approval": self.st.doc["approval"]}

    def approve(self, by="operator", note=None, approved=True):
        self.st.doc["approval"] = {"approved": approved, "by": by, "note": note, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        self.st.event(f"previs {'approved' if approved else 'rejected'} by {by}" + (f": {note}" if note else ""))
        self.st.save()

    # ------------------------------------------------------------------ 7 render
    def _abs(self, p):
        return p if not p or os.path.isabs(p) else os.path.join(ROOT, p)

    def plates_dir(self):
        info = self.st.stage("render").get("info") or {}
        return self._abs(info.get("plates")) if info.get("plates") else self.p("plates")

    def stage_render(self, t0, shots=None):
        if not shots:
            self.shot_gate("render")   # quality_gate: again before spending render time (TIER blocks at final quality)
        ep = _read(self.p("episode.json"))
        spec_path = self.p("episode.json")
        plates = self.p("plates")
        if shots:
            for s in shots:
                shutil.rmtree(os.path.join(self.plates_dir(), s), ignore_errors=True)
        if self.stub("render"):
            res = render_mod.stub_plates(ep, plates, shots=shots, keys_dir=self.p("boards", "keys"))
        elif self.o.render == "farm":
            remaining = None if self.o.budget is None else max(0.0, self.o.budget - self.st.spent)

            def on_submit(rid, sub):
                self.st.update_stage("render", farmRunId=rid, farmEstimate=sub.get("estimate"))
            res = render_mod.render_farm(ep, self.dir, os.path.dirname(os.path.abspath(self.o.episodes_dir)), self.o.quality,
                                         budget=remaining, shots=shots,
                                         run_id=None if shots else self.st.stage("render").get("farmRunId"),
                                         on_submit=on_submit, farm=self.hooks.get("farm"), poll_s=self.o.farm_poll_s,
                                         log=self.log)
            plates = res["plates"]
        else:
            res = render_mod.render_local(ep, spec_path, plates, self.o.quality, self.o.render_engine, shots=shots,
                                          workers=self.o.workers, res=self.o.render_res, samples=self.o.render_samples,
                                          threads=None, blender=self.o.blender, log_dir=self.p("logs", "render"), log=self.log)
            if res["missingCount"]:
                raise RuntimeError(f"local render: {res['missingCount']} plates missing (failed jobs: {res['failedJobs'][:5]})")
        res["plates"] = _rel(plates)
        res["artifacts"] = [plates]
        return res

    # ------------------------------------------------------------------ 8 finish
    def stage_finish(self, t0):
        ep = _read(self.p("episode.json"))
        os.makedirs(self.p("final"), exist_ok=True)
        out = self.p("final", "episode.mp4")
        audio = self.p("audio", "mix_v1.m4a")
        audio = audio if os.path.isfile(audio) else self._abs(ep["audio"]["narration"])
        fn = finish_mod.finish_stub if self.stub("finish") else finish_mod.finish_real
        kw = {} if self.stub("finish") else {"log_path": self.p("logs", "finish.log")}
        os.makedirs(self.p("logs"), exist_ok=True)
        res = fn(ep, self.p("episode.json"), self.plates_dir(), audio, out, log=self.log, **kw)
        res["artifacts"] = [out]
        return res

    # ------------------------------------------------------------------ 9 QC + retry loop
    def _qc(self, iteration):
        if "qc" in self.hooks:
            return self.hooks["qc"](self, iteration)
        from factory.qc import report as qc_report
        rep = qc_report.run(spec=self.p("episode.json"), video_path=self.p("final", "episode.mp4"),
                            plates_dir=self.plates_dir(), out_dir=self.p("qc"), run_vision=False if self.o.offline else None,
                            iteration=iteration, log=lambda m: self.log(m))
        return rep

    def stage_qc(self, t0):
        fixes = 0
        it = 0
        hist = []
        while True:
            rep = self._qc(it)
            path = self.p("qc", f"report.iter{it}.json")
            os.makedirs(self.p("qc"), exist_ok=True)
            _write(path, {k: v for k, v in rep.items() if k != "path"})
            dec = rep["decision"]
            fails = [r for r in rep.get("rules", []) if r.get("status") == "fail"]
            entry = {"iteration": it, "decision": dec, "score": rep.get("engagement_score"), "report": _rel(path),
                     "failing": [r["id"] for r in fails][:40]}
            self.log(f"QC iteration {it}: {dec} (score {rep.get('engagement_score')}, {len(fails)} failing rules)")
            if dec == "AUTO_FIX" and fixes < self.o.max_qc_fixes:
                plan = plan_fix(rep, _read(self.p("episode.json")))
                entry["fix"] = plan
                hist.append(entry)
                self._record_qc(hist, None)
                self.log(f"AUTO_FIX: re-running stage(s) {plan['stages']} for shots {plan['shots'] or 'none'}")
                self._apply_fix(plan, rep)
                fixes += 1
                it += 1
                continue
            hist.append(entry)
            final = dec if dec in ("PUBLISH", "RETURN") else ("RETURN" if dec == "AUTO_FIX" else dec)
            # >>> quality_gate: regress check before publish, then the delivery copies (L006) or a refusal
            arts, extra = [path], {}
            if final == "PUBLISH":
                try:
                    self.regress("publish")
                except RegressionBlocked as e:
                    final = "RETURN"
                    entry["regress"] = str(e)
                    rep = dict(rep, hard_failures=list(rep.get("hard_failures") or []) + ["REGRESS"])
                if final == "PUBLISH" and self.o.deliver:
                    from factory import deliver as deliver_mod
                    d = deliver_mod.deliver_or_raise(self.p("final", "episode.mp4"), self.p("final", "delivery"), log=self.log)
                    arts += [d["outputs"]["final"]["path"], d["outputs"]["mobile"]["path"]]
                    extra["delivery"] = {k: _rel(o["path"]) for k, o in d["outputs"].items()}
            self._record_qc(hist, final, rep)
            return {"artifacts": arts, "decision": final, "rawDecision": dec, "iterations": len(hist),
                    "score": rep.get("engagement_score"), **extra}
            # <<< quality_gate

    def _record_qc(self, hist, final, rep=None):
        q = self.st.doc["qc"]
        q["iterations"] = hist
        if final:
            q["decision"] = final
            q["report"] = hist[-1]["report"]
            if final != "PUBLISH":
                q["returnReport"] = {"stage": rep.get("decision"), "hard_failures": rep.get("hard_failures"),
                                     "failing": hist[-1]["failing"],
                                     "next": "stage 1/4 (story/direction) - see the QC report" if rep.get("hard_failures")
                                     else "operator review"}
        self.st.save()

    def _apply_fix(self, plan, rep):
        shots = set(plan["shots"])
        if 4 in plan["stages"]:
            t0 = time.time()
            before = {s["id"]: s for s in _read(self.p("episode.json"))["shots"]}
            fb = {"qc_decision": rep["decision"], "score": rep.get("engagement_score"),
                  "failing_rules": [{k: r.get(k) for k in ("id", "section", "measured", "expected", "detail")}
                                    for r in rep.get("rules", []) if r.get("status") == "fail"][:30],
                  "shots_to_fix": sorted(shots)}
            res = self.stage_direct(t0, feedback=fb)
            self.st.add_cost("direct", res.get("usd", 0.0), time.time() - t0)
            after = {s["id"]: s for s in _read(self.p("episode.json"))["shots"]}
            changed = {k for k, v in after.items() if before.get(k) != v}
            if set(before) != set(after):
                changed = set(after)            # re-cut: everything moves
            shots |= changed
            self.st.event(f"qc fix: stage 4 re-directed, {len(changed)} shots changed")
        shots &= {s["id"] for s in _read(self.p("episode.json"))["shots"]}
        if shots:
            t0 = time.time()
            res = self.stage_render(t0, shots=sorted(shots))
            self.st.add_cost("render", res.get("usd", 0.0), time.time() - t0)
        t0 = time.time()
        self.stage_finish(t0)
        self.st.add_cost("finish", 0.0, time.time() - t0)


def _feedback_runner_cls():
    from factory.director import checks, compile as comp
    from factory.director.runner import Runner, _write as dwrite

    class FeedbackRunner(Runner):
        """Stage 4 re-run with the QC report's failing rules added to the inputs."""
        qc_feedback = None

        def direct(self, story, bd, man):
            words, holder = self.words, {}

            def validate(plan):
                rep = checks.check_shotplan(plan, story, bd, man, words)
                if rep.ok:
                    ep = comp.compile_episode(plan, story, man, self.out)
                    erep = checks.check_episode(ep)
                    rep.issues.extend(erep.issues)
                    rep.passed += erep.passed
                    holder["episode"] = ep
                return rep
            inputs = {"story.json": story, "breakdown.json": bd, "manifest.json": man, "qc_feedback.json": self.qc_feedback}
            plan = self.llm_stage("direct", inputs, validate)
            ep = holder.get("episode") or comp.compile_episode(plan, story, man, self.out)
            dwrite(self.path("episode.json"), ep)
            return plan, ep
    return FeedbackRunner


SECTION_STAGE = {"TECH": 7, "FRAMING": 4, "HOOK": 4, "RETENTION": 4, "NARRATION": 4, "PACING": 4, "CAPTIONS": 4, "SOUND": 4}


def failing_shots(rep, shot_ids):
    """Shot ids named by failing rules (measured/detail/expected) or failing per-shot framing rows."""
    ids = sorted(shot_ids, key=len, reverse=True)
    pat = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(map(re.escape, ids)) + r")(?![A-Za-z0-9_])") if ids else None
    out = set()
    for r in rep.get("rules", []):
        if r.get("status") != "fail" or pat is None:
            continue
        blob = json.dumps([r.get("measured"), r.get("detail"), r.get("expected")], default=str)
        out |= set(pat.findall(blob))
    for row in (rep.get("details") or {}).get("framing") or []:
        if isinstance(row, dict) and row.get("status") == "fail" and row.get("shot") in shot_ids:
            out.add(row["shot"])
    return sorted(out)


def plan_fix(rep, ep):
    """AUTO_FIX -> which stages to re-run: TECH-only failures re-render (7) the failing shots; anything in a scored
    section or FRAMING re-directs (4) then re-renders the failing + changed shots."""
    # DELIVERY (master encode profile) is fixed by factory/deliver.py at publish, not by re-directing / re-rendering
    fails = [r for r in rep.get("rules", []) if r.get("status") == "fail" and r.get("section") != "DELIVERY"]
    stages = sorted({SECTION_STAGE.get(r.get("section"), 4) for r in fails}) or [7]
    if 4 in stages and 7 not in stages:
        stages.append(7)
    shots = failing_shots(rep, [s["id"] for s in ep["shots"]])
    return {"stages": sorted(stages), "shots": shots, "rules": [r["id"] for r in fails][:40]}
