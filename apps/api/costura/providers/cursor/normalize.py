"""Normalize Cursor's hourly usage events to daily cost and per-principal usage lines."""

import calendar
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from costura.models import ProviderUser
from costura.providers.cursor import PROVIDER
from costura.providers.lines import (
    CostLine,
    NormalizeError,
    UsageLine,
    aggregate_cost_lines,
    aggregate_usage_lines,
)
from costura.providers.normalization import loose_text, optional_decimal
from costura.providers.records import (
    USER_KIND_SERVICE_ACCOUNT,
    USER_KIND_USER,
    UserRecord,
)

CURRENCY = "USD"
COST_TYPE = "tokens"
SEAT_COST_TYPE = "seat"
SEAT_MODEL = "__cursor_seat__"
INCLUDED_IN_BUSINESS = "Included in Business"
ABSENT_IDENTIFIER_VALUES = frozenset({"null"})


@dataclass(frozen=True)
class UserDirectory:
    """Case-insensitive member e-mail to Cursor's stable encoded user id."""

    by_email: dict[str, str]

    @classmethod
    def load(cls, session: Session, provider_account_id: int) -> UserDirectory:
        rows = session.execute(
            select(ProviderUser.email, ProviderUser.external_id).where(
                ProviderUser.provider == PROVIDER,
                ProviderUser.provider_account_id == provider_account_id,
                ProviderUser.kind == "user",
            )
        ).all()
        return cls.from_rows(rows)

    @classmethod
    def from_rows(cls, rows: Iterable[tuple[str, str]]) -> UserDirectory:
        found: dict[str, str | None] = {}
        for email, external_id in rows:
            key = email.casefold()
            found[key] = None if key in found else external_id
        return cls({email: external_id for email, external_id in found.items() if external_id})

    def resolve(self, email: str) -> str:
        return self.by_email.get(email.casefold(), email)


def parse_event_time(value: Any) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise NormalizeError(f"timestamp is not epoch milliseconds: {value!r}")
    try:
        milliseconds = int(value)
    except ValueError as exc:
        raise NormalizeError(f"timestamp is not epoch milliseconds: {value!r}") from exc
    try:
        return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise NormalizeError(f"timestamp is outside the supported range: {value!r}") from exc


