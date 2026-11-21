"""Presigned (credential-free) farm mode: planning, library selection, code tarball, pod manifests, the RunPod
create payload, the watch loop (dead pods, re-assignment, budget, completion) - all against moto S3 and a mocked
RunPod REST API - plus a local end-to-end run where the "pod" is a subprocess running the real startup script
(curl + presigned URLs against a moto S3 server, fake Blender). No network, no AWS resources, no pods."""
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import urllib.parse

import pytest

boto3 = pytest.importorskip("boto3")
moto = pytest.importorskip("moto")

import presigned as P  # noqa: E402
from http_mock import MockTransport  # noqa: E402
from localpod import LocalPods  # noqa: E402
from providers.startup import decode_bootstrap  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
REGION = "us-east-1"
BUCKET = "farm-presigned-test"


def tiny_spec(tmp_path, eid="tiny", shots=(("S1", 0, 3), ("S2", 3, 5))):
    spec = {"id": eid, "fps": 30, "width": 1080, "height": 1920,
            "shots": [{"id": s, "from": a, "to": b} for s, a, b in shots]}
    p = tmp_path / f"{eid}.json"
    p.write_text(json.dumps(spec))
    return str(p), spec


@pytest.fixture
def aws(monkeypatch):
    for k, v in {"AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",
                 "AWS_DEFAULT_REGION": REGION}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    with moto.mock_aws():
        s3, _ = P.s3_client(REGION)
        s3.create_bucket(Bucket=BUCKET)
        yield s3


def runpod_api():
    t = MockTransport()
    n = {"i": 0}
    pods = {}

    def create(call):
        n["i"] += 1
        pid = f"rp{n['i']}"
        pods[pid] = {"id": pid, "name": call["json"]["name"], "status": "RUNNING", "cost": 0.69,
                     "gpu": {"id": call["json"]["gpu"]["id"], "count": 1}, "cloud": call["json"]["cloud"]}
        return 201, pods[pid]

    def delete(call):
        pods.pop(call["path"].rsplit("/", 1)[1], None)
        return 204, None
    t.route("POST", "/v2/pods", create)
    t.route("GET", "/v2/pods", lambda c: (200, {"pods": list(pods.values()), "pagination": {}}))
    t.route("DELETE", "/v2/pods/[^/]+", delete)
    t.pods = pods
    return t


class Clock:
    def __init__(self, t=None):
        import time
        self.t = time.time() if t is None else t

    def __call__(self):
        return self.t


def farm(s3, tmp_path, transport=None, clock=None, **kw):
    return P.PresignedFarm(s3, BUCKET, P.Layout("farm/test/"), "runpod", repo=REPO, state_dir=str(tmp_path / "state"),
                           transport=transport, clock=clock or Clock(), **kw)


# ------------------------------------------------------------------------------------------------ pure helpers
def test_assign_balances_and_covers():
    js = [{"jobId": f"j{i}", "estSeconds": s, "frameStart": i * 10, "frameEnd": i * 10 + 9, "shot": "A"}
          for i, s in enumerate([900, 800, 300, 300, 200, 100])]
    groups = P.assign(js, 3)
    assert sorted(j["jobId"] for g in groups for j in g) == sorted(j["jobId"] for j in js)
    loads = sorted(sum(j["estSeconds"] for j in g) for g in groups)
    assert loads == [800, 900, 900]
    assert len(P.assign(js[:2], 8)) == 2


def test_missing_jobs_splits_runs_and_renames():
    j = {"jobId": "e-A-f00000-00009-preview", "episodeId": "e", "shot": "A", "frameStart": 0, "frameEnd": 9,
         "frames": 10, "quality": "preview", "estSecondsPerFrame": 3.0}
    have = {("A", f) for f in (0, 1, 2, 5, 9)}
    out = P.missing_jobs([j], have, "r1")
    assert [(x["frameStart"], x["frameEnd"]) for x in out] == [(3, 4), (6, 8)]
    assert out[0]["jobId"] == "e-A-f00003-00004-preview-r1" and out[1]["frames"] == 3


