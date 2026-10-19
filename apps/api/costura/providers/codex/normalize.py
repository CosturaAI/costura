"""Normalize official Codex daily usage rows into spend and inventory records."""

from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from costura.models import CreditPrice
from costura.providers.codex import PROVIDER
from costura.providers.codex.pricing import effective_price
from costura.providers.lines import (
    CostLine,
    NormalizeError,
    UsageLine,
    aggregate_cost_lines,
    aggregate_usage_lines,
)
from costura.providers.normalization import text_or
from costura.providers.records import (
    USER_KIND_SERVICE_ACCOUNT,
    USER_KIND_USER,
    UserRecord,
)

CURRENCY = "USD"
COST_TYPE = "credits"
DEFAULT_MODEL = "(none)"
DEFAULT_SPEED = "standard"
DEFAULT_CLIENT = "Codex"


def _epoch(value: Any, *, field: str) -> datetime:
    if isinstance(value, bool) or not isinstance(value, int):
        raise NormalizeError(f"{field} is not Unix seconds: {value!r}")
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise NormalizeError(f"{field} is outside the supported range: {value!r}") from exc


def _count(value: Any, *, field: str) -> int:
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise NormalizeError(f"{field} is not a non-negative integer: {value!r}")
    return value


def _amount(value: Any, *, field: str) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise NormalizeError(f"{field} is not a number: {value!r}")
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise NormalizeError(f"{field} is not a number: {value!r}") from exc
    if not amount.is_finite() or amount < 0:
        raise NormalizeError(f"{field} is not a non-negative finite number: {value!r}")
    return amount


def _usage_buckets(row: dict[str, Any]) -> list[dict[str, Any]]:
    models = row.get("models")
    if isinstance(models, list) and models:
        return [model for model in models if isinstance(model, dict)]
    totals = row.get("totals")
    if not isinstance(totals, dict):
        raise NormalizeError("usage row has no totals object")
    return [{"model": DEFAULT_MODEL, "speed": DEFAULT_SPEED, **totals}]


def _client(row: dict[str, Any]) -> str:
    clients = row.get("clients")
    if not isinstance(clients, list):
        raise NormalizeError("usage row clients is not an array")
    names = {
        client_id
        for client in clients
        if isinstance(client, dict)
        and isinstance((client_id := client.get("client_id")), str)
        and client_id
    }
    return next(iter(names)) if len(names) == 1 else DEFAULT_CLIENT


def cost_lines_from_payload(
    payload: dict[str, Any],
    *,
    workspace_id: str,
    prices: list[CreditPrice],
) -> list[CostLine]:
    lines: list[CostLine] = []
    for row in payload.get("data", []):
        if not isinstance(row, dict):
            continue
        period_start = _epoch(row.get("start_time"), field="start_time")
        period_end = _epoch(row.get("end_time"), field="end_time")
        price = effective_price(prices, period_start.date())
        if price is None:
            continue
        client = _client(row)
        for bucket in _usage_buckets(row):
            credits = _amount(bucket.get("credits"), field="models.credits")
            if credits == 0:
                continue
            lines.append(
                CostLine(
                    period_start=period_start,
                    period_end=period_end,
                    workspace_id=workspace_id,
                    description=client,
                    cost_type=COST_TYPE,
                    model=text_or(bucket.get("model"), field="models.model", default=DEFAULT_MODEL),
                    token_type=None,
                    service_tier=text_or(
                        bucket.get("speed"), field="models.speed", default=DEFAULT_SPEED
                    ),
                    context_window=None,
                    inference_geo=None,
                    amount=credits * price,
                    currency=CURRENCY,
                    raw_amount_minor=str(credits),
                    provider=PROVIDER,
                )
            )
    return lines


