"""Provider adapter contract tests (MOCKED HTTP).

Each adapter is exercised through the official SDK with a mock HTTP transport, checking
the exact request we send and how we parse responses, usage and errors. These verify our
translation layer, not the live provider."""
import json

import anthropic
import httpx2
import openai
import pytest

from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import ProviderError, ToolSpec
from app.providers.openai_provider import OpenAIProvider

TOOLS = [ToolSpec("write_artifact", "Save", {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]})]
CONV = [
    {"role": "user", "content": [{"type": "text", "text": "Do the task"}]},
    {"role": "assistant", "content": [{"type": "text", "text": "ok"},
                                      {"type": "tool_call", "id": "call_1", "name": "write_artifact", "input": {"name": "a"}}],
     "raw": {"provider": "openai", "model": "gpt-5"}},
    {"role": "user", "content": [{"type": "tool_result", "tool_call_id": "call_1", "content": "Saved", "is_error": False},
                                 {"type": "text", "text": "continue"}]},
]


def mock(handler):
    return httpx2.MockTransport(handler)


def anthropic_with(handler, **kw):
    return AnthropicProvider("sk-ant-test", http_client=anthropic.DefaultAsyncHttpxClient(transport=mock(handler)), **kw)


def openai_with(handler):
    return OpenAIProvider("sk-test", http_client=openai.DefaultAsyncHttpxClient(transport=mock(handler)))


ANTH_RESP = {
    "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
    "content": [{"type": "thinking", "thinking": "", "signature": "sig"},
                {"type": "text", "text": "Saving"},
                {"type": "tool_use", "id": "toolu_9", "name": "write_artifact", "input": {"name": "b"}}],
    "stop_reason": "tool_use", "stop_sequence": None,
    "usage": {"input_tokens": 120, "output_tokens": 30, "cache_read_input_tokens": 10, "cache_creation_input_tokens": 5},
}


async def test_anthropic_request_and_parse():
    seen = []

    def h(req):
        seen.append((req.url.path, json.loads(req.content), dict(req.headers)))
        return httpx2.Response(200, json=ANTH_RESP)

    p = anthropic_with(h, enable_fallbacks=False)
    r = await p.complete(model="claude-opus-5-5", system="sys", messages=CONV, tools=TOOLS, max_tokens=1000, effort="low")
    path, body, headers = seen[0]
    assert path == "/v1/messages"
    assert headers["x-api-key"] == "sk-ant-test"
    assert body["system"] == "sys" and body["max_tokens"] == 1000
    assert body["output_config"] == {"effort": "low"}
    assert body["tool_choice"] == {"type": "auto"}  # forced tool choice is never sent
    assert "temperature" not in body and "thinking" not in body
    assert body["tools"][0]["name"] == "write_artifact"
    # Cross-provider history: neutral blocks converted, tool_result first in the user turn.
    assert body["messages"][1]["content"][1] == {"type": "tool_use", "id": "call_1", "name": "write_artifact", "input": {"name": "a"}}
    assert body["messages"][2]["content"][0]["type"] == "tool_result"
    assert body["messages"][2]["content"][0]["tool_use_id"] == "call_1"
    assert r.stop_reason == "tool_use" and r.tool_calls[0].input == {"name": "b"}
    assert (r.usage.input_tokens, r.usage.output_tokens, r.usage.cache_read_tokens, r.usage.cache_write_tokens) == (120, 30, 10, 5)
    # Same model continuing: native blocks (incl. thinking) are replayed unchanged.
    conv2 = CONV[:1] + [r.assistant_message, {"role": "user", "content": [
        {"type": "tool_result", "tool_call_id": "toolu_9", "content": "ok"}]}]
    await p.complete(model="claude-opus-5-5", system="sys", messages=conv2, tools=TOOLS, max_tokens=1000)
    replay = seen[1][1]["messages"][1]["content"]
    assert replay[0]["type"] == "thinking" and replay[0]["signature"] == "sig"


async def test_anthropic_fallback_beta_and_graceful_degrade():
    seen = []

    def h(req):
        body = json.loads(req.content)
        seen.append((body, req.headers.get("anthropic-beta")))
        if "fallbacks" in body:
            return httpx2.Response(400, json={"type": "error", "error": {"type": "invalid_request_error",
                                                                        "message": "fallbacks: unknown beta"}})
        return httpx2.Response(200, json=ANTH_RESP)

    p = anthropic_with(h)
    await p.complete(model="claude-opus-5-5", system="s", messages=CONV[:1], tools=[], max_tokens=10)
    assert seen[0][0]["fallbacks"] == "default" and "server-side-fallback" in seen[0][1]
    assert "fallbacks" not in seen[1][0]  # retried without the optional feature
    await p.complete(model="claude-opus-5-5", system="s", messages=CONV[:1], tools=[], max_tokens=10)
    assert "fallbacks" not in seen[2][0]  # remembered