def test_parse_frames_and_redact():
    assert P.parse_frames("10-20") == (10, 20) and P.parse_frames(None) is None
    with pytest.raises(ValueError):
        P.parse_frames("20-10")
    u = "https://b.s3.amazonaws.com/farm/x/manifest.json?X-Amz-Algorithm=AWS4&X-Amz-Signature=abc"
    assert P.redact_url(u) == "https://b.s3.amazonaws.com/farm/x/manifest.json?REDACTED"


def test_select_library_spec_kit_and_renderer(tmp_path):
    repo = tmp_path
    (repo / "cloud" / "blender").mkdir(parents=True)
    (repo / "cloud" / "blender" / "r.py").write_text(
        'HDRI = {"ph:sky": "polyhaven/sky/sky_4k.exr"}\n'
        'def trees():\n    return [f"polyhaven/tree_0{i}/tree_0{i}_1k.gltf" for i in (1, 2)]\n'
        'def generic(n):\n    return f"polyhaven/{n}/{n}_1k.gltf"\n'
        'ROCKS = ("rock_big_01",)\n')
    (repo / "factory" / "worlds" / "kits").mkdir(parents=True)
    (repo / "factory" / "worlds" / "kits" / "street.json").write_text(json.dumps({"scatter": [{"assets": ["ph:can"]}]}))
    store = repo / "library_store"
    (store / "lod" / "tree_01").mkdir(parents=True)
    (store / "lod" / "tree_01" / "lod.json").write_text("{}")
    (store / "characters").mkdir()
    (store / "characters" / "jay.blend").write_bytes(b"x")
    def a(cid, path, kind="model", sid=None):
        return cid, {"id": cid, "kind": kind, "source_id": sid or cid.split(":")[1], "files": [{"path": path, "sha256": "s"}]}
    catalog = {"assets": dict([
        a("ph:sky", "polyhaven/sky/sky_4k.exr", "hdri"), a("ph:tree_01", "polyhaven/tree_01/tree_01_1k.gltf"),
        a("ph:tree_02", "polyhaven/tree_02/tree_02_1k.gltf"), a("ph:can", "polyhaven/can/can_1k.gltf"),
        a("ph:unused", "polyhaven/unused/unused_1k.gltf"), a("ph:rock_big_01", "polyhaven/rock_big_01/r.gltf"),
        a("acg:Wall", "ambientcg/Wall/Wall.jpg", "texture"), a("el:theme", "music/theme.mp3", "music"),
        a("ph:direct", "polyhaven/direct/direct.gltf")])}
    spec = {"id": "x", "world": {"set": "street"}, "shots": [{"id": "A", "material": "acg:Wall", "song": "el:theme",
                                                             "prop": "lib:ph:direct"}],
            "assets": {"characters": {"jay": {"file": "library_store/characters/jay.blend"}}}}
    got = P.select_library(spec, catalog, str(repo), str(store))
    why = {k: v["why"] for k, v in got.items()}
    assert why["polyhaven/sky/sky_4k.exr"] == "renderer"            # plain path constant
    assert why["polyhaven/tree_01/tree_01_1k.gltf"] == "renderer"   # f-string pattern
    assert why["polyhaven/tree_02/tree_02_1k.gltf"] == "renderer"
    assert why["polyhaven/rock_big_01/r.gltf"] == "renderer"        # source id constant
    assert why["polyhaven/can/can_1k.gltf"] == "spec"               # via the world kit
    assert why["ambientcg/Wall/Wall.jpg"] == "spec"
    assert why["polyhaven/direct/direct.gltf"] == "spec"            # lib:<id>
    assert why["characters/jay.blend"] == "spec:path"
    assert why["lod/tree_01/lod.json"] == "renderer:lod"
    assert "polyhaven/unused/unused_1k.gltf" not in got              # generic f"polyhaven/{n}/..." does not match
    assert "music/theme.mp3" not in got                              # audio never ships to a render pod
    assert set(P.select_library(spec, catalog, str(repo), str(store), include_renderer=False)) >= {
        "polyhaven/can/can_1k.gltf", "ambientcg/Wall/Wall.jpg"}


