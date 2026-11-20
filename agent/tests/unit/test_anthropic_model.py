"""The Claude adapter's request and response handling, against a mock transport (no network)."""

import json

import anthropic
import httpx2
import pytest

from agent.app.errors import INTERNAL, MODEL_REFUSED, MODEL_TRUNCATED
from agent.app.llm.anthropic_model import AnthropicReasonModel
from agent.app.llm.base import ModelError, RenderedPrompt
from agent.tests.conftest import make_settings
from agent.tests.scripts import store_a_turns

PROMPT = RenderedPrompt(system="S1 system", case_facts="U1 case", turn_state="U2 turn", control="C control")


def sse(text: str, stop_reason: str = "end_turn", model: str = "claude-opus-5-5") -> bytes:
    events = [
        ("message_start", {"type": "message_start", "message": {
            "id": "msg_1", "type": "message", "role": "assistant", "model": model, "content": [],
            "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 120, "output_tokens": 1, "cache_read_input_tokens": 900,
                      "cache_creation_input_tokens": 0}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "text_delta", "text": text}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                           "usage": {"output_tokens": 345}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events).encode()


def model_with(responses, sent, **settings):
    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        status, body = responses.pop(0)
        headers = {"content-type": "text/event-stream"} if status == 200 else {"content-type": "application/json"}
        return httpx2.Response(status, content=body, headers=headers)

    client = anthropic.AsyncAnthropic(api_key="test-key", max_retries=0,
                                      http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)))
    return AnthropicReasonModel(make_settings(**settings), client=client)


async def test_request_shape_and_parsed_reply():
    sent = []
    model = model_with([(200, sse(json.dumps(store_a_turns()[0])))], sent)
    reply = await model.reason(PROMPT, {})
    body = json.loads(sent[0].content)
    assert body["model"] == "claude-opus-5-5"
    assert body["max_tokens"] == 32000
    assert body["stream"] is True
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in sent[0].headers["anthropic-beta"]
    assert body["output_config"]["effort"] == "medium"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["system"] == [{"type": "text", "text": "S1 system", "cache_control": {"type": "ephemeral"}}]
    user, control = body["messages"]
    assert user["role"] == "user" and user["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in user["content"][1]
    assert control == {"role": "system", "content": "C control"}
    for absent in ("tools", "tool_choice", "temperature", "top_p", "top_k", "thinking", "speed"):
        assert absent not in body
    assert reply.output["next_action"]["type"] == "check"
    assert reply.usage == {"input_tokens": 120, "output_tokens": 345, "cache_read_input_tokens": 900,
                           "cache_creation_input_tokens": 0}


async def test_fast_mode_adds_speed():
    sent = []
    model = model_with([(200, sse("{}"))], sent, agent_speed="fast", agent_effort="low")
    await model.reason(PROMPT, {})
    body = json.loads(sent[0].content)
    assert body["speed"] == "fast" and body["output_config"]["effort"] == "low"


async def test_refusal_is_model_refused():
    model = model_with([(200, sse("", stop_reason="refusal"))], [])
    with pytest.raises(ModelError) as info:
        await model.reason(PROMPT, {})
    assert info.value.code == MODEL_REFUSED


async def test_max_tokens_retries_once_at_64k_then_truncates():
    sent = []
    model = model_with([(200, sse("{", stop_reason="max_tokens")), (200, sse("{", stop_reason="max_tokens"))], sent)
    with pytest.raises(ModelError) as info:
        await model.reason(PROMPT, {})
    assert info.value.code == MODEL_TRUNCATED
    assert [json.loads(r.content)["max_tokens"] for r in sent] == [32000, 64000]


async def test_unparseable_text_returns_no_output_for_the_guard():
    reply = await model_with([(200, sse("not json"))], []).reason(PROMPT, {})
    assert reply.output is None and reply.raw_text == "not json"


async def test_bad_request_is_internal_with_the_api_message():
    error = json.dumps({"type": "error", "error": {"type": "invalid_request_error",
                                                   "message": "Schema is too complex for compilation."}}).encode()
    model = model_with([(400, error)], [])
    with pytest.raises(ModelError) as info:
        await model.reason(PROMPT, {})
    assert info.value.code == INTERNAL and "too complex" in info.value.message
