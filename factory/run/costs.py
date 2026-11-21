"""Cost accounting for one episode run: LLM tokens, voice characters, render GPU hours.

Every number here is an ESTIMATE used for the budget ceiling and the per-stage report; the real bill comes from the
providers. Prices can be overridden with env FACTORY_PRICES_JSON='{"llm": {...}, "voice_usd_per_1k_chars": ...}'.

LLM prices are USD per million tokens (Anthropic first-party list price, Nov 2026). cache_write assumes the 5-minute
cache-write multiplier (1.25 x input).
"""
import glob
import json
import os

LLM_PRICES = {
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_read": 0.20, "cache_write": 5.00},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.10, "cache_write": 2.50},
    "fixture": {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0},
}
VOICE_USD_PER_1K_CHARS = 0.30     # ElevenLabs multilingual TTS, pay-as-you-go tier (estimate)
FARM_USD_PER_GPU_HOUR = 0.60       # same default as cloud/farm/orchestrator.py
LOCAL_USD_PER_CPU_HOUR = 0.0       # local machine: time is reported, money is not

# Up-front estimates used for admission control in batch mode (before anything ran).
EST_LLM_USD = {"short": 1.50, "docuseries": 12.00}       # develop + breakdown + direct, ~2 attempts each
EST_VOICE_CHARS = {"short": 1400, "docuseries": 18000}


def prices():
    p = {"llm": dict(LLM_PRICES), "voice_usd_per_1k_chars": VOICE_USD_PER_1K_CHARS,
         "farm_usd_per_gpu_hour": FARM_USD_PER_GPU_HOUR}
    raw = os.environ.get("FACTORY_PRICES_JSON")
    if raw:
        o = json.loads(raw)
        p["llm"].update(o.get("llm", {}))
        for k in ("voice_usd_per_1k_chars", "farm_usd_per_gpu_hour"):
            if k in o:
                p[k] = float(o[k])
    return p


def llm_usd(model, usage):
    """usage: Anthropic usage dict (input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens)."""
    if not isinstance(usage, dict):
        return 0.0
    table = prices()["llm"]
    pr = table.get(model) or next((v for k, v in table.items() if model and model.startswith(k)), None) \
        or table["claude-opus-5-5"]
    return (usage.get("input_tokens", 0) * pr["input"] + usage.get("output_tokens", 0) * pr["output"]
            + (usage.get("cache_read_input_tokens") or 0) * pr["cache_read"]
            + (usage.get("cache_creation_input_tokens") or 0) * pr["cache_write"]) / 1e6


def llm_stage_cost(ep_dir, stage, since=0.0):
    """Sum the cost of every director attempt report reports/<stage>.<n>.json written at or after `since`."""
    usd, tokens, attempts = 0.0, {"input": 0, "output": 0}, 0
    for p in glob.glob(os.path.join(ep_dir, "reports", f"{stage}.*.json")):
        if os.path.getmtime(p) + 1e-3 < since:
            continue
        try:
            meta = (json.load(open(p)) or {}).get("meta") or {}
        except (OSError, ValueError):
            continue
        if not meta:
            continue
        attempts += 1
        u = meta.get("usage") if isinstance(meta.get("usage"), dict) else {}
        usd += llm_usd(meta.get("model"), u)
        tokens["input"] += int(u.get("input_tokens", 0) or 0)
        tokens["output"] += int(u.get("output_tokens", 0) or 0)
    return {"usd": round(usd, 4), "tokens": tokens, "attempts": attempts}


def voice_usd(chars):
    return round(chars / 1000.0 * prices()["voice_usd_per_1k_chars"], 4)


def estimate_episode(fmt, render="local", quality="preview", spec=None, offline=False):
    """Admission estimate for one idea (USD). With a spec (episode.json) the farm render cost is computed from it."""
    llm = 0.0 if offline else EST_LLM_USD.get(fmt, EST_LLM_USD["short"])
    voice = 0.0 if offline else voice_usd(EST_VOICE_CHARS.get(fmt, EST_VOICE_CHARS["short"]))
    rend = 0.0
    if render == "farm":
        if spec is not None:
            from . import render as render_mod
            rend = render_mod.farm_estimate(spec, quality)["usd"]
        else:
            # Sentinel-sized short: ~33 shots x ~75 frames; docuseries ~12x that
            frames = 2416 if fmt == "short" else 30000
            spf = 3.0 if quality == "preview" else 40.0
            rend = round((frames * spf * 1.3) / 3600 * prices()["farm_usd_per_gpu_hour"], 2)
    return {"llm": round(llm, 2), "voice": round(voice, 2), "render": round(rend, 2), "usd": round(llm + voice + rend, 2)}
