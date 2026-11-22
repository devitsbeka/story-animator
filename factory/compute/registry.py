"""
registry.py - provider capability model: broker.yaml + the free-compute registry.yaml + measured calibration.

    load(providers=None, allow_care=()) -> {"defaults": {...}, "providers": {id: cfg}, "gated": {id: reason}}

registry.yaml (written by the free-compute hunt) is tolerated in either shape:
    sources: [{id, type, hardware, quota, max_runtime, concurrency, adapter, priority, terms|verdict}, ...]
    {id: {...}, ...}   or   [{id: ...}, ...]
Its fields map onto broker.yaml names (max_runtime -> max_runtime_s, verdict -> terms, ...). Only ids that have
an adapter here (implemented or stub) can be scheduled; the others are listed as `unknown_adapter`.

Terms gate: `terms` USE is schedulable; USE-WITH-CARE only when the id is in allow_care; AVOID never.
"""
import json
import os

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
BROKER_YAML = os.path.join(HERE, "broker.yaml")
REGISTRY_YAML = os.path.join(HERE, "registry.yaml")
FIELD_MAP = {"max_runtime": "max_runtime_s", "verdict": "terms", "terms_verdict": "terms", "cold_start": "cold_start_s"}
KNOWN_ADAPTERS = {"aws_lambda", "local_cpu", "presigned_pod", "member_node", "gcp_cloud_run_jobs",
                  "azure_container_apps", "modal", "kaggle", "oracle_always_free", "hf_spaces"}


def state_dir():
    return os.path.expanduser(os.environ.get("COMPUTE_STATE_DIR", "~/.story-compute"))


def _entries(doc):
    if not doc:
        return []
    if isinstance(doc, dict):
        for k in ("sources", "providers", "registry", "entries"):
            if isinstance(doc.get(k), list):
                return doc[k]
            if isinstance(doc.get(k), dict):
                return [{"id": i, **(v or {})} for i, v in doc[k].items()]
        return [{"id": i, **(v or {})} for i, v in doc.items() if isinstance(v, dict)]
    return [e for e in doc if isinstance(e, dict)]


def _norm_terms(v):
    if isinstance(v, dict):
        v = v.get("verdict") or v.get("terms")
    v = str(v or "").strip().upper().replace("_", "-").replace(" ", "-")
    if v.startswith("USE-WITH"):
        return "USE-WITH-CARE"
    return v or "UNKNOWN"


def merge_registry(providers, reg_entries):
    out = {k: dict(v) for k, v in providers.items()}
    unknown = []
    for e in reg_entries:
        e = {FIELD_MAP.get(k, k): v for k, v in e.items()}
        pid = e.get("id")
        if not pid:
            continue
        cur = out.get(pid, {})
        merged = {**cur}
        for k, v in e.items():
            if k == "id" or v is None:
                continue
            if isinstance(v, dict) and isinstance(cur.get(k), dict):
                merged[k] = {**cur[k], **v}
            else:
                merged[k] = v
        merged["terms"] = _norm_terms(merged.get("terms"))
        merged["fromRegistry"] = True
        if merged.get("adapter") not in KNOWN_ADAPTERS:
            unknown.append(pid)
        out[pid] = merged
    return out, unknown


def load_calibration(path=None):
    path = path or os.path.join(state_dir(), "calibration.json")
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_calibration(cal, path=None):
    path = path or os.path.join(state_dir(), "calibration.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(cal, fh, indent=1, sort_keys=True)


def load(providers=None, allow_care=(), broker_yaml=BROKER_YAML, registry_yaml=REGISTRY_YAML, calibration=None):
    with open(broker_yaml) as fh:
        base = yaml.safe_load(fh) or {}
    provs = base.get("providers", {})
    unknown = []
    if registry_yaml and os.path.isfile(registry_yaml):
        with open(registry_yaml) as fh:
            provs, unknown = merge_registry(provs, _entries(yaml.safe_load(fh)))
    cal = load_calibration() if calibration is None else calibration
    gated = {}
    out = {}
    allow_care = set(allow_care or ())
    for pid, cfg in provs.items():
        cfg = dict(cfg)
        cfg["terms"] = _norm_terms(cfg.get("terms"))
        if pid in cal:
            cfg["spf"] = {**(cfg.get("spf") or {}), **{q: v for q, v in cal[pid].get("spf", {}).items() if v}}
            for k in ("build_s", "cold_start_s"):
                if cal[pid].get(k):
                    cfg[k] = cal[pid][k]
            cfg["calibrated"] = True
        if providers and pid not in providers:
            continue
        if cfg["terms"] == "AVOID":
            gated[pid] = "terms verdict AVOID"
        elif cfg["terms"] == "USE-WITH-CARE" and pid not in allow_care:
            gated[pid] = "terms verdict USE-WITH-CARE (enable explicitly with --allow-care " + pid + ")"
        elif cfg["terms"] not in ("USE", "USE-WITH-CARE"):
            gated[pid] = f"terms verdict {cfg['terms']!r} is not USE"
        elif cfg.get("adapter") not in KNOWN_ADAPTERS:
            gated[pid] = f"no adapter {cfg.get('adapter')!r}"
        else:
            out[pid] = cfg
    if providers:
        for pid in providers:
            if pid not in provs:
                gated[pid] = "unknown provider id"
    return {"defaults": base.get("defaults", {}), "providers": out, "gated": gated, "unknownAdapters": unknown}


def profile(pid, cfg):
    """The capability dict the queue + planner use."""
    hw = cfg.get("hardware") or {}
    return {"provider": pid, "gpu": cfg.get("type") == "gpu", "ramGb": float(hw.get("ram_gb") or 0) or 1e9,
            "spf": dict(cfg.get("spf") or {}), "buildS": float(cfg.get("build_s", 30)),
            "coldStartS": float(cfg.get("cold_start_s", 0)), "maxRuntimeS": float(cfg.get("max_runtime_s", 900)),
            "concurrency": int(cfg.get("concurrency") or 0), "trusted": bool(cfg.get("trusted", True))}
