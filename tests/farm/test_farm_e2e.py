"""Orchestrator + worker end to end against moto (in-process S3/SQS/DynamoDB), with a fake Blender.

No AWS resources are touched: moto patches botocore, credentials are dummies."""
import json
import os
import sys

import pytest

boto3 = pytest.importorskip("boto3")
moto = pytest.importorskip("moto")

import farmio  # noqa: E402
import healthcheck  # noqa: E402
import orchestrator  # noqa: E402
import worker  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
REGION = "us-east-1"
BUCKET = "farm-test"
TABLE = "farm-test-jobs"


def small_spec(eid="sentinel", shots=("B10", "B11")):
    with open(os.path.join(REPO, "episodes", "sentinel", "episode_v2.json")) as fh:
        spec = json.load(fh)
    spec["id"] = eid
    spec["shots"] = [s for s in spec["shots"] if s["id"] in shots]
    return spec


@pytest.fixture
def aws(monkeypatch, tmp_path):
    for k, v in {"AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing", "AWS_SESSION_TOKEN": "testing",
                 "AWS_DEFAULT_REGION": REGION, "AWS_REGION": REGION}.items():
        monkeypatch.setenv(k, v)
    with moto.mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        sqs = boto3.client("sqs", region_name=REGION)
        ddb = boto3.client("dynamodb", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        dlq = sqs.create_queue(QueueName="dlq")["QueueUrl"]
        dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
        q = sqs.create_queue(QueueName="render", Attributes={
            "VisibilityTimeout": "600",
            "RedrivePolicy": json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "4"})})["QueueUrl"]
        ddb.create_table(TableName=TABLE, BillingMode="PAY_PER_REQUEST",
                         AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"},
                                               {"AttributeName": "sk", "AttributeType": "S"}],
                         KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"},
                                    {"AttributeName": "sk", "KeyType": "RANGE"}])
        s3.put_object(Bucket=BUCKET, Key="library_store/polyhaven/models/rock/rock.gltf", Body=b"{}")
        repo = tmp_path / "repo"
        repo.mkdir()
        env = {"FARM_BUCKET": BUCKET, "FARM_QUEUE_URL": q, "FARM_TABLE": TABLE, "FARM_REPO": str(repo),
               "FARM_WORK": str(tmp_path / "work"), "LIBRARY_STORE": str(tmp_path / "lib"),
               "BLENDER": f"{sys.executable} {os.path.join(HERE, 'fake_blender.py')}", "FARM_IMDS": "0",
               "REQUIRE_GPU": "0", "RECEIVE_WAIT_S": "0", "POLL_S": "0", "IDLE_SHUTDOWN_S": "0",
               "HEALTH_FILE": str(tmp_path / "health.json"), "MAX_ATTEMPTS": "4"}
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        for k in ("FAKE_RC", "FAKE_DEVICE", "FAKE_SKIP", "FAKE_SLEEP"):
            monkeypatch.delenv(k, raising=False)
        os.makedirs(env["FARM_WORK"], exist_ok=True)
        farm = orchestrator.Farm(s3, sqs, ddb, BUCKET, q, TABLE)
        yield {"s3": s3, "sqs": sqs, "ddb": ddb, "q": q, "dlq": dlq, "farm": farm, "tmp": tmp_path, "repo": repo}


def make_worker(aws):
    return worker.Worker(worker.Config(), aws["s3"], aws["sqs"], aws["ddb"])


def drain(aws, w=None, limit=50):
    w = w or make_worker(aws)
    w.preflight()
    results = []
    for _ in range(limit):
        msgs = aws["sqs"].receive_message(QueueUrl=aws["q"], MaxNumberOfMessages=1, VisibilityTimeout=600,
                                          MessageSystemAttributeNames=["ApproximateReceiveCount"]).get("Messages", [])
        if not msgs:
            break
        results.append(w.handle(msgs[0]))
    return results


def queue_depth(aws, url=None):
    a = aws["sqs"].get_queue_attributes(QueueUrl=url or aws["q"], AttributeNames=[
        "ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"])["Attributes"]
    return int(a["ApproximateNumberOfMessages"]), int(a["ApproximateNumberOfMessagesNotVisible"])


