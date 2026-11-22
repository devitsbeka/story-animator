"""L014 regression: per-stage cost ceilings stop the run; >= 2 attempts raise an alert. Also the regress gate
(lessons checks before previs approval / publish) and the delivery copies at publish (L006)."""
import json
import os

from conftest import IDEA
from factory.run import costs
from factory.run.pipeline import Options, Pipeline

QUICK_STUBS = frozenset({"previs", "render", "finish", "mix"})


def opts(tmp_path, **kw):
    base = dict(idea=IDEA, offline=True, stubs=QUICK_STUBS, auto_approve=True, episodes_dir=str(tmp_path / "eps"), regress="warn")
    base.update(kw)
    return Options(**base)


def test_ceilings_default_and_override(monkeypatch):
    assert costs.stage_ceilings()["direct"] == costs.STAGE_CEILINGS_USD["direct"]
    monkeypatch.setenv("FACTORY_STAGE_CEILINGS_JSON", json.dumps({"direct": 9.5}))
    assert costs.stage_ceilings()["direct"] == 9.5


def test_stage_over_its_ceiling_stops_the_run(tmp_path, monkeypatch):
    # the original defect: one stage burning $5 on retries; no overall --budget given
    monkeypatch.setenv("FACTORY_STAGE_CEILINGS_JSON", json.dumps({"breakdown": 1.0}))
    pipe = Pipeline(opts(tmp_path), "ceil", log=lambda m: None)
    orig = pipe.stage_breakdown

    def pricey(t0):
        res = orig(t0)
        res["usd"], res["llmAttempts"] = 1.6, 3
        return res
    pipe.stage_breakdown = pricey
    doc = pipe.run()
    assert doc["status"] == "budget_exceeded" and "ceiling" in doc["error"]
    assert doc["stages"]["breakdown"]["ceilingExceeded"] == {"spentUSD": 1.6, "ceilingUSD": 1.0}
    assert doc["stages"]["direct"]["status"] == "pending"
    assert any(a["stage"] == "breakdown" and a["attempts"] == 3 for a in doc["alerts"])
    assert any("ALERT" in e["msg"] for e in doc["events"])
    # resuming does not re-run the stage that hit its ceiling... and a stage at its ceiling is never started again
    pipe2 = Pipeline(opts(tmp_path), "ceil", resume=True, log=lambda m: None)
    pipe2.st.update_stage("direct", costUSD=costs.stage_ceilings()["direct"])
    doc2 = pipe2.run()
    assert doc2["status"] == "budget_exceeded" and "direct" in doc2["error"]


def test_attempts_alert_at_two(tmp_path):
    pipe = Pipeline(opts(tmp_path), "att", log=lambda m: None)
    pipe.st.update_stage("develop", attempts=2, costUSD=0.3)
    pipe.attempts_alert("develop", {})
    assert pipe.st.doc["alerts"][-1]["attempts"] == 2
    pipe.attempts_alert("library", {"llmAttempts": 1})
    assert len(pipe.st.doc["alerts"]) == 1


def test_regress_enforce_blocks_camera_inside_cabin(tmp_path):
    # the recorded Sentinel direct fixture puts C28's camera inside the cabin (L012): enforce stops at previs
    pipe = Pipeline(opts(tmp_path, regress="enforce"), "reg", log=lambda m: None)
    doc = pipe.run()
    assert doc["status"] == "failed" and doc["stages"]["previs"]["status"] == "failed"
    assert "RegressionBlocked" in doc["stages"]["previs"]["error"] and "PROXY" in doc["stages"]["previs"]["error"]
    assert doc["regress"]["previs"]["ok"] is False and doc["stages"]["render"]["status"] == "pending"


def test_publish_runs_regress_and_delivers(tmp_path):
    pub = lambda p, i: {"decision": "PUBLISH", "rules": [], "engagement_score": 90}  # noqa: E731
    pipe = Pipeline(opts(tmp_path), "pub", log=lambda m: None, hooks={"qc": pub})
    doc = pipe.run()
    assert doc["status"] == "published", doc.get("error")
    assert doc["regress"]["publish"]["ok"] is False          # recorded (warn mode), the PROXY finding is listed
    info = doc["stages"]["qc"]["info"]
    d = os.path.join(str(tmp_path / "eps"), "pub", "final", "delivery")
    assert os.path.isfile(os.path.join(d, "episode.mp4")) and os.path.isfile(os.path.join(d, "episode_mobile.mp4"))
    assert json.load(open(os.path.join(d, "delivery.json")))["ok"] and "delivery" in info
    # enforce at publish: the episode is RETURNed instead of published
    pipe2 = Pipeline(opts(tmp_path, regress="enforce"), "pub2", log=lambda m: None, hooks={"qc": pub})
    pipe2.regress = (lambda orig: (lambda gate: None if gate == "previs" else orig(gate)))(pipe2.regress)
    doc2 = pipe2.run()
    assert doc2["status"] == "returned" and doc2["qc"]["decision"] == "RETURN"
    assert "REGRESS" in doc2["qc"]["returnReport"]["hard_failures"]