def test_select_library_real_sentinel_is_bounded():
    spec = json.load(open(os.path.join(REPO, "episodes", "sentinel", "episode_v4.json")))
    catalog = json.load(open(os.path.join(REPO, "factory", "library", "catalog.json")))
    got = P.select_library(spec, catalog, REPO, "/nonexistent")
    assets = {v["asset"] for v in got.values()}
    assert {"ph:moonlit_golf", "ph:island_tree_01", "ph:brown_planks_05"} <= assets
    assert not any(a and a.startswith("el:") for a in assets)
    assert len(assets) < 25


def test_code_tarball_deterministic_with_spec_and_assets(tmp_path):
    repo = tmp_path / "repo"
    (repo / "cloud" / "farm").mkdir(parents=True)
    (repo / "cloud" / "farm" / "presigned_pod.py").write_text("print('hi')\n")
    (repo / "factory").mkdir()
    (repo / "factory" / "x.py").write_text("x=1\n")
    (repo / "factory" / "node_modules").mkdir()
    (repo / "factory" / "node_modules" / "junk.js").write_text("junk")
    (repo / "studio" / "public" / "assets" / "props").mkdir(parents=True)
    (repo / "studio" / "public" / "assets" / "props" / "boat.glb").write_bytes(b"glb")
    os.symlink("studio/public/assets", repo / "assets")
    (repo / "other.txt").write_text("not shipped")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "cloud", "factory/x.py", "assets", "other.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
                   check=True)
    spec = {"id": "e", "assets": {"props": {"boat": "assets/props/boat.glb"}}}
    sb = json.dumps(spec).encode()
    d1, s1, names = P.code_tarball(str(repo), "episodes/e/spec.json", sb, spec, mode="head")
    d2, s2, _ = P.code_tarball(str(repo), "episodes/e/spec.json", sb, spec, mode="head")
    assert s1 == s2 and d1 == d2
    assert "cloud/farm/presigned_pod.py" in names and "episodes/e/spec.json" in names
    assert "studio/public/assets/props/boat.glb" in names and "assets" in names
    assert "other.txt" not in names and not any("node_modules" in n for n in names)
    with tarfile.open(fileobj=io.BytesIO(d1), mode="r:gz") as tf:
        assert tf.getmember("assets").issym() and tf.extractfile("episodes/e/spec.json").read() == sb
    _, _, wnames = P.code_tarball(str(repo), "episodes/e/spec.json", sb, spec, mode="worktree")
    assert not any("node_modules" in n for n in wnames) and "factory/x.py" in wnames


