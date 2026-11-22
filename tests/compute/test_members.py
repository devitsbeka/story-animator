"""Member nodes: invites, capability hello, limits, revocation, untrusted-result verification and spot checks."""
import json

import pytest

from factory.compute.broker import Broker
from factory.compute.members import MemberNodes, decode_token, encode_token, spot_check_selected
from factory.compute.node import Node, gpu_busy
from factory.compute.store import S3Store

from compute_testkit import BUCKET
from compute_fakes import FakeAdapter, key_of, render_manifest

SPEC = {"id": "ep", "shots": [{"id": "S0", "from": 0, "to": 12}]}


class S3Net:
    """What UrlNet does over HTTP, against moto: a presigned URL is just a key here."""

    def __init__(self, s3):
        self.s3 = s3
        self.bytes_up = self.bytes_down = 0

    def get_bytes(self, url):
        return self.s3.get_object(Bucket=BUCKET, Key=key_of(url))["Body"].read()

    def put_json(self, target, obj):
        self.s3.put_object(Bucket=BUCKET, Key=key_of(target["url"]), Body=json.dumps(obj).encode())


class Run:
    """subprocess.run stand-in for nvidia-smi."""

    def __init__(self, gpus="NVIDIA GeForce RTX 4090, 24564, 3", apps=""):
        self.gpus, self.apps = gpus, apps

    def __call__(self, cmd, **kw):
        class R:
            pass
        r = R()
        r.stdout = self.apps if "--query-compute-apps=pid" in cmd else self.gpus
        return r


def cfg(**kw):
    return {"type": "cpu", "max_runtime_s": 900, "terms": "USE", "trusted": True, "priority": 50,
            "hardware": {"ram_gb": 16}, **kw}


def inputs():
    return {"episodeId": "ep", "code": {"key": "c", "sha256": "0" * 64, "size": 1},
            "spec": {"key": "s", "sha256": "0" * 64, "path": "episodes/ep/ep.json"}, "library": []}


@pytest.fixture
def setup(s3, clock, tmp_path):
    spec = tmp_path / "ep.json"
    spec.write_text(json.dumps(SPEC))
    mcfg = {"adapter": "member_node", "type": "gpu", "max_runtime_s": 7200, "trusted": False, "priority": 5,
            "spf": {"preview": 1.0, "final": 10.0}, "build_s": 5, "cold_start_s": 0, "terms": "USE"}
    tcfg = cfg(priority=90, max_runtime_s=86400)
    conf = {"defaults": {"safety": 0.0, "spot_check_fraction": 0.0}, "providers": {"member_node": mcfg, "trusted": tcfg},
            "gated": {}}
    b = Broker(s3, BUCKET, store=S3Store(s3, BUCKET), config=conf, adapters={}, clock=clock, sleep=clock.sleep,
               state_dir=str(tmp_path / "runs"))
    trusted = FakeAdapter("trusted", tcfg, s3, BUCKET, clock, spf=50, conc=1)
    b.adapters.update({"member_node": MemberNodes("member_node", mcfg, b.members, clock=clock), "trusted": trusted})
    return b, str(spec), trusted


def node_for(b, s3, clock, tmp_path, mode="ok", **kw):
    inv = b.members.invite("alice")
    rendered = []

    def render(a):
        man = json.loads(S3Net(s3).get_bytes(a["manifestUrl"]))
        render_manifest(s3, BUCKET, man, mode)
        rendered.append(a["attempt"])
        return {"rc": 0}
    n = Node(inv["token"], "blender", net=S3Net(s3), run=kw.pop("run", Run()), clock=clock, sleep=clock.sleep,
             state_dir=str(tmp_path / "node"), render=render, **kw)
    n.join()
    return inv, n, rendered


def drive(b, st, nodes, clock, ticks=400):
    for _ in range(ticks):
        st = b.tick(st)
        for n in nodes:
            n.step()
        if st["status"] in ("COMPLETE", "FAILED"):
            break
        clock.advance(5)
    return st


def test_token_roundtrip_and_no_credentials_in_invite(setup, s3):
    b, _, _ = setup
    inv = b.members.invite("bob", days=30)          # capped at 7 days (SigV4 presign limit)
    url = decode_token(inv["token"])
    assert encode_token(url) == inv["token"]
    doc = json.loads(S3Net(s3).get_bytes(url))
    assert doc["kind"] == "story-compute-invite" and set(doc) >= {"hello", "heartbeat", "inbox"}
    blob = json.dumps(doc)
    assert "testing" not in blob.split("X-Amz-Credential")[0]     # no secret key; only presigned signatures
    assert "aws_secret_access_key" not in blob.lower()
    assert inv["expiresAt"] - b.clock() <= 7 * 86400


