"""Turn Anthropic report payloads into Costura line records.

Both functions keep every dimension the API returns and never round money: amounts
become `Decimal` major units through `spend.money`, and duplicate natural keys inside
one response are summed so the upsert writes one row per key.
"""

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from costura.providers.anthropic import PROVIDER
from costura.providers.anthropic.client import (
    CONTEXT_WINDOW_PARAM,
    INFERENCE_GEO_PARAM,
    FetchedPage,
)
from costura.providers.lines import (
    CostLine,
    NormalizeError,
    UsageLine,
    parse_timestamp,
)
from costura.providers.normalization import count
from costura.spend.money import minor_to_major


def _optional_text(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise NormalizeError(f"{field} is not a string: {value!r}")
    return value


def _required_text(value: Any, *, field: str) -> str:
    text = _optional_text(value, field=field)
    if text is None:
        raise NormalizeError(f"{field} is missing")
    return text


def _buckets(payload: dict[str, Any]) -> Iterable[tuple[datetime, datetime, list[dict[str, Any]]]]:
    for bucket in payload.get("data", []):
        yield (
            parse_timestamp(bucket.get("starting_at"), field="starting_at"),
            parse_timestamp(bucket.get("ending_at"), field="ending_at"),
            bucket.get("results", []),
        )


def cost_lines_from_payload(payload: dict[str, Any]) -> list[CostLine]:
    """Every cost result in one `cost_report` page, one CostLine each, not yet aggregated."""
    lines: list[CostLine] = []
    for period_start, period_end, results in _buckets(payload):
        for result in results:
            currency = _required_text(result.get("currency"), field="currency")
            raw_amount = _required_text(result.get("amount"), field="amount")
            lines.append(
                CostLine(
                    period_start=period_start,
                    period_end=period_end,
                    workspace_id=_optional_text(result.get("workspace_id"), field="workspace_id"),
                    description=_required_text(result.get("description"), field="description"),
                    cost_type=_required_text(result.get("cost_type"), field="cost_type"),
                    model=_optional_text(result.get("model"), field="model"),
                    token_type=_optional_text(result.get("token_type"), field="token_type"),
                    service_tier=_optional_text(result.get("service_tier"), field="service_tier"),
                    context_window=_optional_text(
                        result.get("context_window"), field="context_window"
                    ),
                    inference_geo=_optional_text(
                        result.get("inference_geo"), field="inference_geo"
                    ),
                    amount=minor_to_major(raw_amount, currency),
                    currency=currency.upper(),
                    raw_amount_minor=raw_amount,
                    provider=PROVIDER,
                )
            )
    return lines


def usage_lines_from_page(page: FetchedPage) -> list[UsageLine]:
    """Usage lines of one fetched page, with the request's `context_window[]` and
    `inference_geos[]` filter values filled in where the API returned null."""
    return usage_lines_from_payload(
        page.payload,
        fixed={
            "context_window": _single_param(page.request_params, CONTEXT_WINDOW_PARAM),
            "inference_geo": _single_param(page.request_params, INFERENCE_GEO_PARAM),
        },
    )


def _single_param(params: dict[str, Any], key: str) -> str | None:
    value = params.get(key)
    if isinstance(value, list):
        if len(value) != 1:
            raise NormalizeError(f"{key} filter must have exactly one value, got {value!r}")
        value = value[0]
    return _optional_text(value, field=key)


def usage_lines_from_payload(
    payload: dict[str, Any], *, fixed: dict[str, str | None] | None = None
) -> list[UsageLine]:
    """Every usage result in one `usage_report/messages` page, not yet aggregated.

    `fixed` supplies dimension values the request pinned through a filter instead of
    `group_by[]`; a result's own non-null value wins over it.
    """
    fixed = fixed or {}
    lines: list[UsageLine] = []
    for period_start, period_end, results in _buckets(payload):
        for result in results:
            cache_creation = result.get("cache_creation") or {}
            server_tool_use = result.get("server_tool_use") or {}
            lines.append(
                UsageLine(
                    period_start=period_start,
                    period_end=period_end,
                    api_key_id=_optional_text(result.get("api_key_id"), field="api_key_id"),
                    account_id=_optional_text(result.get("account_id"), field="account_id"),
                    workspace_id=_optional_text(result.get("workspace_id"), field="workspace_id"),
                    model=_required_text(result.get("model"), field="model"),
                    service_tier=_required_text(result.get("service_tier"), field="service_tier"),
                    context_window=_optional_text(
                        result.get("context_window"), field="context_window"
                    )
                    or fixed.get("context_window"),
                    inference_geo=_optional_text(result.get("inference_geo"), field="inference_geo")
                    or fixed.get("inference_geo"),
                    uncached_input_tokens=count(
                        result.get("uncached_input_tokens"), field="uncached_input_tokens"
                    ),
                    cache_creation_5m_tokens=count(
                        cache_creation.get("ephemeral_5m_input_tokens"),
                        field="cache_creation.ephemeral_5m_input_tokens",
                    ),
                    cache_creation_1h_tokens=count(
                        cache_creation.get("ephemeral_1h_input_tokens"),
                        field="cache_creation.ephemeral_1h_input_tokens",
                    ),
                    cache_read_tokens=count(
                        result.get("cache_read_input_tokens"), field="cache_read_input_tokens"
                    ),
                    output_tokens=count(result.get("output_tokens"), field="output_tokens"),
                    web_search_requests=count(
                        server_tool_use.get("web_search_requests"),
                        field="server_tool_use.web_search_requests",
                    ),
                    provider=PROVIDER,
                )
            )
    return lines
