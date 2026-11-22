"""
members.py - member nodes: team members lend THEIR OWN machine (or a cloud VM in THEIR OWN account) to the farm.

The broker never creates accounts, never registers anywhere on anyone's behalf and never holds a member's
credentials; a member never receives ours. Everything between them is presigned S3 URLs signed by the lead:

  lead:   python -m factory.compute invite --name alice [--days 7]      -> token "sfc1.<base64url(invite URL)>"
  member: python -m factory.compute.node --join sfc1.... [--max-hours 20] [--gpu-only-when-idle] [--no-cpu]
  lead:   python -m factory.compute revoke --node <id>                   (any time; takes effect on the node's
                                                                         next poll, all its URLs expire <= 7 d)

Objects (operator credentials; under compute/nodes/<node>/):
  record.json     lead-side record: name, created/expires, revoked, strikes, accepted/verified chunk counts
  invite.json     what the token points at: PUT hello, PUT heartbeat, GET inbox (presigned, <= 7 days)
  hello.json      PUT by the node at join: capabilities it detected (GPU/VRAM/CPU/RAM) + the member's limits
  heartbeat.json  PUT by the node every poll: state, attempt, hours used, paused (GPU busy) ...
  inbox.json      PUT by the broker: {"state": idle|work|revoked, "assignment": {attempt, chunk, manifestUrl},
                  "renew": {fresh hello/heartbeat/inbox URLs}} - the ONLY way work reaches a node

Untrusted results: plates of a node's chunk go to an attempt-scoped prefix, never to the run's plates directly.
The broker accepts a chunk only if every frame exists, is a decodable PNG of the expected size and matches the
sha256 the node reported; then copies it into place. A deterministic ~2 % of a node's chunks (and its first one,
probation) are re-rendered on a trusted provider and compared (downsampled PSNR); a mismatch revokes the node and
re-opens every chunk it delivered.
"""
import base64
import hashlib
import json
import time
import uuid

from .adapters.base import Adapter

TOKEN_PREFIX = "sfc1."
NODES = "compute/nodes/"
MAX_EXPIRY_S = 7 * 24 * 3600


def encode_token(invite_url):
    return TOKEN_PREFIX + base64.urlsafe_b64encode(invite_url.encode()).decode().rstrip("=")


def decode_token(token):
    token = token.strip()
    if not token.startswith(TOKEN_PREFIX):
        raise ValueError("not a story-compute invite token (expected sfc1....)")
    b = token[len(TOKEN_PREFIX):]
    return base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)).decode()


def presign(s3, method, bucket, key, expires, content_type=None):
    expires = int(min(max(60, expires), MAX_EXPIRY_S))
    params = {"Bucket": bucket, "Key": key}
    headers = {}
    if method == "PUT":
        if content_type:
            params["ContentType"] = content_type
            headers["Content-Type"] = content_type
        url = s3.generate_presigned_url("put_object", Params=params, ExpiresIn=expires, HttpMethod="PUT")
    else:
        url = s3.generate_presigned_url("get_object", Params=params, ExpiresIn=expires, HttpMethod="GET")
    return {"url": url, "method": method, "headers": headers}


def spot_check_selected(attempt, fraction):
    """Deterministic ~fraction selection (auditable: anyone can recompute which chunks were checked)."""
    h = int(hashlib.sha256(attempt.encode()).hexdigest()[:8], 16)
    return (h % 10000) < fraction * 10000


