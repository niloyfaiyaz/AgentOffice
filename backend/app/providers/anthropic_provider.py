"""Anthropic Messages API adapter (official ``anthropic`` SDK)."""
from __future__ import annotations

import re
from typing import Any, Optional

import anthropic

from .base import CompletionResult, ModelInfo, Provider, ProviderError, ToolCall, ToolSpec, Usage

_ID_SAFE = re.compile(r"[^A-Za-z0-9_\-]")

# Models that accept output_config.effort (Claude 4.6+ generation and Opus 4.5).
_EFFORT_MODELS = re.compile(r"^claude-(opus|sonnet|haiku|fable|mythos)-(5|4-[5-9])")
_NO_EFFORT = {"claude-sonnet-4-5", "claude-haiku-4-5"}
# Models for which server-side refusal fallbacks are available (beta).
_FALLBACK_MODELS = re.compile(r"^claude-(opus-5|fable-5|sonnet-5-5)")
_FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Server web search tool version supporting dynamic filtering on current models.
_WEB_SEARCH_NEW = re.compile(r"^claude-(opus-(5|4-[6-9])|sonnet-(5|4-6)|fable|mythos)")


def _safe_id(tool_id: str) -> str:
    return _ID_SAFE.sub("_", tool_id)[:64] or "call"


