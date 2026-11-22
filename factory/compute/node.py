"""
node.py - the member-node worker: lend your own machine to the episode farm with one command.

    python -m factory.compute.node --join sfc1.XXXX [--blender /path/to/blender] [--max-hours 20]
                                   [--gpu-only-when-idle] [--no-cpu] [--qualities preview,final] [--once]

or, as a container (same thing inside the published Lambda image, which has Blender 4.2.3):
    docker run --rm -e JOIN=sfc1.XXXX <image> python3 -m factory.compute.node --join "$JOIN"

What it does (standard library only; it never sees or needs any cloud credential):
  1. resolves the invite token (a presigned GET of the invite) -> presigned PUT hello/heartbeat, GET inbox
  2. detects its capabilities (nvidia-smi GPU + VRAM, CPU count, RAM) and PUTs them with YOUR limits
  3. polls the inbox; an assignment carries one chunk-manifest URL -> renders it exactly like the Lambda worker
     (factory/compute/aws_lambda/handler.py): GET code/spec/library (sha256-checked), Blender, PUT frames
  4. enforces your limits locally: --max-hours (rendering time per node lifetime, kept in
     ~/.story-compute-node/<node>.json), --gpu-only-when-idle (another process on the GPU or >15 % utilisation ->
     paused), --no-cpu (refuse work when no GPU), qualities
  5. stops when the lead revokes the invite (inbox state "revoked") or the URLs expire

The lead cannot run anything on your machine except Blender on the episode files the manifest names, and you
can stop at any time (Ctrl-C); an interrupted chunk is simply re-queued elsewhere.
"""
import argparse
import json
import os
import platform
import re
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = "1"


def log(event, **kw):
    print(json.dumps({"t": round(time.time(), 1), "event": event, **kw}, default=str), flush=True)


def _handler_module():
    sys.path.insert(0, os.path.join(HERE, "aws_lambda"))
    import handler  # noqa: E402
    return handler


