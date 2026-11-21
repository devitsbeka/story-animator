"""LLM clients. AnthropicClient calls the Messages API with structured outputs (output_config.format json_schema),
streaming, adaptive thinking (the model default) and prompt caching on the system block. FixtureClient replays
recorded responses (<fixtures>/<stage>.<attempt>.json) so the whole chain runs offline in tests."""
import json
import os

DEFAULT_MODEL = "claude-opus-5-5"


class LLMError(RuntimeError):
    pass


class AnthropicClient:
    def __init__(self, model=DEFAULT_MODEL, effort="high", max_tokens=64000, fallbacks=True, client=None):
        if client is None:
            try:
                import anthropic
            except ImportError as e:  # pragma: no cover - depends on the environment
                raise LLMError("the 'anthropic' package is not installed (pip install anthropic) - or run with --offline") from e
            client = anthropic.Anthropic()   # credentials: ANTHROPIC_API_KEY or an `ant auth login` profile
        self.client = client
        self.model, self.effort, self.max_tokens, self.fallbacks = model, effort, max_tokens, fallbacks
        self.calls = []

    def complete(self, stage, system, messages, schema):
        kw = dict(model=self.model, max_tokens=self.max_tokens, system=system, messages=messages,
                  output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}})
        if self.fallbacks:
            # server-side refusal fallback (routes by refusal category; no model list to maintain)
            stream = self.client.beta.messages.stream(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw)
        else:
            stream = self.client.messages.stream(**kw)
        with stream as s:
            msg = s.get_final_message()
        meta = {"model": getattr(msg, "model", self.model), "stop_reason": msg.stop_reason,
                "usage": msg.usage.model_dump() if hasattr(msg.usage, "model_dump") else str(msg.usage)}
        self.calls.append({"stage": stage, **meta})
        if msg.stop_reason == "refusal":
            raise LLMError(f"{stage}: the model declined ({getattr(msg, 'stop_details', None)})")
        if msg.stop_reason == "max_tokens":
            raise LLMError(f"{stage}: output hit max_tokens={self.max_tokens}")
        text = next((b.text for b in msg.content if b.type == "text"), None)
        if text is None:
            raise LLMError(f"{stage}: no text block in the response")
        return text, meta


class FixtureClient:
    """Serves <dir>/<stage>.<n>.json for the n-th call of a stage (n from 1). Records every request so tests can
    assert what the stage sent (system blocks, cache_control, retry feedback)."""

    def __init__(self, fixture_dir):
        self.dir = fixture_dir
        self.n = {}
        self.calls = []

    def complete(self, stage, system, messages, schema):
        n = self.n.get(stage, 0) + 1
        self.n[stage] = n
        path = os.path.join(self.dir, f"{stage}.{n}.json")
        self.calls.append({"stage": stage, "attempt": n, "system": system, "messages": json.loads(json.dumps(messages)),
                           "schema": schema, "fixture": path})
        if not os.path.exists(path):
            raise LLMError(f"offline: no recorded response {path} for {stage} attempt {n}")
        with open(path, encoding="utf-8") as fh:
            return fh.read(), {"model": "fixture", "fixture": path, "stop_reason": "end_turn"}
