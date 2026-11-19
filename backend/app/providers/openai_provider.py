"""OpenAI Chat Completions adapter (official ``openai`` SDK)."""
from __future__ import annotations

import json
import re
from typing import Any, Optional

import openai

from .base import CompletionResult, ModelInfo, Provider, ProviderError, ToolCall, ToolSpec, Usage

# Reasoning-capable families accept ``reasoning_effort``.
_REASONING = re.compile(r"^(o\d|gpt-5)")
# Model ids from /v1/models that are not chat models.
_NON_CHAT = re.compile(r"(embedding|whisper|tts|dall-e|davinci|babbage|moderation|image|audio|realtime|transcribe|search)")


def _map_error(e: Exception) -> ProviderError:
    msg = getattr(e, "message", None) or str(e)
    if isinstance(e, openai.AuthenticationError):
        return ProviderError("auth", msg, status=401)
    if isinstance(e, openai.PermissionDeniedError):
        return ProviderError("permission", msg, status=403)
    if isinstance(e, openai.NotFoundError):
        return ProviderError("not_found", msg, status=404)
    if isinstance(e, openai.RateLimitError):
        low = msg.lower()
        if "quota" in low or "billing" in low:
            return ProviderError("billing", msg, status=429)
        return ProviderError("rate_limit", msg, retryable=True, status=429)
    if isinstance(e, openai.BadRequestError):
        return ProviderError("invalid_request", msg, status=400)
    if isinstance(e, openai.APITimeoutError):
        return ProviderError("timeout", msg, retryable=True)
    if isinstance(e, openai.APIConnectionError):
        return ProviderError("connection", msg, retryable=True)
    if isinstance(e, openai.APIStatusError):
        if e.status_code >= 500:
            return ProviderError("server", msg, retryable=True, status=e.status_code)
        return ProviderError("invalid_request", msg, status=e.status_code)
    return ProviderError("server", msg)


class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self, api_key: str, *, http_client: Any = None, base_url: Optional[str] = None):
        kwargs: dict[str, Any] = {"api_key": api_key, "max_retries": 2, "timeout": 600.0,
                                  "base_url": base_url or "https://api.openai.com/v1"}
        if http_client is not None:
            kwargs["http_client"] = http_client
        self.client = openai.AsyncOpenAI(**kwargs)
        self._no_effort: set[str] = set()

    def to_native(self, system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "assistant":
                text = "\n".join(b["text"] for b in m["content"] if b["type"] == "text" and b.get("text"))
                calls = [
                    {"id": b["id"], "type": "function",
                     "function": {"name": b["name"], "arguments": json.dumps(b["input"])}}
                    for b in m["content"] if b["type"] == "tool_call"
                ]
                msg: dict[str, Any] = {"role": "assistant", "content": text or None}
                if calls:
                    msg["tool_calls"] = calls
                out.append(msg)
            else:
                for b in m["content"]:
                    if b["type"] == "tool_result":
                        content = b.get("content") or "(empty)"
                        if b.get("is_error"):
                            content = f"ERROR: {content}"
                        out.append({"role": "tool", "tool_call_id": b["tool_call_id"], "content": content})
                texts = [b["text"] for b in m["content"] if b["type"] == "text" and b.get("text")]
                if texts:
                    out.append({"role": "user", "content": "\n\n".join(texts)})
        return out

    async def complete(self, *, model, system, messages, tools, max_tokens, effort=None) -> CompletionResult:
        params: dict[str, Any] = {
            "model": model,
            "messages": self.to_native(system, messages),
            "max_completion_tokens": max_tokens,
        }
        fn_tools = [
            {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}}
            for t in tools if t.native is None
        ]
        if fn_tools:
            params["tools"] = fn_tools
            params["tool_choice"] = "auto"
        use_effort = effort and _REASONING.match(model) and model not in self._no_effort
        if use_effort:
            params["reasoning_effort"] = {"max": "high", "xhigh": "high"}.get(effort, effort)
        try:
            resp = await self.client.chat.completions.create(**params)
        except openai.BadRequestError as e:
            if use_effort and "reasoning_effort" in (getattr(e, "message", "") or str(e)):
                self._no_effort.add(model)
                params.pop("reasoning_effort", None)
                try:
                    resp = await self.client.chat.completions.create(**params)
                except openai.OpenAIError as e2:
                    raise _map_error(e2) from e2
            else:
                raise _map_error(e) from e
        except openai.OpenAIError as e:
            raise _map_error(e) from e
        return self._parse(model, resp)

    def _parse(self, model: str, resp: Any) -> CompletionResult:
        if not resp.choices:
            raise ProviderError("server", "Provider returned no choices")
        choice = resp.choices[0]
        msg = choice.message
        refusal = getattr(msg, "refusal", None)
        if refusal:
            raise ProviderError("refusal", refusal)
        text = msg.content or ""
        calls: list[ToolCall] = []
        neutral: list[dict[str, Any]] = []
        if text:
            neutral.append({"type": "text", "text": text})
        for tc in msg.tool_calls or []:
            fn = getattr(tc, "function", None)
            if fn is None:
                continue
            try:
                args = json.loads(fn.arguments or "{}")
                if not isinstance(args, dict):
                    args = {"value": args}
            except json.JSONDecodeError:
                args = {"__invalid_json__": fn.arguments}
            calls.append(ToolCall(id=tc.id, name=fn.name, input=args))
            neutral.append({"type": "tool_call", "id": tc.id, "name": fn.name, "input": args})
        u = resp.usage
        cached = 0
        details = getattr(u, "prompt_tokens_details", None) if u else None
        if details is not None:
            cached = getattr(details, "cached_tokens", 0) or 0
        other: dict[str, Any] = {}
        cdetails = getattr(u, "completion_tokens_details", None) if u else None
        if cdetails is not None and getattr(cdetails, "reasoning_tokens", None):
            other["reasoning_tokens"] = cdetails.reasoning_tokens
        prompt = (getattr(u, "prompt_tokens", 0) or 0) if u else 0
        usage = Usage(
            # Normalize: input_tokens excludes cached tokens, which are billed separately.
            input_tokens=max(prompt - cached, 0),
            output_tokens=(getattr(u, "completion_tokens", 0) or 0) if u else 0,
            cache_read_tokens=cached,
            other=other,
        )
        finish = choice.finish_reason
        stop = "tool_use" if calls else {"length": "max_tokens", "content_filter": "refusal"}.get(finish or "", "end")
        if stop == "refusal":
            raise ProviderError("refusal", "content_filter")
        return CompletionResult(
            text=text, tool_calls=calls, stop_reason=stop, usage=usage,
            assistant_message={"role": "assistant", "content": neutral,
                               "raw": {"provider": self.name, "model": model}},
            served_model=getattr(resp, "model", model) or model,
        )

    async def list_models(self) -> list[ModelInfo]:
        try:
            page = await self.client.models.list()
            out = []
            async for m in page:
                if _NON_CHAT.search(m.id):
                    continue
                out.append(ModelInfo(model_id=m.id, display_name=m.id))
            return out
        except openai.OpenAIError as e:
            raise _map_error(e) from e