def _map_error(e: Exception) -> ProviderError:
    msg = getattr(e, "message", None) or str(e)
    if isinstance(e, anthropic.AuthenticationError):
        return ProviderError("auth", msg, status=401)
    if isinstance(e, anthropic.PermissionDeniedError):
        return ProviderError("permission", msg, status=403)
    if isinstance(e, anthropic.NotFoundError):
        return ProviderError("not_found", msg, status=404)
    if isinstance(e, anthropic.RateLimitError):
        return ProviderError("rate_limit", msg, retryable=True, status=429)
    if isinstance(e, anthropic.BadRequestError):
        low = msg.lower()
        if "credit" in low or "billing" in low or "spend" in low:
            return ProviderError("billing", msg, status=400)
        return ProviderError("invalid_request", msg, status=400)
    if isinstance(e, anthropic.APITimeoutError):
        return ProviderError("timeout", msg, retryable=True)
    if isinstance(e, anthropic.APIConnectionError):
        return ProviderError("connection", msg, retryable=True)
    if isinstance(e, anthropic.APIStatusError):
        status = e.status_code
        if status == 529:
            return ProviderError("overloaded", msg, retryable=True, status=status)
        if status >= 500:
            return ProviderError("server", msg, retryable=True, status=status)
        return ProviderError("invalid_request", msg, status=status)
    return ProviderError("server", msg)


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, api_key: str, *, http_client: Any = None, base_url: Optional[str] = None,
                 enable_fallbacks: bool = True):
        kwargs: dict[str, Any] = {"api_key": api_key, "max_retries": 2, "timeout": 600.0}
        if http_client is not None:
            kwargs["http_client"] = http_client
        # Always talk to the public API unless explicitly overridden; never inherit ambient env.
        kwargs["base_url"] = base_url or "https://api.anthropic.com"
        self.client = anthropic.AsyncAnthropic(**kwargs)
        self.enable_fallbacks = enable_fallbacks
        self._unsupported: set[tuple[str, str]] = set()  # (model, feature) learned from 400s

    # -- conversion -------------------------------------------------------------
    def to_native(self, model: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m["role"] == "assistant":
                raw = m.get("raw") or {}
                if raw.get("provider") == self.name and raw.get("model") == model and raw.get("content"):
                    # Same model continues: replay native blocks (incl. thinking) unchanged.
                    out.append({"role": "assistant", "content": raw["content"]})
                    continue
                blocks: list[dict[str, Any]] = []
                for b in m["content"]:
                    if b["type"] == "text" and b.get("text"):
                        blocks.append({"type": "text", "text": b["text"]})
                    elif b["type"] == "tool_call":
                        blocks.append({"type": "tool_use", "id": _safe_id(b["id"]), "name": b["name"], "input": b["input"]})
                out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": "(no content)"}]})
            else:
                results = [b for b in m["content"] if b["type"] == "tool_result"]
                texts = [b for b in m["content"] if b["type"] == "text"]
                blocks = [
                    {"type": "tool_result", "tool_use_id": _safe_id(b["tool_call_id"]),
                     "content": b.get("content") or "(empty)", "is_error": bool(b.get("is_error"))}
                    for b in results
                ]
                blocks += [{"type": "text", "text": b["text"]} for b in texts if b.get("text")]
                out.append({"role": "user", "content": blocks})
        return out

    def _tools(self, model: str, tools: list[ToolSpec]) -> list[dict[str, Any]]:
        native: list[dict[str, Any]] = []
        for t in tools:
            if t.native is not None:
                if t.native.get("kind") == "web_search":
                    ver = "web_search_20260209" if _WEB_SEARCH_NEW.match(model) else "web_search_20250305"
                    native.append({"type": ver, "name": "web_search", "max_uses": t.native.get("max_uses", 5)})
                continue
            native.append({"name": t.name, "description": t.description, "input_schema": t.input_schema})
        return native

    def supports_native_tool(self, model: str, tool_key: str) -> bool:
        return tool_key == "web_research"

    # -- calls --------------------------------------------------------------------
    async def complete(self, *, model, system, messages, tools, max_tokens, effort=None) -> CompletionResult:
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": self.to_native(model, messages),
        }
        native_tools = self._tools(model, tools)
        if native_tools:
            params["tools"] = native_tools
            params["tool_choice"] = {"type": "auto"}
        use_effort = (
            effort and _EFFORT_MODELS.match(model) and model not in _NO_EFFORT
            and (model, "effort") not in self._unsupported
        )
        if use_effort:
            params["output_config"] = {"effort": effort}
        use_fallback = (
            self.enable_fallbacks and _FALLBACK_MODELS.match(model) and (model, "fallbacks") not in self._unsupported
        )
        try:
            resp = await self._send(params, use_fallback)
        except anthropic.BadRequestError as e:
            # Degrade gracefully if an optional feature is not accepted for this key/model.
            msg = (getattr(e, "message", "") or str(e)).lower()
            retried = False
            if use_fallback and ("fallback" in msg or "beta" in msg):
                self._unsupported.add((model, "fallbacks"))
                use_fallback = False
                retried = True
            if use_effort and ("effort" in msg or "output_config" in msg):
                self._unsupported.add((model, "effort"))
                params.pop("output_config", None)
                retried = True
            if not retried:
                raise _map_error(e) from e
            try:
                resp = await self._send(params, use_fallback)
            except anthropic.AnthropicError as e2:
                raise _map_error(e2) from e2
        except anthropic.AnthropicError as e:
            raise _map_error(e) from e
        return self._parse(model, resp)

    async def _send(self, params: dict[str, Any], use_fallback: bool):
        if use_fallback:
            return await self.client.beta.messages.create(
                **params, betas=[_FALLBACK_BETA], fallbacks="default"
            )
        return await self.client.messages.create(**params)

    def _parse(self, model: str, resp: Any) -> CompletionResult:
        stop = resp.stop_reason
        if stop == "refusal":
            details = getattr(resp, "stop_details", None)
            cat = getattr(details, "category", None) if details else None
            expl = getattr(details, "explanation", None) if details else None
            raise ProviderError("refusal", f"category={cat}; {expl or ''}".strip())
        texts: list[str] = []
        calls: list[ToolCall] = []
        neutral: list[dict[str, Any]] = []
        for b in resp.content:
            if b.type == "text":
                texts.append(b.text)
                neutral.append({"type": "text", "text": b.text})
            elif b.type == "tool_use":
                inp = b.input if isinstance(b.input, dict) else {}
                calls.append(ToolCall(id=b.id, name=b.name, input=inp))
                neutral.append({"type": "tool_call", "id": b.id, "name": b.name, "input": inp})
        raw_blocks = [b.model_dump(mode="json", exclude_none=True) for b in resp.content]
        u = resp.usage
        other: dict[str, Any] = {}
        stu = getattr(u, "server_tool_use", None)
        if stu is not None:
            ws = getattr(stu, "web_search_requests", 0) or 0
            if ws:
                other["web_search_requests"] = ws
        usage = Usage(
            input_tokens=getattr(u, "input_tokens", 0) or 0,
            output_tokens=getattr(u, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            other=other,
        )
        mapped = {"end_turn": "end", "tool_use": "tool_use", "max_tokens": "max_tokens",
                  "pause_turn": "pause", "stop_sequence": "end"}.get(stop or "end_turn", "end")
        return CompletionResult(
            text="\n".join(texts),
            tool_calls=calls,
            stop_reason=mapped,
            usage=usage,
            assistant_message={"role": "assistant", "content": neutral,
                               "raw": {"provider": self.name, "model": model, "content": raw_blocks}},
            served_model=getattr(resp, "model", model) or model,
        )

    async def list_models(self) -> list[ModelInfo]:
        try:
            out: list[ModelInfo] = []
            async for m in self.client.models.list(limit=100):
                caps = getattr(m, "capabilities", None)
                out.append(ModelInfo(
                    model_id=m.id,
                    display_name=getattr(m, "display_name", m.id) or m.id,
                    context_window=getattr(m, "max_input_tokens", None),
                    max_output_tokens=getattr(m, "max_tokens", None),
                    capabilities=caps.model_dump(mode="json") if hasattr(caps, "model_dump") else {},
                ))
            return out
        except anthropic.AnthropicError as e:
            raise _map_error(e) from e