def test_two_episodes_render_end_to_end(aws):
    farm = aws["farm"]
    specs = [small_spec("ep-a"), small_spec("ep-b", shots=("C13",))]
    res = farm.submit(specs, quality="preview", budget=100, run_ids=["run-a", "run-b"], res="16x28", samples=1)
    assert [r["runId"] for r in res] == ["run-a", "run-b"]
    assert res[0]["enqueued"] == 3  # B10 + B11 (ep-a) + C13 (ep-b)
    # messages are interleaved across runs: the first two belong to different episodes
    plan_a = farmio.s3_get_json(aws["s3"], BUCKET, farmio.run_key("run-a"))
    assert plan_a["messages"][0]["res"] == "16x28"
    first_two = [json.loads(m["Body"])["runId"] for m in aws["sqs"].receive_message(
        QueueUrl=aws["q"], MaxNumberOfMessages=2, VisibilityTimeout=0)["Messages"]]
    assert set(first_two) == {"run-a", "run-b"}

    results = drain(aws)
    assert sorted(results) == ["done"] * 3
    assert queue_depth(aws) == (0, 0)
    # library synced at preflight
    assert (aws["tmp"] / "lib" / "polyhaven" / "models" / "rock" / "rock.gltf").exists()
    # every frame of every shot is in S3 with a manifest
    for rid, spec in (("run-a", specs[0]), ("run-b", specs[1])):
        keys = farmio.s3_list(aws["s3"], BUCKET, farmio.plates_prefix(spec["id"], rid))
        for shot in spec["shots"]:
            for f in range(shot["from"], shot["to"]):
                assert f"{farmio.plates_prefix(spec['id'], rid)}{shot['id']}/{f:04d}.png" in keys
        assert farm.tick(rid) == "RENDERED"
        st = farm.status(rid)
        assert st["jobs"] == {"DONE": st["jobCount"]} and st["spentUsd"] >= 0
    m = json.loads(aws["s3"].get_object(Bucket=BUCKET, Key=farmio.manifest_key(
        "run-b", plan_b_job(aws)))["Body"].read())
    assert m["status"] == "DONE" and m["render"]["devices"] == ["OPTIX"] and len(m["files"]) == 43  # C13 = 834..876
    assert all(len(f["sha256"]) == 64 for f in m["files"])
    run = farm.store.get_run("run-a")
    assert run["doneJobs"] == run["jobCount"] == 2


def plan_b_job(aws):
    return farmio.s3_get_json(aws["s3"], BUCKET, farmio.run_key("run-b"))["messages"][0]["jobId"]


def test_redelivered_done_job_is_skipped_not_rerendered(aws, tmp_path, monkeypatch):
    farm = aws["farm"]
    farm.submit([small_spec(shots=("B10",))], quality="preview", run_ids=["r1"], res="16x28")
    assert drain(aws) == ["done"]
    msg = farmio.s3_get_json(aws["s3"], BUCKET, farmio.run_key("r1"))["messages"][0]
    farmio.send_jobs(aws["sqs"], aws["q"], [msg])          # SQS at-least-once: same job again
    calls = tmp_path / "calls.txt"
    monkeypatch.setenv("FAKE_CALLS", str(calls))
    assert drain(aws) == ["skipped"]
    assert not calls.exists()                               # Blender never ran
    assert farm.store.get_run("r1")["doneJobs"] == 1        # not double counted


def test_resubmitting_same_run_id_is_refused(aws):
    farm = aws["farm"]
    farm.submit([small_spec(shots=("B10",))], quality="preview", run_ids=["r1"])
    with pytest.raises(Exception):
        farm.submit([small_spec(shots=("B10",))], quality="preview", run_ids=["r1"])


def test_budget_ceiling_spans_parallel_runs(aws):
    farm = aws["farm"]
    one = farm.submit([small_spec()], quality="final", dry_run=True)[0]["estimate"]["usd"]
    farm.submit([small_spec("ep-a")], quality="final", budget=one * 1.5, run_ids=["a"])
    with pytest.raises(orchestrator.BudgetExceeded):
        farm.submit([small_spec("ep-b")], quality="final", budget=one * 1.5, run_ids=["b"])
    # two at once that do not fit together are refused before anything is enqueued
    with pytest.raises(orchestrator.BudgetExceeded):
        farm.submit([small_spec("ep-c"), small_spec("ep-d")], quality="final", budget=one * 2.5, run_ids=["c", "d"])
    assert farm.store.get_run("c") is None
    # cancelling the first run frees its share of the ceiling
    farm.cancel("a")
    farm.submit([small_spec("ep-b")], quality="final", budget=one * 1.5, run_ids=["b"])


