"""Fetch GitHub's billing usage for Copilot and upsert daily cost and per-user usage.

`cost` reads the organization usage report one day at a time: every Copilot SKU, seats and
credits, priced as billed. `users` reads each seat holder's AI credits for each day, then
splits the day's seat cost evenly across the seat holders, so the attribution adds up to the
cost without a configured seat price.
"""

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from costura.models import ProviderUser, SpendCostLine, SpendUsageLine
from costura.providers.copilot import PROVIDER
from costura.providers.copilot.client import FetchedPage, GitHubBillingClient, served_from
from costura.providers.copilot.normalize import (
    SEAT_MODEL,
    DayWindow,
    aggregate_usage_lines,
    cost_lines_from_usage,
    credit_usage_lines,
    day_of,
    page_amount,
    page_amount_with_params,
    seat_usage_lines,
)
from costura.providers.lines import CostLine, UsageLine
from costura.providers.records import USER_KIND_USER
from costura.providers.runs import SyncSummary, Target, run_report
from costura.providers.spend_lines import upsert_cost_lines, upsert_usage_lines

ENDPOINT_COST = "billing_usage"
ENDPOINT_USERS = "ai_credit_usage"
# No endpoint reports a control total apart from the usage report itself, so no step writes
# this run and reconcile reports the provider total as pending.
ENDPOINT_COST_TOTAL = "billing_usage_total"


def seat_history(session: Session, target: Target) -> list[tuple[str, date | None, date | None]]:
    """Every login that held a seat: the day it was assigned (when GitHub reported it) and
    the day it went missing from the inventory (None while it is still assigned)."""
    rows = session.execute(
        select(ProviderUser.external_id, ProviderUser.added_at, ProviderUser.missing_since).where(
            ProviderUser.organization_id == target.org_id,
            ProviderUser.provider_account_id == target.account_id,
            ProviderUser.provider == PROVIDER,
            ProviderUser.kind == USER_KIND_USER,
        )
    )
    return [
        (login, added.date() if added else None, missing.date() if missing else None)
        for login, added, missing in rows
    ]


def holders_on(history: list[tuple[str, date | None, date | None]], day: date) -> list[str]:
    """The logins whose seat covered `day`: assigned on or before it, not gone by then."""
    return sorted(
        login
        for login, added, missing in history
        if (added is None or added <= day) and (missing is None or missing > day)
    )


def seat_holders(session: Session, target: Target) -> list[str]:
    """Logins with a seat in the latest inventory snapshot."""
    return sorted(
        session.scalars(
            select(ProviderUser.external_id).where(
                ProviderUser.organization_id == target.org_id,
                ProviderUser.provider_account_id == target.account_id,
                ProviderUser.provider == PROVIDER,
                ProviderUser.kind == USER_KIND_USER,
                ProviderUser.missing_since.is_(None),
            )
        )
    )


def run_cost_sync(
    session: Session,
    target: Target,
    client: GitHubBillingClient,
    start: datetime,
    end: datetime,
) -> SyncSummary:
    start = max(start, served_from())
    return run_report(
        session,
        target,
        PROVIDER,
        endpoint=ENDPOINT_COST,
        pages=lambda: client.usage_pages(start, end),
        start=start,
        end=end,
        normalize=lambda page: cost_lines_from_usage(page.results, day_of(page.request_params)),
        aggregate=lambda lines: lines,
        upsert=lambda session, target, lines, run_id: _replace_cost(
            session, target, lines, run_id, start, end
        ),
    )


def run_user_sync(
    session: Session,
    target: Target,
    client: GitHubBillingClient,
    start: datetime,
    end: datetime,
) -> SyncSummary:
    start = max(start, served_from())
    logins = seat_holders(session, target)

    def normalize(page: FetchedPage) -> list[UsageLine]:
        login = str(page.request_params.get("_costura_login") or "")
        return credit_usage_lines(page.results, day_of(page.request_params), login)

    return run_report(
        session,
        target,
        PROVIDER,
        endpoint=ENDPOINT_USERS,
        pages=lambda: client.ai_credit_pages(start, end, logins),
        start=start,
        end=end,
        normalize=normalize,
        aggregate=aggregate_usage_lines,
        upsert=lambda session, target, lines, run_id: _replace_usage(
            session, target, lines, run_id, start, end
        ),
    )


def _replace_cost(
    session: Session,
    target: Target,
    lines: Sequence[CostLine],
    run_id: int,
    start: datetime,
    end: datetime,
) -> int:
    session.execute(
        delete(SpendCostLine).where(
            SpendCostLine.organization_id == target.org_id,
            SpendCostLine.provider_account_id == target.account_id,
            SpendCostLine.provider == PROVIDER,
            SpendCostLine.period_start >= start,
            SpendCostLine.period_start < end,
        )
    )
    return upsert_cost_lines(session, target, list(lines), run_id)


def _replace_usage(
    session: Session,
    target: Target,
    lines: Sequence[UsageLine],
    run_id: int,
    start: datetime,
    end: datetime,
) -> int:
    session.execute(
        delete(SpendUsageLine).where(
            SpendUsageLine.organization_id == target.org_id,
            SpendUsageLine.provider_account_id == target.account_id,
            SpendUsageLine.provider == PROVIDER,
            SpendUsageLine.period_start >= start,
            SpendUsageLine.period_start < end,
        )
    )
    history = seat_history(session, target)
    seat_lines: list[UsageLine] = []
    for period_start, amount, sku in session.execute(
        select(SpendCostLine.period_start, SpendCostLine.amount, SpendCostLine.description).where(
            SpendCostLine.organization_id == target.org_id,
            SpendCostLine.provider_account_id == target.account_id,
            SpendCostLine.provider == PROVIDER,
            SpendCostLine.model == SEAT_MODEL,
            SpendCostLine.period_start >= start,
            SpendCostLine.period_start < end,
        )
    ):
        window = DayWindow(period_start.date())
        holders = holders_on(history, period_start.date())
        seat_lines.extend(seat_usage_lines(Decimal(amount), window, holders, sku))
    return upsert_usage_lines(session, target, aggregate_usage_lines([*lines, *seat_lines]), run_id)


__all__ = [
    "ENDPOINT_COST",
    "ENDPOINT_COST_TOTAL",
    "ENDPOINT_USERS",
    "page_amount",
    "page_amount_with_params",
    "run_cost_sync",
    "run_user_sync",
    "seat_holders",
]
