"""Cost estimation. All figures are ESTIMATES computed from configured per-token prices;
actual provider charges may differ and are billed by the provider, not by AgentOffice."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from .models import ModelConfiguration
from .providers.base import Usage

MTOK = Decimal(1_000_000)
# Published Anthropic web search price ($10 per 1,000 searches); configurable here.
WEB_SEARCH_PRICE_USD = Decimal("0.01")


def price_snapshot(mc: Optional[ModelConfiguration]) -> dict[str, Any]:
    if mc is None:
        return {"configured": False}
    return {
        "configured": mc.input_price_per_mtok is not None and mc.output_price_per_mtok is not None,
        "input_per_mtok": str(mc.input_price_per_mtok) if mc.input_price_per_mtok is not None else None,
        "output_per_mtok": str(mc.output_price_per_mtok) if mc.output_price_per_mtok is not None else None,
        "cache_read_per_mtok": str(mc.cache_read_price_per_mtok) if mc.cache_read_price_per_mtok is not None else None,
        "cache_write_per_mtok": str(mc.cache_write_price_per_mtok) if mc.cache_write_price_per_mtok is not None else None,
        "source": mc.pricing_source,
    }


def is_priced(mc: Optional[ModelConfiguration]) -> bool:
    return bool(mc and mc.input_price_per_mtok is not None and mc.output_price_per_mtok is not None)


def cost_of(mc: Optional[ModelConfiguration], usage: Usage) -> Optional[Decimal]:
    if not is_priced(mc):
        return None
    assert mc is not None
    inp = Decimal(usage.input_tokens) * mc.input_price_per_mtok / MTOK
    out = Decimal(usage.output_tokens) * mc.output_price_per_mtok / MTOK
    cr_price = mc.cache_read_price_per_mtok if mc.cache_read_price_per_mtok is not None else mc.input_price_per_mtok
    cw_price = mc.cache_write_price_per_mtok if mc.cache_write_price_per_mtok is not None else mc.input_price_per_mtok
    cr = Decimal(usage.cache_read_tokens) * cr_price / MTOK
    cw = Decimal(usage.cache_write_tokens) * cw_price / MTOK
    extra = Decimal(usage.other.get("web_search_requests", 0)) * WEB_SEARCH_PRICE_USD
    return (inp + out + cr + cw + extra).quantize(Decimal("0.000001"))


def estimate_tokens(text_chars: int) -> int:
    # Conservative heuristic (~3.5 chars/token) used only for pre-call budget reservation.
    return int(text_chars / 3.5) + 50


def estimate_call_cost(mc: Optional[ModelConfiguration], prompt_chars: int, max_output_tokens: int) -> Optional[Decimal]:
    """Upper-bound estimate for one call: estimated input + the full output allowance."""
    if not is_priced(mc):
        return None
    assert mc is not None
    inp = Decimal(estimate_tokens(prompt_chars)) * mc.input_price_per_mtok / MTOK
    out = Decimal(max_output_tokens) * mc.output_price_per_mtok / MTOK
    return (inp + out).quantize(Decimal("0.000001"))