# ------------------------------------------------------------------------------------------------ submit (moto + mocked RunPod)
def test_submit_uploads_inputs_writes_manifests_and_creates_pods(aws, tmp_path):
    spec_path, spec = tiny_spec(tmp_path)
    api = runpod_api()
    f = farm(aws, tmp_path, api)
    aws.put_object(Bucket=BUCKET, Key="library_store/polyhaven/x/x.gltf", Body=b"{}")   # already synced
    aws.put_object(Bucket=BUCKET, Key="library_store/lod/x/lod.json", Body=b"{}")       # its LOD cache, S3 only
    res = f.submit(spec_path, "preview", workers=2, budget=10, gpu="RTX4090", run_id="r1", code_mode="worktree",
                   library="none", extra_library=["polyhaven/x/x.gltf"], price=0.69)
    assert res["status"] == "RUNNING" and len(res["pods"]) == 2
    posts = api.find("POST", "/v2/pods")
    assert len(posts) == 2
    for c in posts:
        body = c["json"]
        assert c["headers"]["Authorization"] == "Bearer proxy-injected"
        assert set(body["env"]) == {"MANIFEST_URL", "NVIDIA_DRIVER_CAPABILITIES"}
        assert not any(re.search(r"AWS|SECRET|TOKEN", k) for k in body["env"])
        assert "AKIA" not in json.dumps(body) and "testing" not in body["env"]["MANIFEST_URL"].split("?")[0]
        assert body["cloud"] == "SECURE" and body["gpu"]["id"] == "NVIDIA GeForce RTX 4090" and body["disk"] >= 40
        assert body["image"].startswith("nvidia/cuda:") and body["entrypoint"] == ["/bin/bash", "-c"]
        script = decode_bootstrap(body["cmd"][0])
        assert "presigned_pod.py" in script and "AWS_ACCESS_KEY_ID" not in script
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(body["env"]["MANIFEST_URL"]).query)
        assert q["X-Amz-Expires"] == ["604800"]
    keys = set(P.s3_list(aws, BUCKET, "farm/test/"))
    st = json.loads(aws.get_object(Bucket=BUCKET, Key="farm/test/runs/r1/state.json")["Body"].read())
    code_key = st["inputs"]["code"]["key"]
    assert code_key in keys and "farm/test/runs/r1/inputs/episode.json" in keys
    assert [f["key"] for f in st["inputs"]["library"]] == ["library_store/lod/x/lod.json",
                                                         "library_store/polyhaven/x/x.gltf"]  # reused, not uploaded
    assert sorted(c["json"]["name"] for c in posts) == ["story-farm-r1-p0-rtx4090-0", "story-farm-r1-p1-rtx4090-0"]
    assert not any(k.startswith("farm/test/library") for k in keys)
    mans = [json.loads(aws.get_object(Bucket=BUCKET, Key=p["manifestKey"])["Body"].read()) for p in st["pods"]]
    frames = sorted((j["shot"], int(fr)) for m in mans for j in m["jobs"] for fr in j["plates"])
    assert frames == [("S1", 0), ("S1", 1), ("S1", 2), ("S2", 3), ("S2", 4)]
    m = mans[0]
    plate = next(iter(m["jobs"][0]["plates"].values()))
    assert plate["method"] == "PUT" and plate["headers"] == {"Content-Type": "image/png"}
    assert "/farm/test/plates/r1/" in plate["url"] and m["heartbeat"]["method"] == "PUT"
    assert m["code"]["sha256"] == st["inputs"]["code"]["sha256"] and m["library"][1]["path"] == "polyhaven/x/x.gltf"
    assert m["blender"]["sha256"].startswith("3a64efd1")
    assert "testing" not in json.dumps(m).replace("X-Amz-Credential=testing", "")  # only the signature's key id


def test_submit_refuses_over_budget_and_rate(aws, tmp_path):
    spec_path, _ = tiny_spec(tmp_path)
    f = farm(aws, tmp_path, runpod_api())
    with pytest.raises(SystemExit, match="budget"):
        f.submit(spec_path, "preview", workers=1, budget=0.01, run_id="r2", code_mode="worktree", library="none",
                 price=0.69)
    with pytest.raises(SystemExit, match="ceiling"):
        f.submit(spec_path, "preview", workers=2, budget=10, run_id="r2", code_mode="worktree", library="none",
                 price=3.0, max_usd_per_hour=4.0)