def test_failure_retries_then_fails_and_logs(aws, monkeypatch):
    farm = aws["farm"]
    farm.submit([small_spec(shots=("B10",))], quality="preview", run_ids=["r1"])
    monkeypatch.setenv("FAKE_RC", "3")
    assert drain(aws) == ["failed"]
    job = farm.store.list_jobs("r1")[0]
    assert job["status"] == "RETRYING" and "exited 3" in job["lastError"] and job["attempts"] == 1
    assert queue_depth(aws) == (0, 1)                       # backed off, not deleted
    logs = farmio.s3_list(aws["s3"], BUCKET, "farm/runs/r1/logs/")
    assert any(k.endswith(".1.log") for k in logs)
    # last allowed attempt -> FAILED (SQS moves it to the DLQ on the next receive)
    monkeypatch.setenv("MAX_ATTEMPTS", "1")
    msg = farmio.s3_get_json(aws["s3"], BUCKET, farmio.run_key("r1"))["messages"][0]
    farmio.send_jobs(aws["sqs"], aws["q"], [msg])
    assert drain(aws) == ["failed"]
    assert farm.store.list_jobs("r1")[0]["status"] == "FAILED"
    assert farm.tick("r1") == "FAILED"
    # operator fixes the cause and retries the failed jobs
    monkeypatch.delenv("FAKE_RC")
    monkeypatch.setenv("MAX_ATTEMPTS", "4")
    assert farm.retry("r1") == 1
    assert "done" in drain(aws)
    assert farm.tick("r1") == "RENDERED"


def test_missing_plate_fails_the_job(aws, monkeypatch):
    farm = aws["farm"]
    farm.submit([small_spec(shots=("B10",))], quality="preview", run_ids=["r1"])
    monkeypatch.setenv("FAKE_SKIP", "700")
    assert drain(aws) == ["failed"]
    assert "plates missing" in farm.store.list_jobs("r1")[0]["lastError"]
    assert not farmio.s3_exists(aws["s3"], BUCKET, farmio.manifest_key("r1", farm.store.list_jobs("r1")[0]["sk"][4:]))


def test_cpu_fallback_on_gpu_worker_fails(aws, monkeypatch):
    farm = aws["farm"]
    farm.submit([small_spec(shots=("B10",))], quality="preview", run_ids=["r1"])
    monkeypatch.setenv("REQUIRE_GPU", "1")
    monkeypatch.setenv("FAKE_DEVICE", "CPU")
    monkeypatch.setattr(worker, "gpu_names", lambda: ["GPU 0: fake L4"])
    assert drain(aws) == ["failed"]
    assert "CPU" in farm.store.list_jobs("r1")[0]["lastError"]


def test_no_gpu_refuses_to_start(aws, monkeypatch):
    monkeypatch.setenv("REQUIRE_GPU", "1")
    monkeypatch.setattr(worker, "gpu_names", lambda: [])
    with pytest.raises(SystemExit):
        make_worker(aws).preflight()


def test_cancelled_run_jobs_are_dropped(aws, tmp_path, monkeypatch):
    farm = aws["farm"]
    farm.submit([small_spec()], quality="preview", run_ids=["r1"])
    farm.cancel("r1")
    calls = tmp_path / "calls.txt"
    monkeypatch.setenv("FAKE_CALLS", str(calls))
    assert drain(aws) == ["cancelled", "cancelled"]
    assert queue_depth(aws) == (0, 0) and not calls.exists()


def test_live_lease_blocks_duplicate_delivery(aws):
    farm = aws["farm"]
    farm.submit([small_spec(shots=("B10",))], quality="preview", run_ids=["r1"])
    jid = farm.store.list_jobs("r1")[0]["sk"][4:]
    assert farm.store.claim_job("r1", jid, "other-worker", 600)
    assert drain(aws) == ["busy"]
    assert farm.store.get_job("r1", jid)["worker"] == "other-worker"


def test_retry_resumes_from_plates_already_in_s3(aws, tmp_path, monkeypatch):
    farm = aws["farm"]
    farm.submit([small_spec(shots=("B10",))], quality="preview", run_ids=["r1"])
    plan = farmio.s3_get_json(aws["s3"], BUCKET, farmio.run_key("r1"))["messages"][0]
    # an interrupted attempt uploaded the first 5 frames
    for f in range(700, 705):
        aws["s3"].put_object(Bucket=BUCKET, Key=f"{plan['platesPrefix']}B10/{f:04d}.png", Body=b"\x89PNG partial")
    assert drain(aws) == ["done"]
    m = farmio.s3_get_json(aws["s3"], BUCKET, farmio.manifest_key("r1", plan["jobId"]))
    assert m["resumedFrames"] == 5
    rendered = m["render"]["secondsPerFrame"]
    assert "700" not in rendered and "705" in rendered   # --skip-existing honoured


