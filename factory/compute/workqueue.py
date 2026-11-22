"""
workqueue.py - a work-stealing frame queue shared by every provider, on atomic object-store leases.

Atoms: the frames of a run are cut into small ATOMS (contiguous frames of ONE shot, never across a cut). A worker
claims a run of consecutive atoms of the same shot sized to ITSELF (a 15-minute Lambda takes a few frames, a GPU
pod or a member's workstation takes many), so the same queue serves tiny serverless tasks and big pods.

Keys (under <prefix>, every write that decides ownership is conditional):
  atoms.json                         the atom list (written once, put_if_absent)
  policy.json                        quality/deadline policy (cpu_final: never | deadline | always, deadline_t)
  leases/<atom>/<gen:04d>.json       lease generation `gen` of an atom. Claim = put_if_absent of the NEXT
                                     generation, allowed when the atom has no lease or the latest one is expired
                                     or released -> two workers can never both own generation g.
                                     heartbeat/release = put_if_match on the holder's own lease (ETag).
  spec/<atom>/<gen:04d>.json         ONE speculative copy per lease generation (straggler re-execution)
  done/<atom>.json                   first completion wins (put_if_absent); later results are duplicates
  failed/<atom>/<n>.json             failure log (an atom failing max_failures times is parked)

Worker capability matching: an atom of quality `final` goes to a CPU worker only when policy.cpu_final is
"always", or "deadline" and the worker's estimated finish is before policy.deadline_t; `min_ram_gb` per atom.

Speculation: when nothing is claimable, a free worker may take a copy of the leased atom whose expected finish
(lease t0 + holder's estimate) is furthest away, if this worker would finish it at least `spec_gain` x sooner.
Whichever finishes first writes done/; the other result is discarded (counted as duplicate).
"""
import json
import time

from .store import MemoryStore


class Lease:
    def __init__(self, atom, gen, worker, etag, key, spec=False, record=None):
        self.atom, self.gen, self.worker, self.etag, self.key, self.spec = atom, gen, worker, etag, key, spec
        self.record = record or {}

    def to_dict(self):
        return {"atom": self.atom, "gen": self.gen, "worker": self.worker, "key": self.key, "spec": self.spec}


def make_atoms(jobs, atom_frames):
    """Jobs (cloud/farm/jobs.split_episode, one shot each) -> atoms of <= atom_frames frames."""
    atoms = []
    for j in jobs:
        a, b = int(j["frameStart"]), int(j["frameEnd"])
        f = a
        while f <= b:
            e = min(b, f + atom_frames - 1)
            atoms.append({"id": f"{j['shot']}-f{f:05d}-{e:05d}", "shot": j["shot"], "frameStart": f, "frameEnd": e,
                          "frames": e - f + 1, "quality": j["quality"], "engine": j.get("engine", "CYCLES"),
                          "res": j.get("res"), "samples": j.get("samples"),
                          "spfRef": float(j.get("estSecondsPerFrame") or 0), "minRamGb": j.get("minRamGb", 0)})
            f = e + 1
    return atoms


