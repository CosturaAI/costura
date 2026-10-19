"""Canonical line records every provider normalizes into, and the helpers that merge them.

Amounts are `Decimal` major units and never rounded; `aggregate_*` sum lines that share a
natural key so an upsert writes one row per key. Each line names its provider explicitly;
"""

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any


class NormalizeError(ValueError):
    """A result lacks a field the normalized model requires."""


@dataclass(frozen=True)
class CostLine:
    period_start: datetime
    period_end: datetime
    workspace_id: str | None
    description: str
    cost_type: str
    model: str | None
    token_type: str | None
    service_tier: str | None
    context_window: str | None
    inference_geo: str | None
    amount: Decimal
    currency: str
    raw_amount_minor: str
    list_amount: Decimal | None = None
    provider: str = field(kw_only=True)
    # The API key the provider itself reports the bucket under; None when the report has
    # no key grain (Anthropic, OpenRouter).
    api_key_id: str | None = None

    @property
    def key(self) -> tuple[Any, ...]:
        return (
            self.provider,
            self.period_start,
            self.workspace_id,
            self.description,
            self.cost_type,
            self.model,
            self.token_type,
            self.service_tier,
            self.context_window,
            self.inference_geo,
            self.api_key_id,
        )


@dataclass(frozen=True)
class UsageLine:
    period_start: datetime
    period_end: datetime
    api_key_id: str | None
    account_id: str | None
    workspace_id: str | None
    model: str
    service_tier: str
    context_window: str | None
    inference_geo: str | None
    uncached_input_tokens: int
    cache_creation_5m_tokens: int
    cache_creation_1h_tokens: int
    cache_read_tokens: int
    output_tokens: int
    web_search_requests: int
    provider: str = field(kw_only=True)
    # Counters Anthropic does not report; OpenRouter fills them. `amount` is the
    # provider-attributed cost of the line when the provider prices per key; `byok_amount` the
    # inference cost routed to another provider's key, billed by that provider, not this one.
    reasoning_tokens: int = 0
    request_count: int = 0
    amount: Decimal | None = None
    currency: str | None = None
    byok_amount: Decimal | None = None
    list_amount: Decimal | None = None
    product: str | None = None

    @property
    def key(self) -> tuple[Any, ...]:
        return (
            self.provider,
            self.period_start,
            self.api_key_id,
            self.account_id,
            self.workspace_id,
            self.model,
            self.service_tier,
            self.context_window,
            self.inference_geo,
            self.product,
        )


@dataclass(frozen=True)
class ActivityLine:
    period_start: datetime
    period_end: datetime
    family: str
    unit: str
    quantity: Decimal
    request_count: int
    workspace_id: str | None
    api_key_id: str | None
    account_id: str | None
    model: str | None
    detail: str | None
    provider: str = field(kw_only=True)

    @property
    def key(self) -> tuple[Any, ...]:
        return (
            self.provider,
            self.period_start,
            self.family,
            self.workspace_id,
            self.api_key_id,
            self.account_id,
            self.model,
            self.detail,
        )


def parse_timestamp(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise NormalizeError(f"{field} is not a string: {value!r}")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise NormalizeError(f"{field} has no timezone: {value!r}")
    return parsed.astimezone(UTC)


def aggregate_cost_lines(lines: Iterable[CostLine]) -> list[CostLine]:
    """Sum amounts that share a natural key; the raw string becomes a `+`-joined list."""
    merged: dict[tuple[Any, ...], CostLine] = {}
    for line in lines:
        existing = merged.get(line.key)
        if existing is None:
            merged[line.key] = line
            continue
        if existing.currency != line.currency:
            raise NormalizeError(f"mixed currencies for one key: {existing.key}")
        merged[line.key] = replace(
            existing,
            amount=existing.amount + line.amount,
            list_amount=_sum_optional(existing.list_amount, line.list_amount),
            raw_amount_minor=f"{existing.raw_amount_minor}+{line.raw_amount_minor}",
        )
    return list(merged.values())


def aggregate_usage_lines(lines: Iterable[UsageLine]) -> list[UsageLine]:
    """Sum token counters that share a natural key."""
    merged: dict[tuple[Any, ...], UsageLine] = {}
    for line in lines:
        existing = merged.get(line.key)
        if existing is None:
            merged[line.key] = line
            continue
        merged[line.key] = replace(
            existing,
            uncached_input_tokens=existing.uncached_input_tokens + line.uncached_input_tokens,
            cache_creation_5m_tokens=(
                existing.cache_creation_5m_tokens + line.cache_creation_5m_tokens
            ),
            cache_creation_1h_tokens=(
                existing.cache_creation_1h_tokens + line.cache_creation_1h_tokens
            ),
            cache_read_tokens=existing.cache_read_tokens + line.cache_read_tokens,
            output_tokens=existing.output_tokens + line.output_tokens,
            web_search_requests=existing.web_search_requests + line.web_search_requests,
            reasoning_tokens=existing.reasoning_tokens + line.reasoning_tokens,
            request_count=existing.request_count + line.request_count,
            amount=_sum_optional(existing.amount, line.amount),
            byok_amount=_sum_optional(existing.byok_amount, line.byok_amount),
            list_amount=_sum_optional(existing.list_amount, line.list_amount),
        )
    return list(merged.values())


def _sum_optional(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None and right is None:
        return None
    return (left or Decimal("0")) + (right or Decimal("0"))