class Members:
    """Lead-side node registry. `store` = S3Store (or MemoryStore in tests), `s3` = boto3 client for presigning."""

    def __init__(self, store, s3, bucket, clock=time.time, lost_s=600, hello_ttl_s=900):
        self.store, self.s3, self.bucket, self.clock = store, s3, bucket, clock
        self.lost_s, self.hello_ttl_s = lost_s, hello_ttl_s

    def k(self, node, name):
        return f"{NODES}{node}/{name}"

    def _urls(self, node, expires):
        return {"hello": presign(self.s3, "PUT", self.bucket, self.k(node, "hello.json"), expires, "application/json"),
                "heartbeat": presign(self.s3, "PUT", self.bucket, self.k(node, "heartbeat.json"), expires,
                                     "application/json"),
                "inbox": presign(self.s3, "GET", self.bucket, self.k(node, "inbox.json"), expires)}

    # --- invites
    def invite(self, name, days=7.0, note=None):
        node = f"n-{uuid.uuid4().hex[:10]}"
        exp = int(min(days * 86400, MAX_EXPIRY_S))
        now = self.clock()
        rec = {"node": node, "name": name, "createdAt": now, "expiresAt": now + exp, "revoked": False,
               "strikes": 0, "accepted": 0, "verified": 0, "failedChecks": 0, "note": note}
        self.store.put_json(self.k(node, "record.json"), rec)
        inv = {"kind": "story-compute-invite", "v": 1, "node": node, "name": name, "expiresAt": now + exp,
               **self._urls(node, exp),
               "rules": {"credentials": "none: every transfer is a presigned URL",
                         "limits": "the member sets max hours / GPU-only-when-idle on the node",
                         "verification": "checksums + ~2% re-rendered elsewhere"}}
        self.store.put_json(self.k(node, "invite.json"), inv)
        self.store.put_json(self.k(node, "inbox.json"), {"v": 0, "state": "idle", "t": now})
        url = presign(self.s3, "GET", self.bucket, self.k(node, "invite.json"), exp)["url"]
        return {"node": node, "name": name, "expiresAt": now + exp, "token": encode_token(url)}

    def revoke(self, node, reason="revoked by lead"):
        rec, _ = self.store.get_json(self.k(node, "record.json"))
        if not rec:
            raise KeyError(f"unknown node {node}")
        rec.update(revoked=True, revokedAt=self.clock(), revokeReason=reason)
        self.store.put_json(self.k(node, "record.json"), rec)
        self.store.put_json(self.k(node, "inbox.json"), {"v": 10 ** 9, "state": "revoked", "reason": reason,
                                                       "t": self.clock()})
        self.store.delete(self.k(node, "invite.json"))      # the token stops resolving at once
        return rec

    def record(self, node):
        return self.store.get_json(self.k(node, "record.json"))[0]

    def update_record(self, node, **inc):
        rec, _ = self.store.get_json(self.k(node, "record.json"))
        if rec is None:
            return None
        for key, v in inc.items():
            if isinstance(v, (int, float)) and isinstance(rec.get(key), (int, float)):
                rec[key] = rec[key] + v
            else:
                rec[key] = v
        self.store.put_json(self.k(node, "record.json"), rec)
        return rec

    def nodes(self):
        out = []
        for key in self.store.list(NODES):
            if key.endswith("/record.json"):
                node = key[len(NODES):].split("/", 1)[0]
                rec, _ = self.store.get_json(key)
                hello, _ = self.store.get_json(self.k(node, "hello.json"))
                hb, _ = self.store.get_json(self.k(node, "heartbeat.json"))
                out.append({"node": node, "record": rec, "hello": hello, "heartbeat": hb})
        return out

    def live(self, n, now=None):
        now = self.clock() if now is None else now
        rec, hb, hello = n["record"] or {}, n["heartbeat"] or {}, n["hello"] or {}
        if rec.get("revoked") or not hello or now > float(rec.get("expiresAt", 0)) + MAX_EXPIRY_S:
            return False
        return now - float(hb.get("t", hello.get("t", 0))) < self.lost_s

    # --- work
    def inbox(self, node):
        return self.store.get_json(self.k(node, "inbox.json"))[0] or {"v": 0, "state": "idle"}

    def assign(self, node, assignment):
        cur = self.inbox(node)
        if cur.get("state") == "revoked":
            return False
        doc = {"v": int(cur.get("v", 0)) + 1, "state": "work", "assignment": assignment, "t": self.clock()}
        rec = self.record(node) or {}
        if float(rec.get("expiresAt", 0)) - self.clock() < 2 * 86400 and not rec.get("revoked"):
            doc["renew"] = self._urls(node, MAX_EXPIRY_S)          # keep a joined node's URLs alive
            self.update_record(node, expiresAt=self.clock() + MAX_EXPIRY_S)
        self.store.put_json(self.k(node, "inbox.json"), doc)
        return True

    def clear(self, node):
        cur = self.inbox(node)
        if cur.get("state") == "revoked":
            return
        self.store.put_json(self.k(node, "inbox.json"), {"v": int(cur.get("v", 0)) + 1, "state": "idle",
                                                       "t": self.clock()})


