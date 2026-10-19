"""Normalize Claude.ai analytics cost and per-user reports."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from costura.providers.claude_ai import PROVIDER
from costura.providers.claude_ai.client import FetchedPage
from costura.providers.lines import (
    CostLine,
    NormalizeError,
    UsageLine,
    aggregate_cost_lines,
    aggregate_usage_lines,
    parse_timestamp,
)
from costura.providers.normalization import count, text_or
from costura.spend.money import minor_to_major

CURRENCY = "USD"
DEFAULT_MODEL = "(none)"
DEFAULT_PRODUCT = "other"
DEFAULT_TIER = "standard"


@dataclass(frozen=True)
class TotalLine:
    period_start: datetime
    period_end: datetime
    amount: Decimal
    list_amount: Decimal
    currency: str
    raw_amount_minor: str


def payload_watermark(payload: dict[str, Any]) -> datetime | None:
    value = payload.get("data_refreshed_at")
    return None if value is None else parse_timestamp(value, field="data_refreshed_at")


def _complete(ending_at: datetime, payload: dict[str, Any]) -> bool:
    watermark = payload_watermark(payload)
    return watermark is not None and ending_at <= watermark


def cost_lines_from_payload(payload: dict[str, Any]) -> list[CostLine]:
    lines: list[CostLine] = []
    for bucket in payload.get("data", []):
        period_start = parse_timestamp(bucket.get("starting_at"), field="starting_at")
        period_end = parse_timestamp(bucket.get("ending_at"), field="ending_at")
        if not _complete(period_end, payload):
            continue
        for result in bucket.get("results", []):
            amount = text_or(result.get("amount"), field="amount")
            list_amount = text_or(result.get("list_amount"), field="list_amount")
            currency = text_or(result.get("currency"), field="currency")
            if amount is None or list_amount is None or currency is None:
                raise NormalizeError("cost row is missing amount, list_amount, or currency")
            lines.append(
                CostLine(
                    period_start=period_start,
                    period_end=period_end,
                    workspace_id=None,
                    description=text_or(
                        result.get("product"), field="product", default=DEFAULT_PRODUCT
                    )
                    or DEFAULT_PRODUCT,
                    cost_type=text_or(result.get("cost_type"), field="cost_type", default="other")
                    or "other",
                    model=text_or(result.get("model"), field="model"),
                    token_type=text_or(result.get("token_type"), field="token_type"),
                    service_tier=text_or(result.get("speed"), field="speed"),
                    context_window=text_or(result.get("context_window"), field="context_window"),
                    inference_geo=text_or(result.get("inference_geo"), field="inference_geo"),
                    amount=minor_to_major(amount, currency),
                    list_amount=minor_to_major(list_amount, currency),
                    currency=currency.upper(),
                    raw_amount_minor=amount,
                    provider=PROVIDER,
                )
            )
    return lines


def total_lines_from_payload(payload: dict[str, Any]) -> list[TotalLine]:
    lines: list[TotalLine] = []
    for bucket in payload.get("data", []):
        period_start = parse_timestamp(bucket.get("starting_at"), field="starting_at")
        period_end = parse_timestamp(bucket.get("ending_at"), field="ending_at")
        if not _complete(period_end, payload):
            continue
        for result in bucket.get("results", []):
            amount = text_or(result.get("amount"), field="amount")
            list_amount = text_or(result.get("list_amount"), field="list_amount")
            currency = text_or(result.get("currency"), field="currency")
            if amount is None or list_amount is None or currency is None:
                raise NormalizeError("cost total is missing amount, list_amount, or currency")
            lines.append(
                TotalLine(
                    period_start=period_start,
                    period_end=period_end,
                    amount=minor_to_major(amount, currency),
                    list_amount=minor_to_major(list_amount, currency),
                    currency=currency.upper(),
                    raw_amount_minor=amount,
                )
            )
    return lines


def user_lines_from_page(page: FetchedPage) -> list[UsageLine]:
    kind = page.request_params.get("report_kind")
    if kind not in ("cost", "usage"):
        raise NormalizeError(f"unknown user report kind: {kind!r}")
    payload = page.payload
    lines: list[UsageLine] = []
    for result in payload.get("data", []):
        period_start = parse_timestamp(result.get("starting_at"), field="starting_at")
        period_end = parse_timestamp(result.get("ending_at"), field="ending_at")
        if not _complete(period_end, payload):
            continue
        actor = result.get("actor")
        if not isinstance(actor, dict):
            raise NormalizeError("user report row has no actor")
        account_id = text_or(actor.get("user_id"), field="actor.user_id")
        if account_id is None:
            raise NormalizeError("actor.user_id is missing")
        cache = result.get("cache_creation") or {}
        if not isinstance(cache, dict):
            raise NormalizeError("cache_creation is not an object")
        tools = result.get("server_tool_use") or {}
        if not isinstance(tools, dict):
            raise NormalizeError("server_tool_use is not an object")
        amount: Decimal | None = None
        list_amount: Decimal | None = None
        currency: str | None = None
        if kind == "cost":
            raw_amount = text_or(result.get("amount"), field="amount")
            raw_list = text_or(result.get("list_amount"), field="list_amount")
            currency = text_or(result.get("currency"), field="currency")
            if raw_amount is None or raw_list is None or currency is None:
                raise NormalizeError("user cost row is missing amount, list_amount, or currency")
            amount = minor_to_major(raw_amount, currency)
            list_amount = minor_to_major(raw_list, currency)
        lines.append(
            UsageLine(
                period_start=period_start,
                period_end=period_end,
                api_key_id=None,
                account_id=account_id,
                workspace_id=None,
                model=text_or(result.get("model"), field="model", default=DEFAULT_MODEL)
                or DEFAULT_MODEL,
                service_tier=DEFAULT_TIER,
                context_window=None,
                inference_geo=None,
                uncached_input_tokens=(
                    count(result.get("uncached_input_tokens"), field="uncached_input_tokens")
                    if kind == "usage"
                    else 0
                ),
                cache_creation_5m_tokens=(
                    count(
                        cache.get("ephemeral_5m_input_tokens"),
                        field="cache_creation.ephemeral_5m_input_tokens",
                    )
                    if kind == "usage"
                    else 0
                ),
                cache_creation_1h_tokens=(
                    count(
                        cache.get("ephemeral_1h_input_tokens"),
                        field="cache_creation.ephemeral_1h_input_tokens",
                    )
                    if kind == "usage"
                    else 0
                ),
                cache_read_tokens=(
                    count(result.get("cache_read_input_tokens"), field="cache_read_input_tokens")
                    if kind == "usage"
                    else 0
                ),
                output_tokens=(
                    count(result.get("output_tokens"), field="output_tokens")
                    if kind == "usage"
                    else 0
                ),
                web_search_requests=(
                    count(
                        tools.get("web_search_requests"),
                        field="server_tool_use.web_search_requests",
                    )
                    if kind == "usage"
                    else 0
                ),
                request_count=(
                    count(result.get("requests"), field="requests") if kind == "usage" else 0
                ),
                amount=amount,
                list_amount=list_amount,
                currency=currency.upper() if currency else None,
                product=text_or(result.get("product"), field="product", default=DEFAULT_PRODUCT),
                provider=PROVIDER,
            )
        )
    return lines


def page_amount(payload: dict[str, Any], start: datetime, end: datetime) -> Decimal:
    total = Decimal("0")
    for bucket in payload.get("data", []):
        bucket_start = parse_timestamp(bucket.get("starting_at"), field="starting_at")
        bucket_end = parse_timestamp(bucket.get("ending_at"), field="ending_at")
        if not start <= bucket_start < end or not _complete(bucket_end, payload):
            continue
        for result in bucket.get("results", []):
            total += minor_to_major(result["amount"], result["currency"])
    return total


__all__ = [
    "aggregate_cost_lines",
    "aggregate_usage_lines",
    "cost_lines_from_payload",
    "page_amount",
    "payload_watermark",
    "total_lines_from_payload",
    "user_lines_from_page",
]