def test_dry_run_prints_redacted_payload_and_uploads_nothing(aws, tmp_path):
    spec_path, _ = tiny_spec(tmp_path)
    api = runpod_api()
    res = farm(aws, tmp_path, api).submit(spec_path, "preview", workers=1, budget=10, run_id="dr", dry_run=True,
                                          code_mode="worktree", library="none")
    assert res["dryRun"] and not api.calls
    req = res["pods"][0]["createRequest"]
    assert req["method"] == "POST" and req["url"] == "https://api.runpod.io/v2/pods"
    assert req["body"]["env"]["MANIFEST_URL"].endswith("/runs/dr/pods/dr-p0/manifest.json?REDACTED")
    assert req["body"]["name"] == "story-farm-dr-p0-rtx4090-0"
    assert "X-Amz-Signature" not in json.dumps(res)
    assert not P.s3_list(aws, BUCKET, "farm/test/")


# ------------------------------------------------------------------------------------------------ watch (moto + mocked RunPod)
def _submit(aws, tmp_path, api, clock, workers=2, budget=10):
    spec_path, _ = tiny_spec(tmp_path)
    f = farm(aws, tmp_path, api, clock)
    f.submit(spec_path, "preview", workers=workers, budget=budget, run_id="w1", code_mode="worktree",
             library="none", price=0.69)
    return f, f.load("w1")


def _plate(aws, run, shot, frame):
    aws.put_object(Bucket=BUCKET, Key=f"farm/test/plates/{run}/{shot}/{frame:04d}.png", Body=b"\x89PNG")


def test_watch_dead_pod_is_terminated_and_its_missing_frames_reassigned(aws, tmp_path):
    clock, api = Clock(), runpod_api()
    f, st = _submit(aws, tmp_path, api, clock)
    p0, p1 = st["pods"]
    for pod in (p0, p1):
        P.s3_put_json(aws, BUCKET, f.layout.heartbeat("w1", pod["pod"]), {"state": "rendering"})
    clock.t += 30
    assert f.tick(st) == "RUNNING"
    assert {p["status"] for p in st["pods"]} == {"RUNNING"}
    # p0 delivers one of its frames, then goes silent for > heartbeat_lost_s (moto LastModified is wall clock)
    first = p0["jobSpecs"][0]
    _plate(aws, "w1", first["shot"], first["frameStart"])
    clock.t += 5000  # past heartbeat_lost_s
    P.s3_put_json(aws, BUCKET, f.layout.done("w1", p1["pod"]), {"status": "DONE"})
    for j in p1["jobSpecs"]:
        for fr in range(j["frameStart"], j["frameEnd"] + 1):
            _plate(aws, "w1", j["shot"], fr)
    assert f.tick(st) == "RUNNING"
    deleted = [c["path"].rsplit("/", 1)[1] for c in api.find("DELETE", "/v2/pods/.*")]
    assert sorted(deleted) == sorted([p0["providerId"], p1["providerId"]])
    assert st["pods"][0]["status"] == "DEAD" and st["pods"][1]["status"] == "DONE:DONE"
    new = st["pods"][2]
    assert new["pod"] == "w1-p0r1" and new["generation"] == 1
    want = {(j["shot"], fr) for j in p0["jobSpecs"] for fr in range(j["frameStart"], j["frameEnd"] + 1)}
    got = {(j["shot"], fr) for j in new["jobSpecs"] for fr in range(j["frameStart"], j["frameEnd"] + 1)}
    assert got == want - {(first["shot"], first["frameStart"])}
    man = json.loads(aws.get_object(Bucket=BUCKET, Key=new["manifestKey"])["Body"].read())
    assert sorted(int(k) for j in man["jobs"] for k in j["plates"]) == sorted(fr for _, fr in got)
    # the replacement finishes -> COMPLETE, every pod terminated, plates pulled
    for s, fr in got:
        _plate(aws, "w1", s, fr)
    P.s3_put_json(aws, BUCKET, f.layout.done("w1", new["pod"]), {"status": "DONE"})
    assert f.tick(st) == "COMPLETE"
    assert not api.pods
    dest = tmp_path / "plates"
    pulled = f.pull(st, str(dest))
    assert pulled["fetched"] == 5 and (dest / "S1" / "0000.png").read_bytes() == b"\x89PNG"


