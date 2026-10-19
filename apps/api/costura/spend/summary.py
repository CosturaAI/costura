"""Month headline figures for the dashboard: total, previous month, run rate, concentration,
cache share, allocation coverage and the share attributed to people. Every number is derived
from the same queries the reconciliation report uses, so the overview and reconciliation
pages never disagree.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura.models import SpendUsageLine
from costura.spend.allocation_check import AllocationCheck, allocation_check
from costura.spend.completeness import completeness
from costura.spend.duplicates import duplicate_accounts
from costura.spend.ledger import breakdown, costura_total, currency_totals, token_totals
from costura.spend.money import to_percent, within_cent
from costura.spend.provider_totals import provider_total_of_latest_run, seat_total
from costura.spend.scope import provider_clause
from costura.spend.usage import usage_report
from costura.spend.window import Window, comparison_window, previous_month, previous_window

CONCENTRATION_TOP = 5

ComparisonBasis = Literal["full_month", "month_to_date", "preceding_period"]


@dataclass
class Summary:
    month: str
    start: date
    end: date
    previous_start: date
    previous_end: date
    comparison_basis: ComparisonBasis
    currency: str | None
    total: Decimal
    previous_month: str
    previous_total: Decimal | None
    change_percent: Decimal | None
    days_in_month: int
    days_with_data: int
    last_day_with_data: date | None
    daily_average: Decimal | None
    is_current_month: bool
    projected_total: Decimal | None
    top_keys_share: Decimal | None
    top_key_count: int
    cache_read_share: Decimal | None
    tokens: dict[str, int]
    allocation: AllocationCheck | None
    provider_total: Decimal | None
    provider_matches: bool | None
    # Inference routed through OpenRouter on the organization's own provider keys, billed by
    # those providers; None when no usage line in scope reports it. Not part of `total`.
    byok_total: Decimal | None
    # Allocated spend whose `person` row is one e-mail; None until allocation runs.
    people_total: Decimal | None = None
    people_share: Decimal | None = None
    # The last day every account in scope has a succeeded cost sync for, and whether a later
    # cost sync failed (`spend.completeness`).
    complete_through: date | None = None
    data_stale: bool = False
    detection_through: date | None = None
    duplicate_accounts: list[str] = field(default_factory=list)
    # Costura's total minus the provider's own total for the same cost run (Cursor seats
    # left out, as in the reconciliation); None without a provider total.
    provider_difference: Decimal | None = None
    # Spend per currency when the scope bills in more than one; `total` then adds amounts in
    # different currencies and is not shown on its own.
    currency_totals: dict[str, Decimal] | None = None


def summary(
    session: Session,
    *,
    org_id: int,
    provider: str,
    month: str,
    today: date | None = None,
    window: Window | None = None,
) -> Summary:
    window = window or Window.for_month(month)
    whole_month = window == Window.for_month(month)
    today = today or datetime.now(UTC).date()
    total, currency = costura_total(session, org_id, provider, window)

    by_day = breakdown(session, org_id, provider, window, "day")
    days_with_data = sum(1 for row in by_day if row.amount != 0)
    last_day = None
    for row in by_day:
        if row.amount != 0:
            last_day = date.fromisoformat(row.label)
    days_in_month = len(by_day)
    is_current_month = window.start.date() <= today < window.end.date()

    prev_month = previous_month(month)
    done = completeness(session, org_id, provider)
    through, compared = _compared_through(
        by_day,
        window,
        total,
        last_day if whole_month and is_current_month else None,
        done.complete_through if whole_month else None,
    )
    before, comparison_basis, previous_total, change_percent = _comparison(
        session,
        org_id,
        provider,
        window,
        month,
        compared,
        through,
        partial=through is not None,
        empty=whole_month and is_current_month and last_day is None,
    )

    daily_average = None
    projected_total = None
    if last_day is not None:
        elapsed = (last_day - window.start.date()).days + 1
        daily_average = to_percent(total / elapsed)
        if is_current_month and whole_month:
            basis_day = through or last_day
            basis_days = (basis_day - window.start.date()).days + 1
            projected_total = to_percent(compared / basis_days * days_in_month)

    top_keys_share = None
    top_key_count = 0
    if total > 0:
        keys = usage_report(
            session, org_id=org_id, provider=provider, window=window, dimension="api_key"
        )
        if keys.allocated:
            real = [row for row in keys.rows if row.key is not None]
            top_key_count = len(real)
            top_amount = sum((row.amount or Decimal("0") for row in real[:CONCENTRATION_TOP]), 0)
            top_keys_share = to_percent(Decimal(top_amount) / total * 100)

    people_total = None
    people_share = None
    if total > 0:
        people = usage_report(
            session, org_id=org_id, provider=provider, window=window, dimension="person"
        )
        if people.allocated:
            people_total = sum(
                (
                    row.amount or Decimal("0")
                    for row in people.rows
                    if row.details.get("kind") == "person"
                ),
                Decimal("0"),
            )
            people_share = to_percent(people_total / total * 100)

    tokens = token_totals(session, org_id, provider, window)
    cache_read_share = _cache_read_share(tokens)

    _, provider_total = provider_total_of_latest_run(session, org_id, provider, window)
    provider_matches = None
    provider_difference = None
    if provider_total is not None:
        # Cursor seats are derived locally and excluded from the provider's cycle total,
        # the same subtraction the reconciliation report uses.
        seats = seat_total(session, org_id, provider, window)
        provider_difference = total - seats - provider_total
        provider_matches = within_cent(provider_difference)

    return Summary(
        month=month,
        start=window.start.date(),
        end=window.last_day,
        previous_start=before.start.date(),
        previous_end=before.last_day,
        comparison_basis=comparison_basis,
        currency=currency,
        total=total,
        previous_month=prev_month,
        previous_total=previous_total,
        change_percent=change_percent,
        days_in_month=days_in_month,
        days_with_data=days_with_data,
        last_day_with_data=last_day,
        daily_average=daily_average,
        is_current_month=is_current_month,
        projected_total=projected_total,
        top_keys_share=top_keys_share,
        top_key_count=top_key_count,
        cache_read_share=cache_read_share,
        tokens=tokens,
        provider_total=provider_total,
        provider_matches=provider_matches,
        allocation=allocation_check(session, org_id, provider, window),
        byok_total=byok_total(session, org_id, provider, window),
        people_total=people_total,
        people_share=people_share,
        complete_through=done.complete_through,
        data_stale=done.stale,
        detection_through=done.detection_through,
        duplicate_accounts=[
            f"{pair.first.label} and {pair.second.label}"
            for pair in duplicate_accounts(session, org_id, provider)
        ],
        provider_difference=provider_difference,
        currency_totals=_mixed_currencies(session, org_id, provider, window, currency, total),
    )


def _mixed_currencies(
    session: Session,
    org_id: int,
    provider: str,
    window: Window,
    currency: str | None,
    total: Decimal,
) -> dict[str, Decimal] | None:
    if currency is not None or total == 0:
        return None
    found = currency_totals(session, org_id, provider, window)
    return found if len(found) > 1 else None


def _compared_through(
    by_day: list,
    window: Window,
    total: Decimal,
    through: date | None,
    complete: date | None,
) -> tuple[date | None, Decimal]:
    """The last day a comparison covers and the spend through it. A month in progress stops
    at its last day with data; any month stops at `complete` when the cost syncs cover less
    than the whole month."""
    if complete is not None and window.start.date() <= complete < window.last_day:
        through = complete if through is None else min(through, complete)
    if through is None:
        return None, total
    compared = sum(
        (row.amount for row in by_day if date.fromisoformat(row.label) <= through),
        Decimal("0"),
    )
    return through, compared


def comparison_for(
    session: Session,
    *,
    org_id: int,
    provider: str,
    window: Window,
    month: str,
    today: date | None = None,
) -> Window:
    today = today or datetime.now(UTC).date()
    in_progress = (
        window == Window.for_month(month) and window.start.date() <= today < window.end.date()
    )
    if not in_progress:
        return previous_window(window, month)
    by_day = breakdown(session, org_id, provider, window, "day")
    through = max(
        (date.fromisoformat(row.label) for row in by_day if row.amount != 0),
        default=window.start.date(),
    )
    return comparison_window(window, month, through=through)


def _comparison(
    session: Session,
    org_id: int,
    provider: str,
    window: Window,
    month: str,
    total: Decimal,
    through: date | None,
    *,
    partial: bool,
    empty: bool,
) -> tuple[Window, ComparisonBasis, Decimal | None, Decimal | None]:
    """`total` covers the window through `through` when `partial`; the previous period is cut
    to the same days. `empty` is a month in progress with no data yet: no change."""
    cut = (through or window.start.date()) if partial or empty else None
    before = comparison_window(window, month, through=cut)
    prev_total, _ = costura_total(session, org_id, provider, before)
    previous_total = prev_total if prev_total != 0 else None
    change_percent = None
    if previous_total and not empty:
        change_percent = to_percent((total - previous_total) / previous_total * 100)
    return before, comparison_basis_of(window, month, before), previous_total, change_percent


def comparison_basis_of(window: Window, month: str, before: Window) -> ComparisonBasis:
    if before == previous_window(window, month):
        return "full_month" if window == Window.for_month(month) else "preceding_period"
    return "month_to_date"


def byok_total(session: Session, org_id: int, provider: str, window: Window) -> Decimal | None:
    """Sum of `byok_amount` over the usage lines in scope; None when every line is null."""
    value = session.scalar(
        select(func.sum(SpendUsageLine.byok_amount)).where(
            SpendUsageLine.organization_id == org_id,
            provider_clause(SpendUsageLine.provider, provider),
            SpendUsageLine.period_start >= window.start,
            SpendUsageLine.period_start < window.end,
        )
    )
    return None if value is None else Decimal(value)


def _cache_read_share(tokens: dict[str, int]) -> Decimal | None:
    """Cache reads as a share of every input token: uncached, cache writes and cache reads."""
    input_tokens = (
        tokens["uncached_input_tokens"]
        + tokens["cache_creation_5m_tokens"]
        + tokens["cache_creation_1h_tokens"]
        + tokens["cache_read_tokens"]
    )
    if not input_tokens:
        return None
    return to_percent(Decimal(tokens["cache_read_tokens"]) / input_tokens * 100)