@pytest.mark.parametrize("status,kind,retryable", [(401, "auth", False), (404, "not_found", False),
                                                   (429, "rate_limit", True), (529, "overloaded", True)])
async def test_anthropic_errors(status, kind, retryable):
    p = AnthropicProvider("k", http_client=anthropic.DefaultAsyncHttpxClient(transport=mock(
        lambda req: httpx2.Response(status, json={"type": "error", "error": {"type": "x", "message": "boom"}}))),
        enable_fallbacks=False)
    p.client = p.client.with_options(max_retries=0)
    with pytest.raises(ProviderError) as e:
        await p.complete(model="claude-haiku-4-5", system="s", messages=CONV[:1], tools=[], max_tokens=10)
    assert e.value.kind == kind and e.value.retryable == retryable


async def test_anthropic_refusal():
    resp = {**ANTH_RESP, "content": [], "stop_reason": "refusal",
            "stop_details": {"type": "refusal", "category": "cyber", "explanation": "no"}}
    p = anthropic_with(lambda req: httpx2.Response(200, json=resp), enable_fallbacks=False)
    with pytest.raises(ProviderError) as e:
        await p.complete(model="claude-opus-5-5", system="s", messages=CONV[:1], tools=[], max_tokens=10)
    assert e.value.kind == "refusal" and "cyber" in e.value.message


async def test_anthropic_model_discovery():
    def h(req):
        return httpx2.Response(200, json={"data": [{"id": "claude-opus-5-5", "type": "model", "display_name": "Claude Opus 5.5",
                                                    "created_at": "2026-01-01T00:00:00Z", "max_input_tokens": 1000000,
                                                    "max_tokens": 128000}], "has_more": False, "first_id": "a", "last_id": "a"})
    ms = await anthropic_with(h).list_models()
    assert ms[0].model_id == "claude-opus-5-5" and ms[0].context_window == 1000000


OAI_RESP = {
    "id": "c1", "object": "chat.completion", "created": 1, "model": "gpt-5",
    "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
        "role": "assistant", "content": None,
        "tool_calls": [{"id": "call_7", "type": "function", "function": {"name": "write_artifact", "arguments": "{\"name\": \"z\"}"}}]}}],
    "usage": {"prompt_tokens": 200, "completion_tokens": 20, "total_tokens": 220, "prompt_tokens_details": {"cached_tokens": 50}},
}


async def test_openai_request_and_parse():
    seen = []

    def h(req):
        seen.append(json.loads(req.content))
        return httpx2.Response(200, json=OAI_RESP)

    p = openai_with(h)
    r = await p.complete(model="gpt-5", system="sys", messages=CONV, tools=TOOLS, max_tokens=500, effort="medium")
    body = seen[0]
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert body["messages"][2]["tool_calls"][0]["function"]["name"] == "write_artifact"
    assert body["messages"][3] == {"role": "tool", "tool_call_id": "call_1", "content": "Saved"}
    assert body["messages"][4] == {"role": "user", "content": "continue"}
    assert body["max_completion_tokens"] == 500 and body["reasoning_effort"] == "medium"
    assert body["tools"][0]["function"]["parameters"]["required"] == ["name"]
    assert r.tool_calls[0].id == "call_7" and r.tool_calls[0].input == {"name": "z"}
    assert (r.usage.input_tokens, r.usage.cache_read_tokens, r.usage.output_tokens) == (150, 50, 20)


async def test_openai_errors_and_invalid_json():
    p = openai_with(lambda req: httpx2.Response(401, json={"error": {"message": "bad key", "type": "invalid_request_error"}}))
    p.client = p.client.with_options(max_retries=0)
    with pytest.raises(ProviderError) as e:
        await p.complete(model="gpt-5", system="s", messages=CONV[:1], tools=[], max_tokens=10)
    assert e.value.kind == "auth"
    bad = json.loads(json.dumps(OAI_RESP))
    bad["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = "{not json"
    r = await openai_with(lambda req: httpx2.Response(200, json=bad)).complete(
        model="gpt-5", system="s", messages=CONV[:1], tools=TOOLS, max_tokens=10)
    assert "__invalid_json__" in r.tool_calls[0].input


async def test_openai_model_discovery_filters_non_chat():
    def h(req):
        return httpx2.Response(200, json={"object": "list", "data": [
            {"id": "gpt-5", "object": "model", "created": 1, "owned_by": "openai"},
            {"id": "text-embedding-3-small", "object": "model", "created": 1, "owned_by": "openai"}]})
    ms = await openai_with(h).list_models()
    assert [m.model_id for m in ms] == ["gpt-5"]
