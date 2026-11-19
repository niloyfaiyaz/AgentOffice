"""Builds provider clients from stored credentials. All provider traffic originates here,
in the local backend; the browser never sees API keys."""
from __future__ import annotations

from typing import Optional

from ..config import settings
from ..security.credentials import load_secret
from .base import Provider, ProviderError

TEST_PROVIDER = "scripted-test"
_cache: dict[tuple[str, str], Provider] = {}
_overrides: dict[str, Provider] = {}


def available_providers() -> list[str]:
    names = ["anthropic", "openai"]
    if settings.enable_test_provider:
        names.append(TEST_PROVIDER)
    return names


def set_override(name: str, provider: Optional[Provider]) -> None:
    """Testing hook: inject a provider instance (used by automated tests only)."""
    if provider is None:
        _overrides.pop(name, None)
    else:
        _overrides[name] = provider


def get_provider(name: str) -> Provider:
    if name in _overrides:
        return _overrides[name]
    if name == TEST_PROVIDER:
        if not settings.enable_test_provider:
            raise ProviderError("not_configured", "The scripted test provider is disabled.")
        from .scripted import ScriptedProvider

        return ScriptedProvider()
    secret = load_secret(name)
    if not secret:
        raise ProviderError("not_configured", f"No API key is configured for {name}. Add one in Settings.")
    key = (name, secret[-6:])
    if key in _cache:
        return _cache[key]
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider

        p: Provider = AnthropicProvider(secret)
    elif name == "openai":
        from .openai_provider import OpenAIProvider

        p = OpenAIProvider(secret)
    else:
        raise ProviderError("not_configured", f"Unknown provider {name}")
    _cache.clear()  # drop clients built with replaced keys
    _cache[key] = p
    return p


def build_provider_with_key(name: str, secret: str) -> Provider:
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(secret)
    if name == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(secret)
    raise ProviderError("not_configured", f"Unknown provider {name}")


def invalidate() -> None:
    _cache.clear()