def test_watch_boot_timeout_and_replacement_limit(aws, tmp_path):
    clock, api = Clock(), runpod_api()
    f, st = _submit(aws, tmp_path, api, clock, workers=1)
    st["opts"]["max_replacements"] = 1
    clock.t += P.DEFAULTS["boot_timeout_s"] + 1
    f.tick(st)
    assert st["pods"][0]["status"] == "DEAD" and "no heartbeat" in st["pods"][0]["deadReason"]
    assert st["pods"][1]["pod"] == "w1-p0r1"
    clock.t += P.DEFAULTS["boot_timeout_s"] + 1
    assert f.tick(st) == "FAILED"            # second death: replacements exhausted
    assert len(st["pods"]) == 2 and st["abandoned"]


def test_watch_budget_stops_everything(aws, tmp_path):
    clock, api = Clock(), runpod_api()
    f, st = _submit(aws, tmp_path, api, clock, workers=2, budget=1.0)
    for pod in st["pods"]:
        P.s3_put_json(aws, BUCKET, f.layout.heartbeat("w1", pod["pod"]), {"state": "rendering"})
    clock.t += 3600  # 2 pods x $0.69 x 1 h = $1.38 > $1
    st["opts"]["heartbeat_lost_s"] = 10 ** 12
    assert f.tick(st) == "BUDGET_EXCEEDED"
    assert not api.pods and st["spentUsd"] == pytest.approx(1.38, abs=0.01)


def test_provider_reports_pod_gone(aws, tmp_path):
    clock, api = Clock(), runpod_api()
    f, st = _submit(aws, tmp_path, api, clock, workers=1)
    api.pods.clear()   # e.g. host failure / deleted from the console
    f.tick(st)
    assert st["pods"][0]["status"] == "DEAD" and "provider reports" in st["pods"][0]["deadReason"]
    assert len(st["pods"]) == 2


def test_stop_terminates_live_pods(aws, tmp_path):
    clock, api = Clock(), runpod_api()
    f, st = _submit(aws, tmp_path, api, clock)
    out = f.stop("w1")
    assert out["status"] == "STOPPED" and not api.pods


# ------------------------------------------------------------------------------------------------ local pod e2e (moto server)
@pytest.fixture
def moto_server(monkeypatch):
    pytest.importorskip("flask")
    from moto.server import ThreadedMotoServer
    for k, v in {"AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",
                 "AWS_DEFAULT_REGION": REGION}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    srv = ThreadedMotoServer(ip_address="127.0.0.1", port=0)
    srv.start()
    host, port = srv.get_host_and_port()
    from botocore.config import Config
    s3 = boto3.client("s3", region_name=REGION, endpoint_url=f"http://{host}:{port}",
                      config=Config(signature_version="s3v4", s3={"addressing_style": "path"}))
    s3.create_bucket(Bucket=BUCKET)
    yield s3
    srv.stop()


def fake_blender(tmp_path):
    p = tmp_path / "fake-blender"
    p.write_text("#!/bin/bash\nfor a in \"$@\"; do if [ \"$a\" = --python-expr ]; then echo 'blender 4.2.3-fake';"
                 " echo 'CYCLES_DEVICES OPTIX:Fake'; exit 0; fi; done\n"
                 f"exec {sys.executable} {os.path.join(HERE, 'fake_blender.py')} \"$@\"\n")
    p.chmod(0o755)
    return str(p)


@pytest.mark.skipif(not os.path.exists("/bin/bash") or subprocess.run(["which", "curl"]).returncode,
                    reason="needs bash + curl")