def test_hello_registers_capabilities_and_limits(setup, s3, clock, tmp_path):
    b, _, _ = setup
    inv, n, _ = node_for(b, s3, clock, tmp_path, max_hours=3, gpu_only_when_idle=True)
    [rec] = b.members.nodes()
    assert rec["hello"]["caps"]["gpu"] and rec["hello"]["caps"]["vramGb"] == 24.0
    assert rec["hello"]["limits"] == {"maxHours": 3, "gpuOnlyWhenIdle": True, "cpuOk": True,
                                      "qualities": ["preview", "final"]}
    n.step()
    ad = b.adapters["member_node"]
    ad.refresh()
    [w] = ad.workers()
    assert w["gpu"] and w["maxRuntimeS"] <= 3 * 3600 and w["trusted"] is False


def test_honest_node_renders_and_passes_probation_check(setup, s3, clock, tmp_path):
    b, spec, trusted = setup
    inv, n, rendered = node_for(b, s3, clock, tmp_path)
    n.step()
    st = b.submit(spec, "preview", res="8x8", inputs=inputs(), run_id="m1")
    st = drive(b, st, [n], clock)
    assert st["status"] == "COMPLETE"
    assert rendered                                           # the node did real work
    v = st["verifications"]
    assert v and v[0]["why"] == "probation" and v[0]["status"] == "passed" and v[0]["psnr"] >= 28
    assert trusted.started                                    # the spot check ran on the trusted provider
    rec = b.members.record(inv["node"])
    assert rec["accepted"] >= 1 and rec["verified"] == 1 and not rec["revoked"]
    keys = [o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET, Prefix="compute/plates/m1/")["Contents"]]
    assert len(keys) == 12


def test_bad_checksum_is_rejected_and_rerendered_elsewhere(setup, s3, clock, tmp_path):
    b, spec, trusted = setup
    inv, n, _ = node_for(b, s3, clock, tmp_path, mode="badsha")
    n.step()
    st = b.submit(spec, "preview", res="8x8", inputs=inputs(), run_id="m2")
    st = drive(b, st, [n], clock, ticks=800)
    assert st["status"] == "COMPLETE"
    assert any(e["ev"] == "rejected" and "sha256" in e["why"] for e in st["events"])
    assert b.members.record(inv["node"])["strikes"] >= 1


def test_lying_node_fails_spot_check_is_revoked_and_its_work_reopened(setup, s3, clock, tmp_path):
    b, spec, trusted = setup
    inv, n, _ = node_for(b, s3, clock, tmp_path, mode="liar")    # right checksums, wrong pictures
    n.step()
    st = b.submit(spec, "preview", res="8x8", inputs=inputs(), run_id="m3")
    st = drive(b, st, [n], clock, ticks=1500)
    assert st["status"] == "COMPLETE"
    assert any(v["status"] == "failed" for v in st["verifications"])
    assert b.members.record(inv["node"])["revoked"]
    assert any(e["ev"] == "node_distrusted" and e["reopened"] >= 1 for e in st["events"])
    assert n.step() == "revoked"
    # every final plate is the trusted render now
    from compute_fakes import png_bytes
    for f in range(12):
        body = s3.get_object(Bucket=BUCKET, Key=f"compute/plates/m3/S0/{f:04d}.png")["Body"].read()
        assert body == png_bytes("S0", f)


def test_lead_can_revoke_any_time(setup, s3, clock, tmp_path):
    b, _, _ = setup
    inv, n, _ = node_for(b, s3, clock, tmp_path)
    assert n.step() == "idle"
    b.members.revoke(inv["node"])
    assert n.step() == "revoked"
    ad = b.adapters["member_node"]
    ad.refresh()
    assert ad.workers() == []
    with pytest.raises(Exception):
        S3Net(s3).get_bytes(decode_token(inv["token"]))     # the invite document is gone


def test_member_limits_enforced_on_the_node(setup, s3, clock, tmp_path):
    b, _, _ = setup
    _, n, _ = node_for(b, s3, clock, tmp_path, max_hours=0.0)
    assert n.step() == "limit"
    _, n2, _ = node_for(b, s3, clock, tmp_path, gpu_only_when_idle=True, run=Run(apps="4242\n"))
    assert n2.step() == "paused"
    _, n3, _ = node_for(b, s3, clock, tmp_path, allow_cpu=False, run=Run(gpus=""))
    assert n3.step() == "no-gpu"
    assert gpu_busy(Run(gpus="RTX, 24000, 80")) and not gpu_busy(Run())


def test_spot_check_selection_is_deterministic_and_about_2_percent():
    picks = sum(spot_check_selected(f"attempt-{i}", 0.02) for i in range(20000))
    assert 300 <= picks <= 500
    assert spot_check_selected("x", 0.02) == spot_check_selected("x", 0.02)
