"""Turn OpenAI Admin API cost and usage pages into Costura line records.

Costs come grouped by `(project_id, api_key_id, line_item)`. A line item reads
"<model>, <kind>[, <modifier>]" for token money ("gpt-4o-mini-2024-07-18, input",
"gpt-5.6-sol, cached input, long context") and names a product for everything else
("web search tool calls", "text-embedding-3-large"). The kinds in `LINE_ITEM_KINDS` become
token-type buckets; known non-token products keep a family-specific `cost_type`. Since each
result carries the API key OpenAI billed it to, the allocation
(`key_attributed`, spend/allocate.py) hands every bucket to that key whatever its kind, so no
OpenAI money is left unattributed. Nothing is dropped and nothing is rounded: amounts are
`Decimal(str(value))` in USD major units as the API reports them.

Completions usage becomes token lines. The other organization usage families become activity
lines with the unit each endpoint publishes.
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from costura.providers.lines import (
    ActivityLine,
    CostLine,
    NormalizeError,
    UsageLine,
    aggregate_cost_lines,
    aggregate_usage_lines,
)
from costura.providers.normalization import count, optional_text, required_text, unix_seconds
from costura.providers.openai import PROVIDER

COST_TYPE_TOKENS = "tokens"


COST_TYPE_WEB_SEARCH = "web_search"


COST_TYPE_OTHER = "other"


SERVICE_TIER = "standard"


CURRENCY = "USD"


CONTEXT_WINDOW_LONG = "long_context"


# `line_item` kind -> Costura token type. The reference does not enumerate the kinds; the
# table holds the vocabulary read from a live organization plus the underscore
# spellings of the usage report. An unknown kind keeps its money as an "other" line.
LINE_ITEM_KINDS: dict[str, str] = {
    "input": "uncached_input_tokens",
    "input_tokens": "uncached_input_tokens",
    "input_uncached": "uncached_input_tokens",
    "uncached_input": "uncached_input_tokens",
    "cached input": "cache_read_input_tokens",
    "cached_input": "cache_read_input_tokens",
    "input_cached": "cache_read_input_tokens",
    "input_cached_tokens": "cache_read_input_tokens",
    "cached_input_tokens": "cache_read_input_tokens",
    "cache writes": "cache_creation.ephemeral_5m_input_tokens",
    "cache_write": "cache_creation.ephemeral_5m_input_tokens",
    "input_cache_write": "cache_creation.ephemeral_5m_input_tokens",
    "input_cache_write_tokens": "cache_creation.ephemeral_5m_input_tokens",
    "output": "output_tokens",
    "output_tokens": "output_tokens",
}


# Third part of a line item -> `context_window` value.
LINE_ITEM_MODIFIERS: dict[str, str] = {"long context": CONTEXT_WINDOW_LONG}


# Model-less line items that are a product of their own.
WEB_SEARCH_LINE_ITEMS = frozenset({"web search tool calls", "web search"})


NON_TOKEN_COST_PATTERNS = (
    ("code interpreter", "code_interpreter"),
    ("vector store", "vector_stores"),
    ("embedding", "embeddings"),
    ("moderation", "moderations"),
    ("transcription", "audio"),
    ("whisper", "audio"),
    ("audio speech", "audio"),
    ("speech", "audio"),
    ("tts", "audio"),
    ("image", "images"),
)


ACTIVITY_FAMILY_SPECS: dict[str, tuple[str, str, str | None]] = {
    "images": ("images", "images", "num_model_requests"),
    "embeddings": ("input_tokens", "input_tokens", "num_model_requests"),
    "moderations": ("input_tokens", "input_tokens", "num_model_requests"),
    "audio_speeches": ("characters", "characters", "num_model_requests"),
    "audio_transcriptions": ("seconds", "seconds", "num_model_requests"),
    "vector_stores": ("bytes", "usage_bytes", None),
    "code_interpreter_sessions": ("sessions", "num_sessions", None),
}


@dataclass(frozen=True)
class ParsedLineItem:
    model: str | None
    token_type: str | None
    cost_type: str
    context_window: str | None

    @property
    def attributable_tokens(self) -> bool:
        return self.cost_type == COST_TYPE_TOKENS


def parse_line_item(line_item: str) -> ParsedLineItem:
    """Split "<model>, <kind>[, <modifier>]" into the cost dimensions.

    "gpt-4o-mini-2024-07-18, output" -> tokens bucket with `output_tokens`;
    "gpt-5.6-sol, input, long context" -> the same with `context_window="long_context"`;
    "web search tool calls" -> `web_search` with no model; recognized non-token products get
    their family cost type, while an unknown item stays `other`.
    """
    parts = [part.strip() for part in line_item.split(",")]
    parts = [part for part in parts if part]
    if not parts:
        return ParsedLineItem(None, None, COST_TYPE_OTHER, None)
    if len(parts) == 1:
        item = parts[0]
        if item.lower() in WEB_SEARCH_LINE_ITEMS:
            return ParsedLineItem(None, None, COST_TYPE_WEB_SEARCH, None)
        return ParsedLineItem(item, None, _non_token_cost_type(item), None)
    model, kind, *modifiers = parts
    token_type = LINE_ITEM_KINDS.get(kind.lower())
    context_window = None
    for modifier in modifiers:
        context_window = LINE_ITEM_MODIFIERS.get(modifier.lower(), context_window)
    if token_type is None:
        return ParsedLineItem(model, None, _non_token_cost_type(", ".join(parts)), context_window)
    return ParsedLineItem(model, token_type, COST_TYPE_TOKENS, context_window)


def _non_token_cost_type(line_item: str) -> str:
    lowered = line_item.lower().replace("_", " ")
    if lowered in WEB_SEARCH_LINE_ITEMS or "web search" in lowered:
        return COST_TYPE_WEB_SEARCH
    for fragment, cost_type in NON_TOKEN_COST_PATTERNS:
        if fragment in lowered:
            return cost_type
    return COST_TYPE_OTHER


def parse_bucket_bounds(bucket: dict[str, Any]) -> tuple[datetime, datetime]:
    return (
        unix_seconds(bucket.get("start_time"), field="start_time"),
        unix_seconds(bucket.get("end_time"), field="end_time"),
    )


def bucket_day(bucket: dict[str, Any]) -> datetime:
    return unix_seconds(bucket.get("start_time"), field="start_time")


def result_amount(result: dict[str, Any]) -> tuple[Decimal, str]:
    """`(amount, currency)` of one costs result; the API reports major units as a float."""
    amount = result.get("amount")
    if not isinstance(amount, dict):
        raise NormalizeError(f"amount is not an object: {amount!r}")
    value = amount.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise NormalizeError(f"amount.value is not a number: {value!r}")
    try:
        money = Decimal(str(value))
    except InvalidOperation as exc:
        raise NormalizeError(f"amount.value is not a number: {value!r}") from exc
    currency = amount.get("currency")
    if not isinstance(currency, str) or not currency:
        raise NormalizeError("amount.currency is missing")
    return money, currency.upper()


def cost_lines_from_page(payload: dict[str, Any]) -> list[CostLine]:
    """Every costs result of one page, one CostLine each, not yet aggregated."""
    lines: list[CostLine] = []
    for bucket in _buckets(payload):
        period_start, period_end = parse_bucket_bounds(bucket)
        for result in bucket.get("results", []):
            if not isinstance(result, dict):
                continue
            amount, currency = result_amount(result)
            line_item = result.get("line_item")
            description = line_item if isinstance(line_item, str) and line_item else "unlabeled"
            parsed = parse_line_item(description)
            lines.append(
                CostLine(
                    period_start=period_start,
                    period_end=period_end,
                    workspace_id=optional_text(result.get("project_id"), field="project_id"),
                    description=description,
                    cost_type=parsed.cost_type,
                    model=parsed.model,
                    token_type=parsed.token_type,
                    service_tier=SERVICE_TIER if parsed.attributable_tokens else None,
                    context_window=parsed.context_window,
                    inference_geo=None,
                    amount=amount,
                    currency=currency,
                    raw_amount_minor=str(result["amount"]["value"]),
                    provider=PROVIDER,
                    api_key_id=optional_text(result.get("api_key_id"), field="api_key_id"),
                )
            )
    return lines


def usage_lines_from_page(payload: dict[str, Any]) -> list[UsageLine]:
    """Every completions result of one page, not yet aggregated. `input_tokens` is the whole
    prompt; the uncached share is `input_uncached_tokens` when the API reports it, otherwise
    the prompt minus cache reads and cache writes."""
    lines: list[UsageLine] = []
    for bucket in _buckets(payload):
        period_start, period_end = parse_bucket_bounds(bucket)
        for result in bucket.get("results", []):
            if not isinstance(result, dict):
                continue
            input_tokens = count(result.get("input_tokens"), field="input_tokens")
            cached = min(
                count(result.get("input_cached_tokens"), field="input_cached_tokens"), input_tokens
            )
            cache_write = min(
                count(result.get("input_cache_write_tokens"), field="input_cache_write_tokens"),
                input_tokens - cached,
            )
            uncached = result.get("input_uncached_tokens")
            uncached_tokens = (
                count(uncached, field="input_uncached_tokens")
                if uncached is not None
                else input_tokens - cached - cache_write
            )
            lines.append(
                UsageLine(
                    period_start=period_start,
                    period_end=period_end,
                    api_key_id=optional_text(result.get("api_key_id"), field="api_key_id"),
                    account_id=optional_text(result.get("user_id"), field="user_id"),
                    workspace_id=optional_text(result.get("project_id"), field="project_id"),
                    model=required_text(result.get("model"), field="model"),
                    service_tier=SERVICE_TIER,
                    context_window=None,
                    inference_geo=None,
                    uncached_input_tokens=max(uncached_tokens, 0),
                    cache_creation_5m_tokens=cache_write,
                    cache_creation_1h_tokens=0,
                    cache_read_tokens=cached,
                    output_tokens=count(result.get("output_tokens"), field="output_tokens"),
                    web_search_requests=0,
                    provider=PROVIDER,
                    reasoning_tokens=0,
                    request_count=count(
                        result.get("num_model_requests"), field="num_model_requests"
                    ),
                )
            )
    return lines


def activity_lines_from_page(payload: dict[str, Any], family: str) -> list[ActivityLine]:
    """Normalize one organization usage family without inventing unsupported dimensions."""
    try:
        unit, quantity_field, request_field = ACTIVITY_FAMILY_SPECS[family]
    except KeyError as exc:
        raise NormalizeError(f"unknown activity family: {family!r}") from exc
    lines: list[ActivityLine] = []
    for bucket in _buckets(payload):
        period_start, period_end = parse_bucket_bounds(bucket)
        for result in bucket.get("results", []):
            if not isinstance(result, dict):
                continue
            detail = None
            if family == "images":
                image_detail = {
                    key: value
                    for key in ("size", "source")
                    if (value := optional_text(result.get(key), field=key)) is not None
                }
                detail = (
                    json.dumps(image_detail, sort_keys=True, separators=(",", ":"))
                    if image_detail
                    else None
                )
            lines.append(
                ActivityLine(
                    period_start=period_start,
                    period_end=period_end,
                    family=family,
                    unit=unit,
                    quantity=_decimal(result.get(quantity_field), field=quantity_field),
                    request_count=(
                        count(result.get(request_field), field=request_field)
                        if request_field is not None
                        else 0
                    ),
                    workspace_id=optional_text(result.get("project_id"), field="project_id"),
                    api_key_id=optional_text(result.get("api_key_id"), field="api_key_id"),
                    account_id=optional_text(result.get("user_id"), field="user_id"),
                    model=optional_text(result.get("model"), field="model"),
                    detail=detail,
                    provider=PROVIDER,
                )
            )
    return lines


def aggregate_activity_lines(lines: Iterable[ActivityLine]) -> list[ActivityLine]:
    merged: dict[tuple[Any, ...], ActivityLine] = {}
    for line in lines:
        existing = merged.get(line.key)
        if existing is None:
            merged[line.key] = line
            continue
        if existing.unit != line.unit:
            raise NormalizeError(f"mixed units for one activity key: {existing.key}")
        merged[line.key] = replace(
            existing,
            quantity=existing.quantity + line.quantity,
            request_count=existing.request_count + line.request_count,
        )
    return list(merged.values())


def total_amounts(payload: dict[str, Any]) -> list[Decimal]:
    """The amounts of an ungrouped costs page, one per day bucket."""
    return [
        result_amount(result)[0]
        for bucket in _buckets(payload)
        for result in bucket.get("results", [])
        if isinstance(result, dict)
    ]


def _buckets(payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
    data = payload.get("data", [])
    if not isinstance(data, list):
        raise NormalizeError(f"data is not a list: {type(data).__name__}")
    for bucket in data:
        if isinstance(bucket, dict) and isinstance(bucket.get("results"), list):
            yield bucket


def _decimal(value: Any, *, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise NormalizeError(f"{field} is not a number: {value!r}")
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise NormalizeError(f"{field} is not a number: {value!r}") from exc


__all__ = [
    "ACTIVITY_FAMILY_SPECS",
    "CONTEXT_WINDOW_LONG",
    "COST_TYPE_OTHER",
    "COST_TYPE_TOKENS",
    "COST_TYPE_WEB_SEARCH",
    "CURRENCY",
    "LINE_ITEM_KINDS",
    "LINE_ITEM_MODIFIERS",
    "SERVICE_TIER",
    "WEB_SEARCH_LINE_ITEMS",
    "ParsedLineItem",
    "activity_lines_from_page",
    "aggregate_activity_lines",
    "aggregate_cost_lines",
    "aggregate_usage_lines",
    "bucket_day",
    "cost_lines_from_page",
    "parse_bucket_bounds",
    "parse_line_item",
    "result_amount",
    "total_amounts",
    "usage_lines_from_page",
]
