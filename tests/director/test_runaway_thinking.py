from factory.director.llm import LLMError
from factory.director.runner import runaway_thinking


def _err(out, think, stop="max_tokens"):
    return LLMError("x", {"stop_reason": stop, "usage": {"output_tokens": out, "output_tokens_details": {"thinking_tokens": think}}})


def test_runaway_thinking_lowers_effort():
    assert runaway_thinking(_err(64000, 60324), "high") == "medium"
    assert runaway_thinking(_err(64000, 10000), "high") is None      # the answer itself was long: not this lesson
    assert runaway_thinking(_err(64000, 60000, "end_turn"), "high") is None
    assert runaway_thinking(_err(64000, 60000), "low") is None