def _actor(row: dict[str, Any]) -> tuple[str, UserRecord]:
    actor = row.get("actor")
    actor = actor if isinstance(actor, dict) else {}
    user_id = text_or(actor.get("user_id") or row.get("user_id"), field="actor.user_id")
    if user_id is None:
        raise NormalizeError("per-user usage row has no actor.user_id or user_id")
    actor_type = (
        text_or(actor.get("type"), field="actor.type", default="ACCOUNT_USER") or "ACCOUNT_USER"
    )
    email = text_or(actor.get("email"), field="actor.email", default=user_id) or user_id
    kind = USER_KIND_USER if actor_type == "ACCOUNT_USER" else USER_KIND_SERVICE_ACCOUNT
    return user_id, UserRecord(
        external_id=user_id,
        email=email,
        role=actor_type.casefold(),
        added_at=None,
        provider=PROVIDER,
        kind=kind,
    )


def user_lines_from_payload(
    payload: dict[str, Any],
    *,
    workspace_id: str,
    prices: list[CreditPrice],
) -> list[UsageLine | UserRecord]:
    lines: list[UsageLine | UserRecord] = []
    users: dict[str, UserRecord] = {}
    for row in payload.get("data", []):
        if not isinstance(row, dict):
            continue
        period_start = _epoch(row.get("start_time"), field="start_time")
        period_end = _epoch(row.get("end_time"), field="end_time")
        account_id, user = _actor(row)
        users[user.external_id] = user
        price = effective_price(prices, period_start.date())
        client = _client(row)
        totals = row.get("totals")
        if not isinstance(totals, dict):
            raise NormalizeError("usage row has no totals object")
        turns = _count(totals.get("turns"), field="totals.turns")
        for index, bucket in enumerate(_usage_buckets(row)):
            credits = _amount(bucket.get("credits"), field="models.credits")
            lines.append(
                UsageLine(
                    period_start=period_start,
                    period_end=period_end,
                    api_key_id=None,
                    account_id=account_id,
                    workspace_id=workspace_id,
                    model=text_or(bucket.get("model"), field="models.model", default=DEFAULT_MODEL)
                    or DEFAULT_MODEL,
                    service_tier=text_or(
                        bucket.get("speed"), field="models.speed", default=DEFAULT_SPEED
                    )
                    or DEFAULT_SPEED,
                    context_window=None,
                    inference_geo=None,
                    uncached_input_tokens=_count(
                        bucket.get("uncached_text_input_tokens"),
                        field="models.uncached_text_input_tokens",
                    ),
                    cache_creation_5m_tokens=0,
                    cache_creation_1h_tokens=0,
                    cache_read_tokens=_count(
                        bucket.get("cached_text_input_tokens"),
                        field="models.cached_text_input_tokens",
                    ),
                    output_tokens=_count(
                        bucket.get("text_output_tokens"),
                        field="models.text_output_tokens",
                    ),
                    web_search_requests=0,
                    request_count=turns if index == 0 else 0,
                    amount=None if price is None else credits * price,
                    currency=None if price is None else CURRENCY,
                    product=client,
                    provider=PROVIDER,
                )
            )
    return [*lines, *users.values()]


def aggregate_user_lines(
    lines: Iterable[UsageLine | UserRecord],
) -> list[UsageLine | UserRecord]:
    usage = aggregate_usage_lines(line for line in lines if isinstance(line, UsageLine))
    users = {line.external_id: line for line in lines if isinstance(line, UserRecord)}
    return [*usage, *users.values()]


def page_credits(payload: dict[str, Any], window_start: datetime, window_end: datetime) -> Decimal:
    total = Decimal("0")
    for row in payload.get("data", []):
        if not isinstance(row, dict):
            continue
        period_start = _epoch(row.get("start_time"), field="start_time")
        if not window_start <= period_start < window_end:
            continue
        totals = row.get("totals")
        if not isinstance(totals, dict):
            raise NormalizeError("usage row has no totals object")
        total += _amount(totals.get("credits"), field="totals.credits")
    return total


__all__ = [
    "COST_TYPE",
    "aggregate_cost_lines",
    "aggregate_user_lines",
    "cost_lines_from_payload",
    "page_credits",
    "user_lines_from_payload",
]
