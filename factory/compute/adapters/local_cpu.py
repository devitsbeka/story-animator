"""
local_cpu.py - render chunks on this machine with the SAME code path as the Lambda worker.

Each task is a child process `python3 -m factory.compute.adapters.local_cpu <manifestUrl> <attempt>` that runs
factory/compute/aws_lambda/handler.py:handler (presigned GET/PUT only, no credentials in its env), with the local
Blender (BLENDER env or /opt/blender/blender-4.2.3-linux-x64/blender) and CHUNK_TMP under the compute state dir.
"""
import json
import os
import subprocess
import sys

from .base import Adapter

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DEFAULT_BLENDER = "/opt/blender/blender-4.2.3-linux-x64/blender"


class LocalCpu(Adapter):
    name = "local_cpu"

    def __init__(self, pid, cfg, clock=None, tmp=None, blender=None, python=sys.executable):
        super().__init__(pid, cfg, clock)
        from ..registry import state_dir
        self.tmp = tmp or os.path.join(state_dir(), "local_tmp")
        self.blender = blender or os.environ.get("BLENDER") or DEFAULT_BLENDER
        self.python = python

    def available(self):
        if not os.path.isfile(self.blender):
            return False, f"no Blender at {self.blender}"
        return True, f"{self.concurrency()} local slot(s), {self.blender}"

    def start(self, task):
        os.makedirs(self.tmp, exist_ok=True)
        logp = os.path.join(self.tmp, f"{task['attempt']}.log")
        env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}   # credential-free like Lambda
        env.update(CHUNK_TMP=self.tmp, BLENDER=self.blender, PYTHONPATH=REPO, HOME=env.get("HOME", "/tmp"))
        with open(logp, "ab") as lf:
            proc = subprocess.Popen([self.python, "-m", "factory.compute.adapters.local_cpu", task["manifestUrl"],
                                     task["attempt"], task.get("chunk") or ""], cwd=REPO, env=env, stdout=lf,
                                    stderr=subprocess.STDOUT, start_new_session=True)
        h = {"attempt": task["attempt"], "pid": proc.pid, "t0": self.clock(), "log": logp, "provider": self.pid}
        self.running[task["attempt"]] = {**h, "_proc": proc}
        return h

    def poll(self, handle):
        rec = self.running.get(handle["attempt"])
        proc = rec and rec.get("_proc")
        if proc is None:
            return {"state": "lost"}
        rc = proc.poll()
        if rc is None:
            return {"state": "running"}
        return {"state": "exited" if rc == 0 else "failed", "rc": rc, "usage": {},
                "seconds": round(self.clock() - handle["t0"], 1)}

    def cancel(self, handle):
        rec = self.running.pop(handle["attempt"], None)
        if rec and rec.get("_proc") and rec["_proc"].poll() is None:
            rec["_proc"].kill()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    sys.path.insert(0, os.path.join(REPO, "factory", "compute", "aws_lambda"))
    import handler  # noqa: E402 - the Lambda handler, run locally
    out = handler.handler({"manifestUrl": argv[0], "attempt": argv[1], "chunk": argv[2] if len(argv) > 2 else None},
                          blender=os.environ.get("BLENDER", DEFAULT_BLENDER))
    print(json.dumps(out))
    return 0 if out.get("rc") == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
