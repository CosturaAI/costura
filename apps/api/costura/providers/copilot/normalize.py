"""Normalize GitHub billing usage rows to daily cost lines and per-user usage lines.

The organization usage report prices every Copilot SKU for a day, seats included; the AI
credit report prices one user's credits. `netAmount` is what GitHub bills after the included
credit pool and discounts, so it is the ledger amount; `grossAmount` and the credit quantity
are kept on the line for the reader.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from costura.providers.copilot import PROVIDER
from costura.providers.lines import (
    CostLine,
    NormalizeError,
    UsageLine,
    aggregate_cost_lines,
    aggregate_usage_lines,
)

CURRENCY = "USD"
PRODUCT = "copilot"
# Every Copilot cost line is `tokens`: direct allocation attributes only that cost type, and
# both seats and credits have per-user usage lines to attribute to. The SKU kinds below pick
# the synthetic model that joins a cost line to its usage lines.
COST_TYPE = "tokens"
KIND_CREDITS = "credits"
KIND_SEAT = "seat"
SEAT_MODEL = "__copilot_seat__"
CREDITS_MODEL = "__copilot_credits__"
UNATTRIBUTED_LOGIN = "__copilot_unattributed__"


@dataclass(frozen=True)
class DayWindow:
    day: date

    @property
    def start(self) -> datetime:
        return datetime.combine(self.day, time.min, tzinfo=UTC)

    @property
    def end(self) -> datetime:
        return self.start + timedelta(days=1)


def day_of(request_params: dict[str, Any]) -> DayWindow:
    raw = request_params.get("_costura_day")
    if not isinstance(raw, str):
        raise NormalizeError("page is missing its day")
    try:
        return DayWindow(date.fromisoformat(raw))
    except ValueError as exc:
        raise NormalizeError(f"page day is not an ISO date: {raw!r}") from exc


def amount(row: dict[str, Any], field: str) -> Decimal:
    value = row.get(field)
    if value is None:
        return Decimal("0")
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise NormalizeError(f"{field} is not a number: {value!r}")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise NormalizeError(f"{field} is not a number: {value!r}") from exc
    if not parsed.is_finite() or parsed < 0:
        raise NormalizeError(f"{field} is not a non-negative finite number: {value!r}")
    return parsed


def _text(row: dict[str, Any], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value:
        raise NormalizeError(f"{field} is missing")
    return value


def is_copilot(row: dict[str, Any]) -> bool:
    product = row.get("product")
    return isinstance(product, str) and product.strip().lower() == PRODUCT


def sku_kind(sku: str) -> str:
    """Seat SKUs (`copilot_for_business`, `copilot_enterprise`) against credit SKUs
    (`copilot_ai_credit`, "Copilot AI Credits", premium requests)."""
    lowered = sku.lower()
    if "credit" in lowered or "request" in lowered:
        return KIND_CREDITS
    return KIND_SEAT


def model_of(sku: str) -> str:
    return SEAT_MODEL if sku_kind(sku) == KIND_SEAT else CREDITS_MODEL


def cost_lines_from_usage(rows: Iterable[dict[str, Any]], window: DayWindow) -> list[CostLine]:
    """Copilot rows of one day of the organization usage report, one cost line per SKU."""
    lines: list[CostLine] = []
    for row in rows:
        if not is_copilot(row):
            continue
        sku = _text(row, "sku")
        net = amount(row, "netAmount")
        lines.append(
            CostLine(
                period_start=window.start,
                period_end=window.end,
                workspace_id=None,
                description=sku,
                cost_type=COST_TYPE,
                model=model_of(sku),
                token_type=None,
                service_tier=sku,
                context_window=None,
                inference_geo=None,
                amount=net,
                currency=CURRENCY,
                raw_amount_minor=str(net * 100),
                list_amount=amount(row, "grossAmount"),
                provider=PROVIDER,
            )
        )
    return aggregate_cost_lines(lines)


def credit_usage_lines(
    rows: Iterable[dict[str, Any]], window: DayWindow, login: str
) -> list[UsageLine]:
    """One user's AI credit rows of one day: one usage line per SKU and model, priced at the
    net amount GitHub bills, with the gross credits as the request count."""
    lines: list[UsageLine] = []
    for row in rows:
        if not is_copilot(row):
            continue
        sku = _text(row, "sku")
        gross_quantity = amount(row, "grossQuantity")
        lines.append(
            UsageLine(
                period_start=window.start,
                period_end=window.end,
                api_key_id=None,
                account_id=login,
                workspace_id=None,
                model=CREDITS_MODEL,
                service_tier=sku,
                context_window=None,
                inference_geo=None,
                uncached_input_tokens=0,
                cache_creation_5m_tokens=0,
                cache_creation_1h_tokens=0,
                cache_read_tokens=0,
                output_tokens=0,
                web_search_requests=0,
                provider=PROVIDER,
                request_count=int(gross_quantity),
                amount=amount(row, "netAmount"),
                currency=CURRENCY,
            )
        )
    return aggregate_usage_lines(lines)


def seat_usage_lines(
    seat_cost: Decimal, window: DayWindow, logins: list[str], sku: str = "copilot_seat"
) -> list[UsageLine]:
    """The day's billed seat amount, split evenly across the seats assigned that day. With no
    seat holder known the amount stays on one unattributed line so the day still adds up."""
    if seat_cost == 0:
        return []
    holders = sorted(set(logins)) or [UNATTRIBUTED_LOGIN]
    share = seat_cost / Decimal(len(holders))
    return [
        UsageLine(
            period_start=window.start,
            period_end=window.end,
            api_key_id=None,
            account_id=login,
            workspace_id=None,
            model=SEAT_MODEL,
            service_tier=sku,
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
            amount=share,
            currency=CURRENCY,
        )
        for login in holders
    ]


def page_amount(payload: dict[str, Any], window_start: datetime, window_end: datetime) -> Decimal:
    """Net Copilot amount of one usage page; the page's day is inside the window or not."""
    rows = payload.get("usageItems", [])
    if not isinstance(rows, list):
        return Decimal("0")
    total = Decimal("0")
    for row in rows:
        if not isinstance(row, dict) or not is_copilot(row):
            continue
        raw_day = row.get("date")
        if isinstance(raw_day, str):
            try:
                day = datetime.combine(date.fromisoformat(raw_day[:10]), time.min, tzinfo=UTC)
            except ValueError:
                continue
            if not window_start <= day < window_end:
                continue
        total += amount(row, "netAmount")
    return total


def page_amount_with_params(
    payload: dict[str, Any],
    request_params: dict[str, Any],
    window_start: datetime,
    window_end: datetime,
) -> Decimal:
    """Same as `page_amount`, using the day the page was requested for when rows carry no
    `date` (the AI credit report)."""
    raw = request_params.get("_costura_day")
    if isinstance(raw, str):
        try:
            day = DayWindow(date.fromisoformat(raw)).start
        except ValueError:
            day = None
        if day is not None and not window_start <= day < window_end:
            return Decimal("0")
    return page_amount(payload, window_start, window_end)


__all__ = [
    "COST_TYPE",
    "CREDITS_MODEL",
    "KIND_CREDITS",
    "KIND_SEAT",
    "SEAT_MODEL",
    "UNATTRIBUTED_LOGIN",
    "DayWindow",
    "amount",
    "cost_lines_from_usage",
    "credit_usage_lines",
    "day_of",
    "is_copilot",
    "model_of",
    "page_amount",
    "page_amount_with_params",
    "seat_usage_lines",
    "sku_kind",
]