def test_bad_messages_are_rejected(aws):
    sqs = aws["sqs"]
    sqs.send_message(QueueUrl=aws["q"], MessageBody="not json")
    sqs.send_message(QueueUrl=aws["q"], MessageBody=json.dumps({
        "runId": "r", "jobId": "j", "episodeId": "e", "specKey": "../../etc/passwd", "shot": "A01", "frameStart": 0,
        "frameEnd": 1, "quality": "final", "engine": "CYCLES", "platesPrefix": "episodes/e/runs/r/plates/"}))
    assert drain(aws, limit=2) == ["bad", "bad"]
    with pytest.raises(worker.JobError):
        worker.extra_args({"extraArgs": ["--python", "evil.py"]})
    assert worker.extra_args({"extraArgs": ["--haze", "0.02", "--no-motion-blur"]}) == ["--haze", "0.02",
                                                                                         "--no-motion-blur"]


def test_idle_worker_exits_and_reports_health(aws, monkeypatch):
    monkeypatch.setenv("IDLE_SHUTDOWN_S", "1")  # 0 means "never shut down"
    w = make_worker(aws)
    assert w.run() == 0                         # empty queue for 1 s -> idle shutdown path
    assert healthcheck.main(os.environ["HEALTH_FILE"]) == 0


def test_finish_pulls_plates_and_runs_finish_then_qc(aws):
    farm = aws["farm"]
    farm.submit([small_spec(shots=("B10",))], quality="preview", run_ids=["r1"])
    with pytest.raises(SystemExit):              # not rendered yet
        farm.finish("r1", repo=str(aws["repo"]))
    drain(aws)
    assert farm.tick("r1") == "RENDERED"
    cmds = []

    def runner(cmd):
        cmds.append(cmd)
        if "FINISH" in cmd:
            out = cmd.split("OUT=")[1].split()[0]
            open(out, "wb").write(b"mp4")
        return 0
    r = farm.finish("r1", finish_cmd="FINISH OUT={out} PLATES={plates} PROPS={props}",
                    qc_cmd="QC {episode_dir} {out}", repo=str(aws["repo"]), runner=runner)
    assert r["status"] == "DONE" and len(cmds) == 2
    plates = aws["repo"] / "episodes" / "sentinel" / "runs" / "r1" / "plates" / "B10"
    assert len(list(plates.glob("*.png"))) == 55
    props = json.load(open(aws["repo"] / "episodes" / "sentinel" / "runs" / "r1" / "final" / "finish_props.json"))
    assert props["platesDir"].endswith("plates")
    assert farmio.s3_exists(aws["s3"], BUCKET, "episodes/sentinel/runs/r1/final/sentinel.mp4")
    assert farm.store.get_run("r1")["status"] == "DONE"


def test_finish_stops_on_qc_failure(aws):
    farm = aws["farm"]
    farm.submit([small_spec(shots=("B10",))], quality="preview", run_ids=["r1"])
    drain(aws)
    farm.tick("r1")
    r = farm.finish("r1", finish_cmd="ok", qc_cmd="qc", repo=str(aws["repo"]),
                    runner=lambda c: 0 if c == "ok" else 1)
    assert r["status"] == "QC_FAILED" and farm.store.get_run("r1")["status"] == "QC_FAILED"


def test_overspent_run_is_cancelled_by_tick(aws):
    farm = aws["farm"]
    farm.submit([small_spec(shots=("B10",))], quality="preview", run_ids=["r1"])
    run = farm.store.get_run("r1")
    # pretend workers billed 10x the run budget
    farm.store.add_run_progress("r1", gpu_seconds=run["budgetUsd"] * 10 / run["usdPerGpuHour"] * 3600)
    assert farm.tick("r1") == "CANCELLED"


def test_cli_plan_needs_no_aws(capsys):
    orchestrator.main(["plan", "--spec", os.path.join(REPO, "episodes", "sentinel", "episode_v2.json"),
                       "--quality", "final", "--workers", "4"])
    out = json.loads(capsys.readouterr().out)
    assert out[0]["episodeId"] == "sentinel" and out[0]["estimate"]["frames"] == 2416