class MemberNodes(Adapter):
    """The broker's view of member nodes: one worker per live, idle node, with that node's own capabilities."""
    name = "member_node"
    push = False
    trusted = False

    def __init__(self, pid, cfg, members, clock=None):
        super().__init__(pid, cfg, clock or members.clock)
        self.members = members
        self._nodes = []

    def refresh(self):
        self._nodes = self.members.nodes()

    def available(self):
        self.refresh()
        n = sum(1 for x in self._nodes if self.members.live(x))
        return (n > 0), f"{n} live member node(s)"

    def concurrency(self):
        return sum(1 for x in self._nodes if self.members.live(x))

    def node_profile(self, n):
        hello = n["hello"] or {}
        caps, lim = hello.get("caps") or {}, hello.get("limits") or {}
        hb = n["heartbeat"] or {}
        spf = dict(self.cfg.get("spf") or {})
        if not caps.get("gpu"):
            spf = {"preview": 12.0, "final": 400.0} | (hello.get("spf") or {})
        qualities = lim.get("qualities") or ["preview", "final"]
        return {"id": f"{self.pid}:{n['node']}", "node": n["node"], "provider": self.pid,
                "gpu": bool(caps.get("gpu")), "ramGb": float(caps.get("ramGb") or 4), "spf": spf,
                "buildS": float(self.cfg.get("build_s", 15)), "coldStartS": float(self.cfg.get("cold_start_s", 10)),
                "maxRuntimeS": float(min(self.cfg.get("max_runtime_s", 7200),
                                         3600 * max(0.05, float(lim.get("maxHours") or 1e9)
                                                    - float(hb.get("hoursUsed") or 0)))),
                "qualities": qualities, "trusted": False, "paused": bool(hb.get("paused"))}

    def workers(self):
        out = []
        busy = {h.get("node") for h in self.running.values()}
        for n in self._nodes:
            if not self.members.live(n) or n["node"] in busy:
                continue
            p = self.node_profile(n)
            hb = n["heartbeat"] or {}
            if p["paused"] or hb.get("state") in ("busy", "rendering", "limit"):
                continue
            out.append(p)
        return out

    def slots(self):
        return len(self.workers())

    def start(self, task):
        node = task["worker"]["node"]
        ok = self.members.assign(node, {"attempt": task["attempt"], "chunk": task["chunk"],
                                        "manifestUrl": task["manifestUrl"]})
        if not ok:
            from .adapters.base import ProviderError
            raise ProviderError(f"node {node} is revoked")
        h = {"attempt": task["attempt"], "node": node, "t0": self.clock(), "provider": self.pid}
        self.running[task["attempt"]] = h
        return h

    def poll(self, handle):
        node = handle["node"]
        rec = self.members.record(node) or {}
        if rec.get("revoked"):
            return {"state": "lost", "error": "node revoked"}
        hb = self.members.store.get_json(self.members.k(node, "heartbeat.json"))[0] or {}
        if self.clock() - float(hb.get("t", handle["t0"])) > self.members.lost_s:
            return {"state": "lost", "error": "node heartbeat lost"}
        if hb.get("attempt") == handle["attempt"] and hb.get("state") in ("failed", "refused"):
            return {"state": "failed", "error": hb.get("error")}
        if hb.get("lastAttempt") == handle["attempt"] and hb.get("state") == "idle":
            return {"state": "exited", "usage": {"h": float(hb.get("lastHours") or 0)}}
        return {"state": "running"}

    def finish(self, handle):
        self.running.pop(handle["attempt"], None)
        self.members.clear(handle["node"])

    def cancel(self, handle):
        self.finish(handle)

    def usage_estimate(self, est_s):
        return {"h": est_s / 3600.0}


def dumps(o):
    return json.dumps(o, indent=1, default=str)
