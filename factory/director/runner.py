"""Stage runner: idea -> story.json -> breakdown.json -> manifest.json -> shotplan.json + episode.json.

Each LLM stage: build the cached system prompt (role + recipe sections), send the inputs, parse the JSON, validate it
against its schema and the automatable checklist, and on failure send the validator's errors back in the same
conversation (up to max_attempts). Every artifact and its validation report is written under the episode dir, so a
stage is resumable: a valid existing artifact is reused unless force=True.
"""
import json
import os
import time

from . import checks, compile as comp, librarian, prompts, schemas
from .llm import LLMError

STAGES = ("develop", "breakdown", "library", "direct")
ARTIFACT = {"develop": "story.json", "breakdown": "breakdown.json", "library": "manifest.json", "direct": "shotplan.json"}
SCHEMA = {"develop": "story", "breakdown": "breakdown", "direct": "shotplan"}


class StageFailed(RuntimeError):
    def __init__(self, stage, report):
        super().__init__(f"stage {stage} failed validation after retries: "
                         + "; ".join(f"[{i['rule']}] {i['msg']}" for i in report.blocking[:8]))
        self.stage, self.report = stage, report


def _write(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class Runner:
    def __init__(self, out_dir, client, idea, fmt, ph=None, max_attempts=3, words=None, force=False, log=print):
        self.out, self.client, self.idea, self.fmt = out_dir, client, idea, fmt
        self.ph, self.max_attempts, self.force, self.log = ph, max_attempts, force, log
        self.words = words
        self.reports = {}

    def path(self, name):
        return os.path.join(self.out, name)

    def _existing(self, stage, validate):
        p = self.path(ARTIFACT[stage])
        if self.force or not os.path.exists(p):
            return None
        doc = _read(p)
        rep = validate(doc)
        if rep.ok:
            self.log(f"[{stage}] reusing valid {p}")
            self.reports[stage] = rep
            return doc
        self.log(f"[{stage}] existing {p} is invalid ({len(rep.blocking)} issues); regenerating")
        return None

    def llm_stage(self, stage, inputs, validate):
        doc = self._existing(stage, validate)
        if doc is not None:
            return doc
        system = prompts.system_blocks(stage)
        messages = [prompts.user_message(stage, self.idea, self.fmt, inputs)]
        schema = schemas.api_schema(SCHEMA[stage])
        rep = None
        for attempt in range(1, self.max_attempts + 1):
            t0 = time.time()
            text, meta = self.client.complete(stage, system, messages, schema)
            os.makedirs(self.path("_llm"), exist_ok=True)
            with open(self.path(f"_llm/{stage}.{attempt}.json"), "w", encoding="utf-8") as fh:
                fh.write(text)
            try:
                doc = json.loads(text)
                rep = validate(doc)
            except json.JSONDecodeError as e:
                doc, rep = None, checks.Report(stage)
                rep.hard("JSON", False, f"response is not valid JSON: {e}")
            _write(self.path(f"reports/{stage}.{attempt}.json"), {**rep.to_dict(), "meta": meta})
            n_ovr = sum(1 for i in rep.issues if i["overridden"])
            self.log(f"[{stage}] attempt {attempt}: {'PASS' if rep.ok else 'FAIL'} - {len(rep.passed)} checks passed, "
                     f"{len(rep.blocking)} blocking, {n_ovr} overridden ({time.time() - t0:.1f}s, {meta.get('model')})")
            if rep.ok:
                _write(self.path(ARTIFACT[stage]), doc)
                _write(self.path(f"reports/{stage}.json"), rep.to_dict())
                self.reports[stage] = rep
                return doc
            for i in rep.blocking[:12]:
                self.log(f"    [{i['severity']} {i['rule']}] {i['msg'][:160]}")
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": rep.retry_feedback()})
        _write(self.path(f"reports/{stage}.json"), rep.to_dict())
        raise StageFailed(stage, rep)

    # ------------------------------------------------------------------ stages
    def develop(self):
        def validate(s):
            rep = checks.check_story(s)
            if isinstance(s, dict) and s.get("format") and s["format"] != self.fmt:
                rep.hard("FORMAT", False, f"story.format is {s['format']!r} but {self.fmt!r} was requested")
            return rep
        return self.llm_stage("develop", {}, validate)

    def breakdown(self, story):
        return self.llm_stage("breakdown", {"story.json": story}, lambda b: checks.check_breakdown(b, story))

    def library(self, story, bd):
        cat = librarian.load_catalog()
        p = self.path("manifest.json")
        man, gaps = librarian.resolve(bd, cat, self.ph)
        rep = checks.check_manifest(man, bd, cat)
        _write(self.path("reports/library.json"), {**rep.to_dict(), "catalog_gaps": gaps,
                                                   "polyhaven_cache_misses": getattr(self.ph, "misses", [])})
        s = man["summary"]
        self.log(f"[library] {'PASS' if rep.ok else 'FAIL'} - REUSE {s.get('REUSE', 0)}, SOURCE {s.get('SOURCE', 0)}, BUILD {s.get('BUILD', 0)}"
                 f" (to_fetch {s.get('to_fetch', 0)}, to_build {s.get('to_build', 0)}); catalog gaps: {gaps}")
        if not rep.ok:
            raise StageFailed("library", rep)
        _write(p, man)
        self.reports["library"] = rep
        return man

    def direct(self, story, bd, man):
        words = self.words
        holder = {}

        def validate(plan):
            rep = checks.check_shotplan(plan, story, bd, man, words)
            if rep.ok:
                ep = comp.compile_episode(plan, story, man, self.out)
                erep = checks.check_episode(ep, plan.get("overrides"))
                for i in erep.issues:
                    rep.issues.append(i)
                rep.passed += erep.passed
                holder["episode"] = ep
            return rep
        plan = self.llm_stage("direct", {"story.json": story, "breakdown.json": bd, "manifest.json": man}, validate)
        ep = holder.get("episode") or comp.compile_episode(plan, story, man, self.out)
        _write(self.path("episode.json"), ep)
        self.log(f"[direct] wrote {self.path('episode.json')}: {len(ep['shots'])} shots, {ep['durationFrames']} frames")
        return plan, ep

    def run(self, stages=STAGES):
        os.makedirs(self.out, exist_ok=True)
        _write(self.path("idea.json"), {"idea": self.idea, "format": self.fmt})
        story = self.develop() if "develop" in stages else _read(self.path("story.json"))
        if "breakdown" not in stages and "library" not in stages and "direct" not in stages:
            return {"story": story}
        bd = self.breakdown(story) if "breakdown" in stages else _read(self.path("breakdown.json"))
        man = self.library(story, bd) if "library" in stages else _read(self.path("manifest.json"))
        out = {"story": story, "breakdown": bd, "manifest": man}
        if "direct" in stages:
            out["shotplan"], out["episode"] = self.direct(story, bd, man)
        return out


def load_words(out_dir, explicit=None):
    p = explicit or os.path.join(out_dir, "audio", "narration.words.json")
    if p and os.path.exists(p):
        return _read(p)
    return None


__all__ = ["Runner", "StageFailed", "LLMError", "STAGES", "load_words"]