def event_day(row: dict[str, Any]) -> tuple[datetime, datetime]:
    value = parse_event_time(row.get("timestamp"))
    start = value.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _text(row: dict[str, Any], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value:
        raise NormalizeError(f"{field} is missing")
    return value


def _optional_text(row: dict[str, Any], field: str) -> str | None:
    value = row.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise NormalizeError(f"{field} is not a non-empty string: {value!r}")
    return value


def _optional_identifier(row: dict[str, Any], field: str) -> str | None:
    value = _optional_text(row, field)
    if value is None or value.casefold() in ABSENT_IDENTIFIER_VALUES:
        return None
    return value


def _count(row: dict[str, Any], field: str) -> int:
    value = row.get(field)
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise NormalizeError(f"tokenUsage.{field} is not a non-negative integer: {value!r}")
    return value


def charged_cents(row: dict[str, Any], field: str = "chargedCents") -> Decimal:
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise NormalizeError(f"{field} is not a number: {value!r}")
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise NormalizeError(f"{field} is not a number: {value!r}") from exc
    if not amount.is_finite() or amount < 0:
        raise NormalizeError(f"{field} is not a non-negative finite number: {value!r}")
    return amount


def lines_from_events(
    events: Iterable[dict[str, Any]],
    directory: UserDirectory,
    *,
    include_included_in_business: bool = True,
) -> tuple[list[CostLine], list[UsageLine], list[UserRecord]]:
    cost: list[CostLine] = []
    usage: list[UsageLine] = []
    principals: dict[tuple[str, str], UserRecord] = {}
    for event in events:
        period_start, period_end = event_day(event)
        model = _text(event, "model")
        kind = _text(event, "kind")
        if not include_included_in_business and kind == INCLUDED_IN_BUSINESS:
            continue
        service_account_id = _optional_identifier(event, "serviceAccountId")
        user_email = _text(event, "userEmail")
        member_id = directory.by_email.get(user_email.casefold())
        account_id = service_account_id or member_id or user_email
        if service_account_id:
            principals[(USER_KIND_SERVICE_ACCOUNT, service_account_id)] = UserRecord(
                external_id=service_account_id,
                email=_optional_text(event, "serviceAccountName") or service_account_id,
                role="service_account",
                added_at=None,
                provider=PROVIDER,
                kind=USER_KIND_SERVICE_ACCOUNT,
            )
        elif member_id is None:
            principals[(USER_KIND_USER, user_email.casefold())] = UserRecord(
                external_id=user_email,
                email=user_email,
                role="event_user",
                added_at=None,
                provider=PROVIDER,
            )
        cents = charged_cents(event)
        amount = cents / Decimal("100")
        tokens = event.get("tokenUsage")
        if tokens is None:
            tokens = {}
        if not isinstance(tokens, dict):
            raise NormalizeError(f"tokenUsage is not an object: {tokens!r}")
        cost.append(
            CostLine(
                period_start=period_start,
                period_end=period_end,
                workspace_id=None,
                description=kind,
                cost_type=COST_TYPE,
                model=model,
                token_type=None,
                service_tier=kind,
                context_window=None,
                inference_geo=None,
                amount=amount,
                currency=CURRENCY,
                raw_amount_minor=str(event["chargedCents"]),
                provider=PROVIDER,
            )
        )
        usage.append(
            UsageLine(
                period_start=period_start,
                period_end=period_end,
                api_key_id=None,
                account_id=account_id,
                workspace_id=None,
                model=model,
                service_tier=kind,
                context_window=None,
                inference_geo=None,
                uncached_input_tokens=_count(tokens, "inputTokens"),
                cache_creation_5m_tokens=_count(tokens, "cacheWriteTokens"),
                cache_creation_1h_tokens=0,
                cache_read_tokens=_count(tokens, "cacheReadTokens"),
                output_tokens=_count(tokens, "outputTokens"),
                web_search_requests=0,
                provider=PROVIDER,
                request_count=1,
                amount=amount,
                currency=CURRENCY,
            )
        )
    return cost, usage, list(principals.values())


def page_amount(payload: dict[str, Any], window_start: datetime, window_end: datetime) -> Decimal:
    return sum(
        (
            charged_cents(event) / Decimal("100")
            for event in payload.get("usageEvents", [])
            if isinstance(event, dict)
            and window_start <= parse_event_time(event.get("timestamp")) < window_end
        ),
        Decimal("0"),
    )


def page_amount_with_settings(
    payload: dict[str, Any],
    request_params: dict[str, Any],
    window_start: datetime,
    window_end: datetime,
) -> Decimal:
    if "_costura_control_field" in request_params:
        return spend_control_total(payload, request_params)
    include = request_params.get("_costura_include_included_in_business", True) is True
    return sum(
        (
            charged_cents(event) / Decimal("100")
            for event in payload.get("usageEvents", [])
            if isinstance(event, dict)
            and (include or event.get("kind") != INCLUDED_IN_BUSINESS)
            and window_start <= parse_event_time(event.get("timestamp")) < window_end
        ),
        Decimal("0"),
    )


def member_limits(payload: dict[str, Any]) -> dict[str, Decimal | None]:
    limits: dict[str, Decimal | None] = {}
    for row in payload.get("teamMemberSpend", []):
        if not isinstance(row, dict):
            continue
        email = loose_text(row.get("email"))
        if email is None:
            continue
        limits[email.strip().lower()] = optional_decimal(
            row.get("effectivePerUserLimitDollars"), field="effectivePerUserLimitDollars"
        )
    return limits


def spend_control_total(payload: dict[str, Any], request_params: dict[str, Any]) -> Decimal:
    field = request_params.get("_costura_control_field")
    if field not in {"spendCents", "overallSpendCents"}:
        raise NormalizeError("Cursor spend control field is missing")
    total = Decimal("0")
    for row in payload.get("teamMemberSpend", []):
        if not isinstance(row, dict):
            continue
        if field == "overallSpendCents" and row.get(field) is None:
            cents = charged_cents(row, "spendCents") + charged_cents(row, "includedSpendCents")
        else:
            cents = charged_cents(row, field)
        total += cents / Decimal("100")
    return total


def seat_lines_from_daily_usage(
    rows: Iterable[dict[str, Any]],
    directory: UserDirectory,
    *,
    seat_price_usd: Decimal,
    effective_from: date,
) -> tuple[list[CostLine], list[UsageLine]]:
    cost_by_day: dict[date, Decimal] = {}
    usage: list[UsageLine] = []
    seen: set[tuple[date, str]] = set()
    for row in rows:
        raw_day = row.get("day")
        try:
            day = date.fromisoformat(raw_day) if isinstance(raw_day, str) else None
        except ValueError as exc:
            raise NormalizeError(f"day is not an ISO date: {raw_day!r}") from exc
        if day is None:
            raise NormalizeError(f"day is not an ISO date: {raw_day!r}")
        if day < effective_from:
            continue
        email = _text(row, "email")
        account_id = directory.resolve(email)
        identity = (day, account_id)
        if identity in seen:
            continue
        seen.add(identity)
        daily = seat_price_usd / Decimal(calendar.monthrange(day.year, day.month)[1])
        period_start = datetime.combine(day, time.min, tzinfo=UTC)
        period_end = period_start + timedelta(days=1)
        cost_by_day[day] = cost_by_day.get(day, Decimal("0")) + daily
        usage.append(
            UsageLine(
                period_start=period_start,
                period_end=period_end,
                api_key_id=None,
                account_id=account_id,
                workspace_id=None,
                model=SEAT_MODEL,
                service_tier=SEAT_COST_TYPE,
                context_window=None,
                inference_geo=None,
                uncached_input_tokens=0,
                cache_creation_5m_tokens=0,
                cache_creation_1h_tokens=0,
                cache_read_tokens=0,
                output_tokens=0,
                web_search_requests=0,
                provider=PROVIDER,
                request_count=0,
                amount=daily,
                currency=CURRENCY,
            )
        )
    cost = [
        CostLine(
            period_start=datetime.combine(day, time.min, tzinfo=UTC),
            period_end=datetime.combine(day, time.min, tzinfo=UTC) + timedelta(days=1),
            workspace_id=None,
            description="Cursor seats",
            cost_type=SEAT_COST_TYPE,
            model=None,
            token_type=None,
            service_tier=SEAT_COST_TYPE,
            context_window=None,
            inference_geo=None,
            amount=amount,
            currency=CURRENCY,
            raw_amount_minor=str(amount * 100),
            provider=PROVIDER,
        )
        for day, amount in sorted(cost_by_day.items())
    ]
    return cost, usage


__all__ = [
    "UserDirectory",
    "aggregate_cost_lines",
    "aggregate_usage_lines",
    "charged_cents",
    "event_day",
    "lines_from_events",
    "page_amount",
    "page_amount_with_settings",
    "parse_event_time",
    "seat_lines_from_daily_usage",
    "spend_control_total",
]
