"""A provider whose "pods" are local subprocesses running the exact container command a RunPod pod would get.

launch() takes the same (n, gpu_class, env, startup) as providers.runpod.RunPod.launch, then runs
`bash -c <startup>` with ONLY the pod env (MANIFEST_URL, NVIDIA_DRIVER_CAPABILITIES) plus a few local overrides
(PATH, HOME, proxy/CA vars this sandbox needs to reach S3, BLENDER, PRESIGNED_HOME). It refuses to start a pod
whose env carries anything that looks like a credential, and asserts no AWS_* variable reaches the process."""
import os
import re
import subprocess
import time

from providers import PENDING, RUNNING, STOPPED, TERMINATED, WorkerHandle

PASS_THROUGH = ("PATH", "HOME", "LANG", "HTTPS_PROXY", "https_proxy", "NO_PROXY", "no_proxy", "CURL_CA_BUNDLE",
                "SSL_CERT_FILE")
CRED = re.compile(r"AWS_|SECRET|TOKEN|PASSWORD|API_KEY")


class LocalPods:
    name = "localpod"
    default_prices = {"RTX4090": 0.69, "CPU": 0.0}

    def __init__(self, root, overrides=None, price=0.69):
        self.root, self.overrides, self.price = root, dict(overrides or {}), price
        self.procs, self.handles, self.envs, self.calls = {}, {}, {}, []
        self.n = 0

    def for_pod(self, pod):
        self._next_name = pod
        return self

    def price_per_hour(self, gpu_class):
        return self.price

    def launch(self, n, gpu_class, env, startup, spot=False):
        bad = [k for k in env if CRED.search(k)]
        assert not bad, f"pod env must not carry credentials: {bad}"
        out = []
        for _ in range(n):
            self.n += 1
            pid = f"local{self.n}"
            home = os.path.join(self.root, pid)
            os.makedirs(home, exist_ok=True)
            penv = {k: os.environ[k] for k in PASS_THROUGH if k in os.environ}
            penv.update(env)
            penv.update({"PRESIGNED_HOME": home, **self.overrides})
            assert not [k for k in penv if k.startswith("AWS_")]
            cmd = startup.replace("/tmp/presigned-startup.sh", os.path.join(home, "startup.sh"))
            log = open(os.path.join(home, "process.log"), "w")
            self.procs[pid] = subprocess.Popen(["bash", "-c", cmd], env=penv, stdout=log, stderr=subprocess.STDOUT)
            self.envs[pid] = penv
            self.calls.append(("launch", pid, sorted(env)))
            h = WorkerHandle(self.name, pid, gpu_class, PENDING, self.price, False,
                             detail={"name": getattr(self, "_next_name", None)})
            self.handles[pid] = h
            out.append(h)
        return out

    def list(self):
        out = []
        for pid, h in self.handles.items():
            p = self.procs.get(pid)
            if p is None:
                continue
            h.status = RUNNING if p.poll() is None else STOPPED
            out.append(h)
        return out

    def terminate(self, ids):
        for pid in ids:
            p = self.procs.pop(pid, None)
            if p and p.poll() is None:
                p.terminate()
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    p.kill()
            if pid in self.handles:
                self.handles[pid].status = TERMINATED
            self.calls.append(("terminate", pid))
        return list(ids)

    def wait(self, timeout=600, poll=1.0):
        t = time.time()
        while time.time() - t < timeout:
            if all(p.poll() is not None for p in self.procs.values()):
                return True
            time.sleep(poll)
        return False
