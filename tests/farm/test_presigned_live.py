"""LIVE presigned-path proof on the REAL farm bucket (opt-in; never launches a cloud pod).

    PRESIGNED_LIVE=1 env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN \\
        python3 -m pytest -q tests/farm/test_presigned_live.py -s

The orchestrator (operator credentials from ~/.aws) uploads the inputs under a unique test prefix and writes a pod
manifest; the "pod" is a local subprocess running the exact bootstrap command a RunPod pod would get, with only
MANIFEST_URL (+ local Blender path / proxy vars) in its env and NO AWS variables. It renders 2 frames of Sentinel
shot A01a at 64x112 with the local CPU Blender, PUTs every plate/log/heartbeat/done marker through presigned URLs,
and the orchestrator's watch loop sees the run COMPLETE and pulls the plates. Every object under the test prefix
is deleted afterwards. Env: PRESIGNED_LIVE_CODE=head|worktree (default worktree), FARM_BUCKET (default: stack)."""
import json
import os
import struct
import uuid

import pytest

if os.environ.get("PRESIGNED_LIVE") != "1":
    pytest.skip("live test: set PRESIGNED_LIVE=1 (uses the real bucket)", allow_module_level=True)

import presigned as P  # noqa: E402
from localpod import LocalPods  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
BLENDER = os.environ.get("BLENDER_LOCAL", "/opt/blender/blender-4.2.3-linux-x64/blender")


def test_live_presigned_pod_renders_two_frames(tmp_path):
    assert not os.environ.get("AWS_ACCESS_KEY_ID"), "run with env -u AWS_ACCESS_KEY_ID ... (operator profile)"
    s3, sess = P.s3_client("us-east-1", os.environ.get("FARM_AWS_PROFILE"))
    bucket = os.environ.get("FARM_BUCKET") or P.stack_bucket(sess, "story-farm")
    root = f"farm/test/presigned-{uuid.uuid4().hex[:10]}/"
    layout = P.Layout(root, root + "library_store/")
    lib = tmp_path / "lib"
    (lib / "test").mkdir(parents=True)
    (lib / "test" / "probe.txt").write_text("library file delivered through a presigned GET\n")
    empty_lib = tmp_path / "empty_lib"
    empty_lib.mkdir()
    pods = LocalPods(str(tmp_path / "pods"), overrides={"BLENDER": BLENDER})
    f = P.PresignedFarm(s3, bucket, layout, "runpod", provider=pods, repo=REPO, state_dir=str(tmp_path / "state"))
    os.environ["LIBRARY_STORE"] = str(lib)
    try:
        res = f.submit(os.path.join(REPO, "episodes", "sentinel", "episode_v4.json"), "preview", workers=1,
                       budget=1.0, gpu="RTX4090", frames=(0, 1), engine="CYCLES", res="64x112", samples=4,
                       run_id="live-" + uuid.uuid4().hex[:6], code_mode=os.environ.get("PRESIGNED_LIVE_CODE", "worktree"),
                       library="none", extra_library=["test/probe.txt"], price=0.0,
                       opts={"require_gpu": False, "exit_when_done": True, "heartbeat_s": 10, "threads": 2,
                             "expires_s": 3 * 3600})
        os.environ.pop("LIBRARY_STORE")
        run = res["runId"]
        print(json.dumps(res, indent=1))
        assert pods.wait(900), "local pod did not finish"
        st = f.watch(run, interval=1, max_ticks=3, dest=str(tmp_path / "plates"))
        print(json.dumps(f.summary(st), indent=1))
        assert st["status"] == "COMPLETE"
        for fr in (0, 1):
            png = (tmp_path / "plates" / "A01a" / f"{fr:04d}.png").read_bytes()
            assert png[:8] == b"\x89PNG\r\n\x1a\n"
            w, h = struct.unpack(">II", png[16:24])
            assert (w, h) == (64, 112)
        pod = st["pods"][0]["pod"]
        done, _ = P.s3_get_json(s3, bucket, layout.done(run, pod))
        hb, _ = P.s3_get_json(s3, bucket, layout.heartbeat(run, pod))
        jm, _ = P.s3_get_json(s3, bucket, layout.job_manifest(run, pod, st["pods"][0]["jobs"][0]))
        print(json.dumps({"done": done, "heartbeat": hb, "jobManifest": jm}, indent=1)[:4000])
        assert done["status"] == "DONE" and done["framesDone"] == 2
        assert jm["status"] == "DONE" and jm["render"]["resolution"] == [64, 112]
        home = tmp_path / "pods" / "local1"
        assert (home / "library_store" / "test" / "probe.txt").read_text().startswith("library file")
        assert not [k for k in pods.envs["local1"] if k.startswith("AWS_")]
        keys = P.s3_list(s3, bucket, root)
        print("objects under test prefix:", len(keys))
        for k in sorted(keys):
            print("  ", k, keys[k][0])
    finally:
        os.environ.pop("LIBRARY_STORE", None)
        for pid in list(pods.procs):
            pods.terminate([pid])
        keys = list(P.s3_list(s3, bucket, root))
        for i in range(0, len(keys), 1000):
            s3.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": k} for k in keys[i:i + 1000]]})
        left = P.s3_list(s3, bucket, root)
        print(f"cleanup: deleted {len(keys)} objects under s3://{bucket}/{root}; left {len(left)}")
        assert not left
