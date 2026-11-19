"""Provider-neutral model interface.

Conversation format (persisted in ``TaskExecution.conversation``)::

    {"role": "user", "content": [
        {"type": "text", "text": "..."},
        {"type": "tool_result", "tool_call_id": "...", "content": "...", "is_error": false},
    ]}
    {"role": "assistant", "content": [
        {"type": "text", "text": "..."},
        {"type": "tool_call", "id": "...", "name": "...", "input": {...}},
    ], "raw": {"provider": "anthropic", "model": "...", "content": [...native blocks...]}}

``raw`` lets an adapter replay its own native blocks (e.g. thinking blocks) unchanged when
the same model continues a conversation. When the model or provider changes at a safe
checkpoint the neutral blocks are used instead, so tool calls stay paired with results.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    # Provider-hosted tools (e.g. Anthropic web search) are passed through natively.
    native: Optional[dict[str, Any]] = None


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    other: dict[str, Any] = field(default_factory=dict)


@dataclass
class CompletionResult:
    text: str
    tool_calls: list[ToolCall]
    stop_reason: str  # end | tool_use | max_tokens | refusal | pause
    usage: Usage
    assistant_message: dict[str, Any]
    served_model: str


@dataclass
class ModelInfo:
    model_id: str
    display_name: str
    context_window: Optional[int] = None
    max_output_tokens: Optional[int] = None
    capabilities: dict[str, Any] = field(default_factory=dict)


class ProviderError(Exception):
    """Normalized provider failure.

    kind: auth | permission | rate_limit | overloaded | invalid_request | not_found | timeout |
          connection | server | refusal | not_configured | billing
    """

    def __init__(self, kind: str, message: str, *, retryable: bool = False, status: Optional[int] = None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.retryable = retryable
        self.status = status

    def user_message(self) -> str:
        labels = {
            "auth": "The provider rejected the API key.",
            "permission": "The API key is not permitted to use this model or feature.",
            "rate_limit": "The provider rate-limited the request.",
            "overloaded": "The provider is temporarily overloaded.",
            "invalid_request": "The provider rejected the request.",
            "not_found": "The model was not found for this API key.",
            "timeout": "The request to the provider timed out.",
            "connection": "Could not reach the provider.",
            "server": "The provider returned a server error.",
            "refusal": "The model declined this request.",
            "not_configured": "The provider is not configured.",
            "billing": "The provider reported a billing or spend-limit problem.",
        }
        return f"{labels.get(self.kind, 'Provider error.')} {self.message}".strip()


class Provider(abc.ABC):
    name: str = ""
    is_test_provider: bool = False

    @abc.abstractmethod
    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
        max_tokens: int,
        effort: Optional[str] = None,
    ) -> CompletionResult: ...

    @abc.abstractmethod
    async def list_models(self) -> list[ModelInfo]: ...

    async def validate(self) -> list[ModelInfo]:
        """Raise ProviderError if the key does not work. Returns visible models."""
        return await self.list_models()

    def supports_native_tool(self, model: str, tool_key: str) -> bool:
        return False


def text_of(message: dict[str, Any]) -> str:
    return "\n".join(b.get("text", "") for b in message.get("content", []) if b.get("type") == "text")