def test_local_pod_end_to_end_with_presigned_urls_only(moto_server, tmp_path):
    s3 = moto_server
    spec_path, spec = tiny_spec(tmp_path)
    lib = tmp_path / "lib"
    (lib / "polyhaven" / "t").mkdir(parents=True)
    (lib / "polyhaven" / "t" / "t.gltf").write_text('{"asset": 1}')
    os.environ["LIBRARY_STORE"] = str(lib)
    try:
        pods = LocalPods(str(tmp_path / "pods"), overrides={"BLENDER": fake_blender(tmp_path)})
        f = P.PresignedFarm(s3, BUCKET, P.Layout("farm/test/", "farm/test/library_store/"), "runpod",
                            provider=pods, repo=REPO, state_dir=str(tmp_path / "state"))
        res = f.submit(spec_path, "preview", workers=2, budget=5, run_id="e2e", code_mode="worktree",
                       library="none", extra_library=["polyhaven/t/t.gltf"], price=0.69,
                       opts={"require_gpu": False, "exit_when_done": True, "heartbeat_s": 5})
    finally:
        os.environ.pop("LIBRARY_STORE")
    assert len(res["pods"]) == 2
    for pid, env in pods.envs.items():
        assert not [k for k in env if k.startswith("AWS_")] and "MANIFEST_URL" in env
    assert pods.wait(240), "local pods did not finish"
    st = f.load("e2e")
    assert f.tick(st) == "COMPLETE"
    pulled = f.pull(st, str(tmp_path / "out"))
    assert pulled["fetched"] == 5
    for shot, a, b in (("S1", 0, 3), ("S2", 3, 5)):
        for fr in range(a, b):
            assert (tmp_path / "out" / shot / f"{fr:04d}.png").read_bytes().startswith(b"\x89PNG")
    keys = P.s3_list(s3, BUCKET, "farm/test/runs/e2e/pods/")
    for p in st["pods"]:
        done = json.loads(s3.get_object(Bucket=BUCKET, Key=f.layout.done("e2e", p["pod"]))["Body"].read())
        assert done["status"] == "DONE" and done["framesDone"] == done["framesTotal"]
        assert f.layout.heartbeat("e2e", p["pod"]) in keys and f.layout.pod_log("e2e", p["pod"]) in keys
        for jid in p["jobs"]:
            jm = json.loads(s3.get_object(Bucket=BUCKET, Key=f.layout.job_manifest("e2e", p["pod"], jid))["Body"].read())
            assert jm["status"] == "DONE" and len(jm["files"]) == jm["frameEnd"] - jm["frameStart"] + 1
            assert f.layout.job_log("e2e", p["pod"], jid) in keys
    # the library file went through the presigned GET path
    home = tmp_path / "pods" / "local1"
    assert (home / "library_store" / "polyhaven" / "t" / "t.gltf").read_text() == '{"asset": 1}'
    assert ("terminate", "local1") in pods.calls or not pods.procs


def test_local_pod_without_gpu_fails_fast_and_is_replaced(moto_server, tmp_path):
    s3 = moto_server
    spec_path, _ = tiny_spec(tmp_path, shots=(("S1", 0, 2),))
    pods = LocalPods(str(tmp_path / "pods"), overrides={"BLENDER": fake_blender(tmp_path), "PATH": "/usr/bin:/bin"})
    f = P.PresignedFarm(s3, BUCKET, P.Layout("farm/test/"), "runpod", provider=pods, repo=REPO,
                        state_dir=str(tmp_path / "state"))
    f.submit(spec_path, "preview", workers=1, budget=5, run_id="nogpu", code_mode="worktree", library="none",
             price=0.69, opts={"require_gpu": True, "exit_when_done": True, "heartbeat_s": 5})
    assert pods.wait(120)
    st = f.load("nogpu")
    done = json.loads(s3.get_object(Bucket=BUCKET, Key=f.layout.done("nogpu", st["pods"][0]["pod"]))["Body"].read())
    assert done["status"] == "FAILED" and "GPU" in done["error"]
    f.tick(st)
    assert st["pods"][0]["status"] == "DONE:FAILED" and st["pods"][1]["pod"] == "nogpu-p0r1"
    pods.wait(120)
    f.stop("nogpu")