def gpu_info(run=subprocess.run):
    try:
        r = run(["nvidia-smi", "--query-gpu=name,memory.total,utilization.gpu", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return []
    out = []
    for line in (r.stdout or "").splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) >= 3:
            try:
                out.append({"name": parts[0], "vramGb": round(float(parts[1]) / 1024, 1), "util": float(parts[2])})
            except ValueError:
                continue
    return out


def gpu_busy(run=subprocess.run, util_threshold=15.0):
    """True when someone else is using the GPU (compute processes or utilisation above threshold)."""
    g = gpu_info(run)
    if not g:
        return False
    if any(x["util"] > util_threshold for x in g):
        return True
    try:
        r = run(["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"], capture_output=True, text=True,
                timeout=20)
        pids = [p for p in (r.stdout or "").split() if p.strip().isdigit() and int(p) != os.getpid()]
        return bool(pids)
    except (OSError, subprocess.TimeoutExpired):
        return False


def ram_gb():
    try:
        with open("/proc/meminfo") as fh:
            m = re.search(r"MemTotal:\s+(\d+) kB", fh.read())
        return round(int(m.group(1)) / 1024 / 1024, 1)
    except (OSError, AttributeError):
        return None


def capabilities(run=subprocess.run):
    g = gpu_info(run)
    return {"gpu": bool(g), "gpuName": g[0]["name"] if g else None, "vramGb": g[0]["vramGb"] if g else None,
            "gpus": len(g), "cpus": os.cpu_count(), "ramGb": ram_gb(), "os": platform.platform(),
            "arch": platform.machine()}


class Node:
    def __init__(self, token, blender, max_hours=None, gpu_only_when_idle=False, allow_cpu=True,
                 qualities=("preview", "final"), state_dir=None, poll_s=20, net=None, run=subprocess.run,
                 clock=time.time, sleep=time.sleep, render=None):
        from .members import decode_token
        self.invite_url = decode_token(token)
        self.blender = blender
        self.max_hours, self.gpu_only_when_idle, self.allow_cpu = max_hours, gpu_only_when_idle, allow_cpu
        self.qualities = list(qualities)
        self.state_dir = state_dir or os.path.expanduser("~/.story-compute-node")
        self.poll_s, self.run, self.clock, self.sleep = poll_s, run, clock, sleep
        self.net = net
        self.render = render
        self.inv = None
        self.caps = None
        self.state = {"hoursUsed": 0.0, "lastV": -1, "done": []}

    # --- io
    def _net(self):
        if self.net is None:
            self.net = _handler_module().UrlNet()
        return self.net

    def get_json(self, url):
        return json.loads(self._net().get_bytes(url))

    def put_json(self, target, obj):
        self._net().put_json(target, obj)

    def _state_path(self):
        return os.path.join(self.state_dir, f"{self.inv['node']}.json")

    def load_state(self):
        try:
            with open(self._state_path()) as fh:
                self.state.update(json.load(fh))
        except (OSError, ValueError):
            pass

    def save_state(self):
        os.makedirs(self.state_dir, exist_ok=True)
        with open(self._state_path(), "w") as fh:
            json.dump(self.state, fh)

    # --- protocol
    def join(self):
        self.inv = self.get_json(self.invite_url)
        if self.inv.get("kind") != "story-compute-invite":
            raise SystemExit("this token does not point at a story-compute invite")
        self.load_state()
        self.caps = capabilities(self.run)
        hello = {"node": self.inv["node"], "t": self.clock(), "version": VERSION, "caps": self.caps,
                 "limits": {"maxHours": self.max_hours, "gpuOnlyWhenIdle": self.gpu_only_when_idle,
                            "cpuOk": self.allow_cpu, "qualities": self.qualities}}
        self.put_json(self.inv["hello"], hello)
        log("joined", node=self.inv["node"], caps=self.caps)
        return hello

    def beat(self, state, **kw):
        hb = {"t": self.clock(), "node": self.inv["node"], "state": state, "hoursUsed": round(self.state["hoursUsed"], 4),
              "paused": state == "paused", **kw}
        try:
            self.put_json(self.inv["heartbeat"], hb)
        except Exception as e:  # noqa: BLE001
            log("heartbeat_failed", error=str(e)[:200])

    def refusal(self):
        """Why this node must not take work right now (member limits), or None."""
        if self.max_hours is not None and self.state["hoursUsed"] >= float(self.max_hours):
            return "limit"
        if not self.caps.get("gpu") and not self.allow_cpu:
            return "no-gpu"
        if self.gpu_only_when_idle and self.caps.get("gpu") and gpu_busy(self.run):
            return "paused"
        return None

    def step(self):
        """One poll. -> 'revoked' | 'idle' | 'rendered' | 'paused' | 'limit' | ..."""
        try:
            inbox = self.get_json(self.inv["inbox"]["url"])
        except Exception as e:  # noqa: BLE001 - expired or deleted invite
            log("inbox_unreachable", error=str(e)[:200])
            return "unreachable"
        if inbox.get("state") == "revoked":
            log("revoked", reason=inbox.get("reason"))
            self.beat("revoked")
            return "revoked"
        if inbox.get("renew"):
            self.inv.update({k: inbox["renew"][k] for k in ("hello", "heartbeat", "inbox") if k in inbox["renew"]})
        why = self.refusal()
        if why:
            self.beat(why if why != "no-gpu" else "refused")
            return why
        a = inbox.get("assignment") if inbox.get("state") == "work" else None
        if not a or int(inbox.get("v", 0)) <= int(self.state["lastV"]) or a["attempt"] in self.state["done"]:
            self.beat("idle", lastAttempt=self.state.get("lastAttempt"), lastHours=self.state.get("lastHours"))
            return "idle"
        self.state["lastV"] = int(inbox.get("v", 0))
        self.beat("rendering", attempt=a["attempt"])
        t0 = self.clock()
        try:
            out = (self.render or self._render)(a)
            ok = out.get("rc") == 0
        except Exception as e:  # noqa: BLE001
            out, ok = {"error": f"{type(e).__name__}: {e}"[:300]}, False
        hours = (self.clock() - t0) / 3600.0
        self.state["hoursUsed"] += hours
        self.state.update(lastAttempt=a["attempt"], lastHours=round(hours, 5))
        self.state["done"] = (self.state["done"] + [a["attempt"]])[-50:]
        self.save_state()
        if ok:
            self.beat("idle", lastAttempt=a["attempt"], lastHours=round(hours, 5))
        else:
            self.beat("failed", attempt=a["attempt"], error=out.get("error") or out.get("errors"))
        log("chunk", attempt=a["attempt"], ok=ok, hours=round(hours, 4))
        return "rendered" if ok else "failed"

    def _render(self, a):
        h = _handler_module()
        os.environ.setdefault("CHUNK_TMP", os.path.join(self.state_dir, "work"))
        h.TMP = os.environ["CHUNK_TMP"]
        return h.handler({"manifestUrl": a["manifestUrl"], "attempt": a["attempt"], "chunk": a.get("chunk")},
                         blender=self.blender)

    def loop(self, once=False):
        self.join()
        while True:
            r = self.step()
            if r in ("revoked", "unreachable") or once:
                return r
            if r == "limit":
                log("max_hours_reached", hours=self.state["hoursUsed"])
                return r
            self.sleep(self.poll_s if r != "rendered" else 1)


def main(argv=None):
    p = argparse.ArgumentParser(description="Lend this machine to the episode render farm (presigned URLs only).")
    p.add_argument("--join", default=os.environ.get("JOIN"), required=not os.environ.get("JOIN"))
    p.add_argument("--blender", default=os.environ.get("BLENDER", "blender"))
    p.add_argument("--max-hours", type=float, default=None, help="stop taking work after this much render time")
    p.add_argument("--gpu-only-when-idle", action="store_true", help="pause while anything else uses the GPU")
    p.add_argument("--no-cpu", action="store_true", help="refuse work on a machine without a GPU")
    p.add_argument("--qualities", default="preview,final")
    p.add_argument("--poll", type=float, default=20)
    p.add_argument("--once", action="store_true", help="one poll, then exit (testing)")
    a = p.parse_args(argv)
    n = Node(a.join, a.blender, a.max_hours, a.gpu_only_when_idle, not a.no_cpu, a.qualities.split(","),
             poll_s=a.poll)
    r = n.loop(once=a.once)
    log("node_exit", reason=r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
