"""AnthropicClient against the real SDK with a mocked HTTP transport (no network, no key): checks the request we
send (model, structured output schema, effort, cached system block, server-side fallback beta) and that the
streamed answer is parsed. Skipped when the `anthropic` package is not installed."""
import json

import pytest

anthropic = pytest.importorskip("anthropic")
try:                                  # anthropic >= 1.0 ships on httpx2; older releases on httpx
    import httpx2 as httpx
except ImportError:
    httpx = pytest.importorskip("httpx")

from factory.director import prompts, schemas  # noqa: E402
from factory.director.llm import AnthropicClient, LLMError  # noqa: E402


def _sse(text, stop="end_turn"):
    ev = [
        ("message_start", {"type": "message_start", "message": {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
                                                                "content": [], "stop_reason": None, "stop_sequence": None,
                                                                "usage": {"input_tokens": 10, "output_tokens": 1}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None}, "usage": {"output_tokens": 5}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    return "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in ev).encode()


def _client(captured, text='{"ok": true}', stop="end_turn"):
    def handler(req):
        captured.append(req)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=_sse(text, stop))
    return anthropic.Anthropic(api_key="test-key", http_client=httpx.Client(transport=httpx.MockTransport(handler)), max_retries=0)


def test_request_shape_and_parse():
    cap = []
    c = AnthropicClient(client=_client(cap))
    system = prompts.system_blocks("develop")
    text, meta = c.complete("develop", system, [prompts.user_message("develop", "idea", "short", {})], schemas.api_schema("story"))
    assert json.loads(text) == {"ok": True} and meta["stop_reason"] == "end_turn"
    body = json.loads(cap[0].content)
    assert body["model"] == "claude-opus-5-5" and body["stream"] is True
    assert body["output_config"]["effort"] == "high" and body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["format"]["schema"]["required"][0] == "id"
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in cap[0].headers["anthropic-beta"]
    assert "thinking" not in body and "temperature" not in body


def test_no_fallbacks_uses_plain_endpoint():
    cap = []
    AnthropicClient(client=_client(cap), fallbacks=False).complete("develop", [], [{"role": "user", "content": "x"}], {"type": "object"})
    body = json.loads(cap[0].content)
    assert "fallbacks" not in body and "anthropic-beta" not in cap[0].headers


def test_refusal_and_truncation_raise():
    with pytest.raises(LLMError, match="declined"):
        AnthropicClient(client=_client([], stop="refusal")).complete("develop", [], [{"role": "user", "content": "x"}], {"type": "object"})
    with pytest.raises(LLMError, match="max_tokens"):
        AnthropicClient(client=_client([], stop="max_tokens")).complete("develop", [], [{"role": "user", "content": "x"}], {"type": "object"})
