"""Startup script: lint (shellcheck + bash -n), rendering rules, a real run against stubs, dry-run, IAM policy."""
import json
import os
import shutil
import stat
import subprocess
import sys

import pytest

import scheduler as sched
from providers import startup

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
CODE = {"FARM_CODE_SOURCE": "git", "FARM_GIT_URL": "https://github.com/o/r.git", "FARM_GIT_COMMIT": "b" * 40}


def shellcheck():
    return os.environ.get("SHELLCHECK") or shutil.which("shellcheck")


@pytest.mark.skipif(not shellcheck(), reason="shellcheck not installed (pip install shellcheck-py)")
def test_shellcheck_template_and_rendered(tmp_path):
    rendered = tmp_path / "startup.sh"
    rendered.write_text(startup.render_startup(CODE))
    r = subprocess.run([shellcheck(), "-s", "bash", "-S", "style", startup.TEMPLATE, str(rendered)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_bash_syntax(tmp_path):
    p = tmp_path / "s.sh"
    p.write_text(startup.render_startup(CODE))
    assert subprocess.run(["bash", "-n", str(p)]).returncode == 0


def test_render_pins_blender_and_commit_and_refuses_secrets():
    s = startup.render_startup(CODE)
    assert "export BLENDER_VERSION=4.2.3" in s and f"export FARM_GIT_COMMIT={'b' * 40}" in s
    assert "export BLENDER_SHA256=3a64efd1982465395abab4259b4091d5c8c56054c7267e9633e4f702a71ea3f4" in s
    # same checksum as the Docker image
    with open(os.path.join(REPO, "cloud", "farm", "Dockerfile")) as fh:
        assert startup.BLENDER["BLENDER_SHA256"] in fh.read()
    for bad in ({"AWS_SECRET_ACCESS_KEY": "x"}, {"GIT_TOKEN": "x"}, {"lower": "x"}, {"A": "x\ny"}):
        with pytest.raises(ValueError):
            startup.render_startup(bad)
    assert startup.render_startup({"FARM_GIT_URL": "https://x/y z"}).count("'https://x/y z'") == 1


def test_bootstrap_roundtrip_and_size():
    s = startup.render_startup(CODE)
    cmd = startup.bootstrap_command(s)
    assert startup.decode_bootstrap(cmd) == s
    assert len(cmd) < 8000 and "\n" not in cmd   # RunPod limit 100 KB; one line for docker args


def make_exe(path, text):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def stub_env(tmp_path):
    """A world where worker_startup.sh can run end to end without root, apt, GPU, Blender or network."""
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    make_exe(bin_ / "apt-get", "#!/bin/sh\nexit 0\n")
    make_exe(bin_ / "sudo", '#!/bin/sh\nexec "$@"\n')
    make_exe(bin_ / "nvidia-smi", '#!/bin/sh\n[ -n "$FAKE_NO_GPU" ] && exit 9\n'
                                  'echo "GPU 0: NVIDIA GeForce RTX 4090 (UUID: GPU-1)"\n')
    bl = tmp_path / "blender"
    bl.mkdir()
    make_exe(bl / "blender", '#!/bin/sh\ncase "$*" in *CYCLES_DEVICES*) echo "CYCLES_DEVICES ${FAKE_DEVICES:-'
                             'OPTIX:NVIDIA GeForce RTX 4090}";; *) echo "blender 4.2.3";; esac\n')
    venv = tmp_path / "venv" / "bin"
    venv.mkdir(parents=True)
    os.symlink(sys.executable, venv / "python")
    make_exe(venv / "pip", "#!/bin/sh\nexit 0\n")
    # a tiny "repo" whose worker.py dumps its environment
    src = tmp_path / "src"
    (src / "cloud" / "farm").mkdir(parents=True)
    (src / "cloud" / "farm" / "worker.py").write_text(
        "import json, os, sys\njson.dump(dict(os.environ), open(os.environ['OUT_JSON'], 'w'))\nprint('worker ran')\n")
    git = ["git", "-C", str(src), "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(["git", "init", "-q", str(src)], check=True)
    subprocess.run([*git, "config", "uploadpack.allowAnySHA1InWant", "true"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "w"], check=True)
    sha = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    env = {"PATH": f"{bin_}:/usr/local/bin:/usr/bin:/bin", "HOME": str(tmp_path),
           "FARM_BUCKET": "b", "FARM_QUEUE_URL": "https://sqs/q", "FARM_TABLE": "t", "AWS_REGION": "us-east-1",
           "AWS_ACCESS_KEY_ID": "AKIA", "AWS_SECRET_ACCESS_KEY": "s", "GIT_TOKEN": "ghp_secret",
           "FARM_PROVIDER": "runpod", "FARM_GPU_CLASS": "RTX4090", "RUNPOD_POD_ID": "pod123",
           "BLENDER_DIR": str(bl), "FARM_VENV": str(tmp_path / "venv"), "FARM_ROOT": str(tmp_path / "root"),
           "FARM_WORK_DIR": str(tmp_path / "work"), "FARM_CACHE_DIR": str(tmp_path / "cache"),
           "OUT_JSON": str(tmp_path / "worker_env.json")}
    script = tmp_path / "startup.sh"
    script.write_text(startup.render_startup({"FARM_CODE_SOURCE": "git", "FARM_GIT_URL": f"file://{src}",
                                              "FARM_GIT_COMMIT": sha}))
    return {"env": env, "script": script, "sha": sha, "tmp": tmp_path}


def run(stub, **extra):
    env = {**stub["env"], **extra}
    return subprocess.run(["bash", str(stub["script"])], env=env, capture_output=True, text=True, timeout=120)


def test_startup_script_runs_end_to_end_against_stubs(stub_env):
    r = run(stub_env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "worker ran" in r.stdout and "CYCLES_DEVICES OPTIX:NVIDIA GeForce RTX 4090" in r.stdout
    got = json.loads((stub_env["tmp"] / "worker_env.json").read_text())
    root = str(stub_env["tmp"] / "root")
    assert got["FARM_REPO"] == root and got["BLENDER"].endswith("/blender/blender") and got["FARM_IMDS"] == "0"
    assert got["FARM_PROVIDER_WORKER_ID"] == "runpod:pod123" and got["REQUIRE_GPU"] == "1"
    assert got["LIBRARY_STORE"] == str(stub_env["tmp"] / "cache" / "library_store")
    assert "GIT_TOKEN" not in got                                   # the token never reaches the worker
    head = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert head == stub_env["sha"]
    assert os.path.islink(os.path.join(root, "assets"))
    assert "ghp_secret" not in r.stdout + r.stderr


def test_startup_vast_worker_id(stub_env):
    r = run(stub_env, FARM_PROVIDER="vastai", RUNPOD_POD_ID="", VAST_CONTAINERLABEL="C.31337")
    assert r.returncode == 0, r.stderr
    assert json.loads((stub_env["tmp"] / "worker_env.json").read_text())["FARM_PROVIDER_WORKER_ID"] == "vastai:31337"


def test_startup_fails_fast_without_gpu_or_secrets(stub_env):
    assert run(stub_env, FAKE_NO_GPU="1").returncode == 3
    r = run(stub_env, FAKE_DEVICES="CPU")
    assert r.returncode == 3 and "no OptiX/CUDA" in r.stdout
    assert run(stub_env, AWS_SECRET_ACCESS_KEY="").returncode == 2
    # CPU class (REQUIRE_GPU=0) runs without a GPU
    assert run(stub_env, FAKE_NO_GPU="1", FAKE_DEVICES="CPU", REQUIRE_GPU="0").returncode == 0


def test_startup_wrong_commit_fails(stub_env):
    s = stub_env["script"].read_text().replace(stub_env["sha"], "0" * 40)
    stub_env["script"].write_text(s)
    assert run(stub_env).returncode != 0
    assert not (stub_env["tmp"] / "worker_env.json").exists()


def test_code_bundle_has_the_renderer():
    try:
        head = startup.git_head()
    except subprocess.CalledProcessError:
        pytest.skip("not a git checkout")
    data, sha = startup.code_bundle(head)
    names = startup.bundle_members(data)
    assert "cloud/farm/worker.py" in names and "cloud/blender/render_episode.py" in names
    assert not any(n.startswith("episodes/") for n in names)
    assert startup.code_bundle(head)[1] == sha        # deterministic


def test_dry_run_writes_reviewable_files(tmp_path):
    out = tmp_path / "dry"
    files = sched.dry_run(sched.load_config(), str(out), commit="c" * 40)
    assert {"startup.sh", "bootstrap.txt", "plan.json", "payloads/runpod-RTX4090.json",
            "payloads/vastai-RTX4090.json", "payloads/aws_ec2-L4.json", "payloads/local-CPU.json"} <= set(files)
    rp = json.loads((out / "payloads" / "runpod-RTX4090.json").read_text())
    body = rp["bodies"][0]
    assert rp["url"] == "https://api.runpod.io/v2/pods" and body["env"]["AWS_SECRET_ACCESS_KEY"] == "REDACTED"
    assert startup.decode_bootstrap(body["cmd"][0]) == (out / "startup.sh").read_text()
    vast = json.loads((out / "payloads" / "vastai-RTX4090.json").read_text())
    assert "-e AWS_SECRET_ACCESS_KEY=REDACTED" in vast["create"]["body"]["env"]
    plan = json.loads((out / "plan.json").read_text())
    assert plan["options"][0]["option"].startswith("aws_ec2/")
    assert subprocess.run(["bash", "-n", str(out / "startup.sh")]).returncode == 0


def test_cli_plan_and_dry_run(tmp_path, capsys):
    sched.main(["--state-dir", str(tmp_path), "plan", "--gpu-hours", "10"])
    rows = json.loads(capsys.readouterr().out)["options"]
    assert {r["option"] for r in rows} >= {"runpod/RTX4090/ondemand", "vastai/L40S/ondemand", "local/CPU/ondemand"}
    sched.main(["--state-dir", str(tmp_path), "plan", "--spec",
                os.path.join(REPO, "episodes", "sentinel", "episode_v2.json"), "--quality", "preview"])
    assert json.loads(capsys.readouterr().out)["gpuHoursA10G"] > 0


class CfnLoader(__import__("yaml").SafeLoader):
    pass


CfnLoader.add_multi_constructor("!", lambda loader, suffix, node: None)


def test_external_worker_policy_in_template_and_user_off_by_default():
    import yaml
    with open(os.path.join(REPO, "cloud", "farm", "infra", "farm.yaml")) as fh:
        t = yaml.load(fh, Loader=CfnLoader)
    pol = t["Resources"]["ExternalWorkerPolicy"]
    assert pol["Type"] == "AWS::IAM::ManagedPolicy"
    actions = {a for st in pol["Properties"]["PolicyDocument"]["Statement"]
               for a in ([st["Action"]] if isinstance(st["Action"], str) else st["Action"])}
    assert actions == {"s3:GetObject", "s3:ListBucket", "s3:PutObject", "sqs:ReceiveMessage", "sqs:DeleteMessage",
                       "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes", "dynamodb:GetItem",
                       "dynamodb:UpdateItem"}
    user = t["Resources"]["ExternalWorkerUser"]
    assert user["Condition"] == "MakeExternalWorkerUser" and user["Properties"]["UserName"] == "farm-worker-external"
    assert t["Parameters"]["CreateExternalWorkerUser"]["Default"] == "false"
    assert not any(r["Type"] == "AWS::IAM::AccessKey" for r in t["Resources"].values())
