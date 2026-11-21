"""worker.py records its provider (manifest + job item + DynamoDB heartbeat); orchestrator submit/status drive the
scheduler. moto (in-process AWS), fake Blender; nothing leaves the process."""
import json
import os

import pytest

pytest.importorskip("moto")

import farmio  # noqa: E402
import orchestrator  # noqa: E402
import scheduler as sched  # noqa: E402
from test_farm_e2e import BUCKET, aws, drain, make_worker, small_spec  # noqa: E402,F401


def test_manifest_job_and_heartbeat_record_the_provider(aws, monkeypatch):
    monkeypatch.setenv("FARM_PROVIDER", "runpod")
    monkeypatch.setenv("FARM_PROVIDER_WORKER_ID", "runpod:pod42")
    monkeypatch.setenv("FARM_GPU_CLASS", "RTX4090")
    farm = aws["farm"]
    farm.submit([small_spec("ep-p", shots=("B10",))], quality="preview", run_ids=["run-p"], res="16x28", samples=1)
    assert drain(aws) == ["done"]
    plan = farmio.s3_get_json(aws["s3"], BUCKET, farmio.run_key("run-p"))
    job_id = plan["messages"][0]["jobId"]
    m = farmio.s3_get_json(aws["s3"], BUCKET, farmio.manifest_key("run-p", job_id))
    assert (m["provider"], m["providerWorkerId"], m["gpuClass"]) == ("runpod", "runpod:pod42", "RTX4090")
    assert m["estSeconds"] == plan["messages"][0]["estSeconds"]
    job = farm.store.get_job("run-p", job_id)
    assert job["provider"] == "runpod" and job["providerWorkerId"] == "runpod:pod42"
    hb = farm.store.list_heartbeats()
    assert hb["runpod:pod42"]["provider"] == "runpod" and hb["runpod:pod42"]["state"] in ("idle", "rendering")
    # heartbeat rows do not disturb run listing
    assert [r["runId"] for r in farm.store.list_runs()] == ["run-p"]
    # calibration from these manifests feeds the planner
    assert set(sched.speed_calibration_from_manifests([m])) == {"RTX4090"}


def test_heartbeat_is_throttled_and_never_fatal(aws, monkeypatch):
    monkeypatch.setenv("HEARTBEAT_DDB_S", "3600")
    w = make_worker(aws)
    w.health("idle")
    t0 = aws["farm"].store.list_heartbeats()[w.provider_worker_id]["t"]
    w.health("idle")                                    # same state inside the window: no write
    assert aws["farm"].store.list_heartbeats()[w.provider_worker_id]["t"] == t0
    w.health("rendering")                               # state change: written at once
    assert aws["farm"].store.list_heartbeats()[w.provider_worker_id]["state"] == "rendering"
    w.store.table = "no-such-table"
    w.health("idle")                                    # DynamoDB error is logged, not raised


def test_scheduler_reads_dynamodb_heartbeats(aws, tmp_path):
    store = aws["farm"].store
    store.put_heartbeat("local:abc", state="rendering", provider="local")
    cfg = sched.load_config()
    s = sched.Scheduler(cfg, {}, heartbeats=store.list_heartbeats, state_path=str(tmp_path / "s.json"))
    assert s._heartbeats({"errors": []})["local:abc"]["state"] == "rendering"


def test_s3_code_source_uploads_bundle_once(aws):
    try:
        head = sched.startup.git_head()
    except Exception:  # noqa: BLE001
        pytest.skip("not a git checkout")
    cfg = {"code": {"source": "s3", "commit": head}}
    code = sched.ensure_code(cfg, aws["farm"])
    assert code["FARM_CODE_SOURCE"] == "s3" and code["FARM_CODE_KEY"] == f"farm/code/{head}.tar.gz"
    body = aws["s3"].get_object(Bucket=BUCKET, Key=code["FARM_CODE_KEY"])["Body"].read()
    import hashlib
    assert hashlib.sha256(body).hexdigest() == code["FARM_CODE_SHA256"]
    assert sched.ensure_code(cfg, aws["farm"]) == code     # idempotent


def no_gpu_config(tmp_path):
    p = tmp_path / "providers.yaml"
    p.write_text("order: [local]\nbudget: {max_usd_per_hour: 1}\n"
                 "providers:\n  local: {enabled: true, max_workers: 0}\n")
    return str(p)


def test_orchestrator_submit_ticks_scheduler_and_status_lists_providers(aws, tmp_path, monkeypatch, capsys):
    cfgp = no_gpu_config(tmp_path)
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps(small_spec("ep-o", shots=("B10",))))
    base = ["--providers", cfgp, "--state-dir", str(tmp_path / "state")]
    orchestrator.main([*base, "submit", "--spec", str(spec), "--quality", "preview", "--run-id", "run-o",
                       "--res", "16x28", "--samples", "1"])
    res = json.loads(capsys.readouterr().out)
    assert res["runs"][0]["runId"] == "run-o"
    assert res["compute"]["backlogJobs"] == 1 and res["compute"]["launched"] == []
    assert "local" in res["compute"]["unavailable"]       # 0 slots configured
    orchestrator.main([*base, "status"])
    st = json.loads(capsys.readouterr().out)
    assert st["runs"][0]["runId"] == "run-o" and st["compute"]["providers"][0]["provider"] == "local"
    orchestrator.main([*base, "submit", "--spec", str(spec), "--quality", "preview", "--run-id", "run-o2",
                       "--no-scale"])
    assert isinstance(json.loads(capsys.readouterr().out), list)   # plain submit result, no scheduler tick
    assert os.path.isfile(tmp_path / "state" / "scheduler.json")