class WorkQueue:
    def __init__(self, store=None, prefix="", clock=time.time, lease_s=900.0, spec_gain=1.5, max_failures=3):
        self.store = store or MemoryStore()
        self.prefix = prefix.rstrip("/") + "/" if prefix else ""
        self.clock = clock
        self.lease_s, self.spec_gain, self.max_failures = lease_s, spec_gain, max_failures
        self._atoms = None
        self.stats = {"claims": 0, "lostRaces": 0, "steals": 0, "speculative": 0, "duplicates": 0}

    # --- keys
    def k(self, rel):
        return self.prefix + rel

    # --- setup
    def init(self, atoms, policy=None):
        created = self.store.put_json_if_absent(self.k("atoms.json"), {"atoms": atoms, "createdAt": self.clock()})
        self.store.put_json(self.k("policy.json"), policy or {"cpu_final": "deadline", "deadline_t": None})
        self._atoms = None
        return created

    def atoms(self):
        if self._atoms is None:
            doc, _ = self.store.get_json(self.k("atoms.json"))
            self._atoms = (doc or {}).get("atoms", [])
        return self._atoms

    def policy(self):
        doc, _ = self.store.get_json(self.k("policy.json"))
        return doc or {"cpu_final": "deadline", "deadline_t": None}

    def set_policy(self, **kw):
        p = {**self.policy(), **kw}
        self.store.put_json(self.k("policy.json"), p)
        return p

    # --- state snapshot (one listing per prefix)
    def snapshot(self):
        done = {k.rsplit("/", 1)[1][:-5] for k in self.store.list(self.k("done/"))}
        leases = {}
        for k in self.store.list(self.k("leases/")):
            atom, gen = k[len(self.k("leases/")):].rsplit("/", 1)
            leases.setdefault(atom, []).append(int(gen[:-5]))
        specs = {}
        for k in self.store.list(self.k("spec/")):
            atom, gen = k[len(self.k("spec/")):].rsplit("/", 1)
            specs.setdefault(atom, set()).add(int(gen[:-5]))
        fails = {}
        for k in self.store.list(self.k("failed/")):
            atom = k[len(self.k("failed/")):].rsplit("/", 1)[0]
            fails[atom] = fails.get(atom, 0) + 1
        return done, leases, specs, fails

    def lease_record(self, atom, gen):
        return self.store.get_json(self.k(f"leases/{atom}/{gen:04d}.json"))

    def _live(self, rec, now):
        return rec and not rec.get("released") and float(rec.get("expires", 0)) > now

    # --- matching
    def eligible(self, atom, worker, now, policy=None):
        policy = policy or self.policy()
        if float(worker.get("ramGb", 1e9)) < float(atom.get("minRamGb") or 0):
            return False
        if atom["quality"] == "final" and not worker.get("gpu"):
            mode = policy.get("cpu_final", "deadline")
            if mode == "never":
                return False
            if mode == "deadline":
                dl = policy.get("deadline_t")
                if dl is None or now + self.est(worker, [atom]) > float(dl):
                    return False
        if worker.get("qualities") and atom["quality"] not in worker["qualities"]:
            return False
        return True

    @staticmethod
    def est(worker, atoms):
        """Seconds for `worker` to render `atoms` (one chunk): cold start + scene build per shot + frames x spf."""
        spf = worker.get("spf") or {}
        frames = sum(a["frames"] for a in atoms)
        q = atoms[0]["quality"] if atoms else "preview"
        per = float(spf.get(q) or worker.get("spfDefault") or 10.0)
        shots = len({a["shot"] for a in atoms})
        return float(worker.get("coldStartS", 0)) + shots * float(worker.get("buildS", 30)) + frames * per

    # --- claim
    def claim(self, worker, max_frames=None, now=None, max_s=None):
        """Claim the next run of consecutive atoms (same shot) this worker can do. -> [Lease] (may be empty).

        `max_frames` / `max_s`: chunk size limits for this worker (frames, estimated seconds)."""
        now = self.clock() if now is None else now
        policy = self.policy()
        done, leases, _, fails = self.snapshot()
        got = []
        for atom in self.atoms():
            aid = atom["id"]
            if aid in done or fails.get(aid, 0) >= self.max_failures:
                if got:
                    break
                continue
            if got and (atom["shot"] != got[-1].record["shot"] or atom["frameStart"] != got[-1].record["frameEnd"] + 1):
                break
            if not self.eligible(atom, worker, now, policy):
                if got:
                    break
                continue
            cand = [a.record for a in got] + [atom]
            if got and max_frames and sum(a["frames"] for a in cand) > max_frames:
                break
            if got and max_s and self.est(worker, cand) > max_s:
                break
            gens = sorted(leases.get(aid, []))
            gen = 0
            if gens:
                rec, _ = self.lease_record(aid, gens[-1])
                if self._live(rec, now):
                    if got:
                        break
                    continue
                gen = gens[-1] + 1
            lease = self._take(atom, gen, worker, now, est=self.est(worker, cand))
            if lease is None:
                self.stats["lostRaces"] += 1
                if got:
                    break
                continue
            if gen > 0:
                self.stats["steals"] += 1
            got.append(lease)
        self.stats["claims"] += len(got)
        return got

    def _take(self, atom, gen, worker, now, est, spec=False):
        rel = f"{'spec' if spec else 'leases'}/{atom['id']}/{gen:04d}.json"
        rec = {"atom": atom["id"], "gen": gen, "worker": worker["id"], "provider": worker.get("provider"),
               "t0": now, "beat": now, "expires": now + float(worker.get("leaseS") or self.lease_s),
               "estS": round(est, 1), "spec": spec}
        if not self.store.put_json_if_absent(self.k(rel), rec):
            return None
        _, etag = self.store.get(self.k(rel))
        return Lease(atom["id"], gen, worker["id"], etag, rel, spec, record={**atom, **rec, "id": atom["id"]})

    # --- speculation (tail-latency killer)
    def speculate(self, worker, now=None, max_frames=None, max_s=None):
        now = self.clock() if now is None else now
        done, leases, specs, _ = self.snapshot()
        policy = self.policy()
        best = None
        for atom in self.atoms():
            aid = atom["id"]
            if aid in done or aid not in leases:
                continue
            gen = max(leases[aid])
            if gen in specs.get(aid, set()):
                continue
            rec, _ = self.lease_record(aid, gen)
            if not self._live(rec, now) or rec.get("worker") == worker["id"]:
                continue
            if not self.eligible(atom, worker, now, policy):
                continue
            if (max_frames and atom["frames"] > max_frames) or (max_s and self.est(worker, [atom]) > max_s):
                continue
            elapsed, est_s = now - float(rec["t0"]), float(rec.get("estS") or 0)
            # on schedule: what the estimate says is left; overdue (a straggler): assume it needs as long again
            remaining = est_s - elapsed if elapsed <= est_s else elapsed
            mine = self.est(worker, [atom])
            if remaining > self.spec_gain * mine and (best is None or remaining > best[0]):
                best = (remaining, atom, gen)
        if not best:
            return []
        _, atom, gen = best
        lease = self._take(atom, gen, worker, now, self.est(worker, [atom]), spec=True)
        if lease:
            self.stats["speculative"] += 1
            return [lease]
        return []

    def next_chunk(self, worker, max_frames=None, max_s=None, now=None, speculate=True):
        got = self.claim(worker, max_frames=max_frames, now=now, max_s=max_s)
        if not got and speculate:
            got = self.speculate(worker, now=now, max_s=max_s)   # an atom is indivisible: only the time cap applies
        return got

    # --- holder operations
    def heartbeat(self, lease, now=None, extend_s=None):
        now = self.clock() if now is None else now
        rec, etag = self.store.get_json(self.k(lease.key))
        if not rec or rec.get("worker") != lease.worker or rec.get("released"):
            return False
        rec["beat"] = now
        rec["expires"] = now + float(extend_s or self.lease_s)
        ok = self.store.put_json_if_match(self.k(lease.key), rec, etag)
        if ok:
            _, lease.etag = self.store.get(self.k(lease.key))
        return ok

    def release(self, lease, reason="released", failed=True, now=None):
        """Give an atom back (worker failed / was revoked). Failures are counted toward max_failures."""
        now = self.clock() if now is None else now
        rec, etag = self.store.get_json(self.k(lease.key))
        if rec and not rec.get("released"):
            rec.update(released=True, releasedAt=now, reason=reason)
            self.store.put_json_if_match(self.k(lease.key), rec, etag)
        if failed and not lease.spec:
            n = len(self.store.list(self.k(f"failed/{lease.atom}/")))
            self.store.put_json_if_absent(self.k(f"failed/{lease.atom}/{n:03d}.json"),
                                          {"t": now, "worker": lease.worker, "reason": reason, "gen": lease.gen})

    def complete(self, lease, result, now=None):
        """-> True if this result is THE result for the atom (first writer wins), False if a duplicate."""
        now = self.clock() if now is None else now
        doc = {"atom": lease.atom, "gen": lease.gen, "worker": lease.worker, "spec": lease.spec, "t": now,
               **(result or {})}
        won = self.store.put_json_if_absent(self.k(f"done/{lease.atom}.json"), doc)
        if not won:
            self.stats["duplicates"] += 1
        rec, etag = self.store.get_json(self.k(lease.key))
        if rec and not rec.get("released"):
            rec.update(released=True, releasedAt=now, reason="done" if won else "duplicate")
            self.store.put_json_if_match(self.k(lease.key), rec, etag)
        return won

    def reopen(self, atom_id, reason):
        """Un-complete an atom (e.g. an untrusted node's result failed verification): it becomes claimable."""
        doc, _ = self.store.get_json(self.k(f"done/{atom_id}.json"))
        self.store.delete(self.k(f"done/{atom_id}.json"))
        n = len(self.store.list(self.k(f"reopened/{atom_id}/")))
        self.store.put_json(self.k(f"reopened/{atom_id}/{n:03d}.json"), {"t": self.clock(), "reason": reason,
                                                                         "was": doc})
        # expire every live lease generation so the next claim takes a fresh one
        for k in self.store.list(self.k(f"leases/{atom_id}/")):
            rec, etag = self.store.get_json(k)
            if rec and not rec.get("released"):
                rec.update(released=True, reason="reopened")
                self.store.put_json_if_match(k, rec, etag)

    def result(self, atom_id):
        return self.store.get_json(self.k(f"done/{atom_id}.json"))[0]

    # --- progress
    def progress(self, now=None):
        now = self.clock() if now is None else now
        done, leases, specs, fails = self.snapshot()
        atoms = self.atoms()
        frames = sum(a["frames"] for a in atoms)
        fdone = sum(a["frames"] for a in atoms if a["id"] in done)
        leased = 0
        for a in atoms:
            if a["id"] in done or a["id"] not in leases:
                continue
            rec, _ = self.lease_record(a["id"], max(leases[a["id"]]))
            if self._live(rec, now):
                leased += a["frames"]
        parked = [a["id"] for a in atoms if a["id"] not in done and fails.get(a["id"], 0) >= self.max_failures]
        dups = 0
        for a in atoms:
            if a["id"] in done:
                gens = leases.get(a["id"], [])
                dups += sum(1 for _ in specs.get(a["id"], ())) + max(0, len(gens) - 1)
        return {"atoms": len(atoms), "atomsDone": sum(1 for a in atoms if a["id"] in done), "frames": frames,
                "framesDone": fdone, "framesLeased": leased, "framesQueued": frames - fdone - leased,
                "parked": parked, "complete": fdone == frames,
                # from the store, so they are right whichever process (or tick) made the claims:
                "leaseGenerations": sum(len(g) for g in leases.values()),
                "steals": sum(max(0, len(g) - 1) for g in leases.values()),
                "speculative": sum(len(x) for x in specs.values()), "failures": sum(fails.values()),
                "extraAttempts": dups}

    def remaining_atoms(self):
        done, _, _, fails = self.snapshot()
        return [a for a in self.atoms() if a["id"] not in done and fails.get(a["id"], 0) < self.max_failures]


def dumps(obj):
    return json.dumps(obj, indent=1, default=str)
