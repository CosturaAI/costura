"""Fetch Cursor filtered usage events and upsert daily cost and per-user usage."""

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from costura import account_settings
from costura.models import ProviderAccount, ProviderUser, SpendCostLine, SpendUsageLine
from costura.providers.cursor import PROVIDER
from costura.providers.cursor.client import CursorAdminClient, FetchedPage
from costura.providers.cursor.normalize import (
    ABSENT_IDENTIFIER_VALUES,
    SEAT_COST_TYPE,
    UserDirectory,
    aggregate_cost_lines,
    aggregate_usage_lines,
    lines_from_events,
    member_limits,
    page_amount,
    page_amount_with_settings,
    seat_lines_from_daily_usage,
    spend_control_total,
)
from costura.providers.lines import CostLine, UsageLine
from costura.providers.records import UserRecord
from costura.providers.runs import SyncSummary, Target, run_report, write_records
from costura.providers.spend_lines import upsert_cost_lines, upsert_usage_lines

ENDPOINT_USAGE = "filtered_usage_events"
ENDPOINT_COST = ENDPOINT_USAGE
# Reserved for the provider-published billing-cycle total added with Cursor seat settings.
# This phase intentionally creates no run for it, so reconcile reports no provider total.
ENDPOINT_COST_TOTAL = "spend"
ENDPOINT_SEATS = "daily_usage_seats"

type Line = CostLine | UsageLine | UserRecord


def run_usage_sync(
    session: Session,
    target: Target,
    client: CursorAdminClient,
    start: datetime,
    end: datetime,
) -> SyncSummary:

    directory = UserDirectory.load(session, target.account_id)
    account = session.get(ProviderAccount, target.account_id)
    if account is None:
        raise LookupError(f"Cursor account {target.account_id} not found")
    configured = account_settings.cursor_settings(account)

    def normalize(page: FetchedPage) -> list[Line]:
        cost, usage, service_accounts = lines_from_events(
            page.results,
            directory,
            include_included_in_business=configured.include_included_in_business,
        )
        return [*cost, *usage, *service_accounts]

    return run_report(
        session,
        target,
        PROVIDER,
        endpoint=ENDPOINT_USAGE,
        pages=lambda: client.filtered_usage_events_pages(
            start,
            end,
            include_included_in_business=configured.include_included_in_business,
        ),
        start=start,
        end=end,
        normalize=normalize,
        aggregate=_aggregate,
        upsert=lambda session, target, lines, run_id: _replace_window(
            session, target, lines, run_id, start, end, "tokens"
        ),
    )


run_cost_sync = run_usage_sync


def run_seat_sync(
    session: Session,
    target: Target,
    client: CursorAdminClient,
    start: datetime,
    end: datetime,
) -> SyncSummary:

    directory = UserDirectory.load(session, target.account_id)
    account = session.get(ProviderAccount, target.account_id)
    if account is None:
        raise LookupError(f"Cursor account {target.account_id} not found")
    configured = account_settings.cursor_settings(account)

    def normalize(page: FetchedPage) -> list[Line]:
        cost, usage = seat_lines_from_daily_usage(
            page.results,
            directory,
            seat_price_usd=configured.seat_price_usd,
            effective_from=max(configured.effective_from, account.created_at.date()),
        )
        return [*cost, *usage]

    return run_report(
        session,
        target,
        PROVIDER,
        endpoint=ENDPOINT_SEATS,
        pages=lambda: client.daily_usage_pages(start, end),
        start=start,
        end=end,
        normalize=normalize,
        aggregate=_aggregate,
        upsert=lambda session, target, lines, run_id: _replace_window(
            session, target, lines, run_id, start, end, "seat"
        ),
    )


def run_cost_total_sync(
    session: Session,
    target: Target,
    client: CursorAdminClient,
    _start: datetime,
    _end: datetime,
) -> SyncSummary:

    account = session.get(ProviderAccount, target.account_id)
    if account is None:
        raise LookupError(f"Cursor account {target.account_id} not found")
    configured = account_settings.cursor_settings(account)
    pages = list(
        client.spend_pages(include_included_in_business=configured.include_included_in_business)
    )
    if not pages:
        raise ValueError("Cursor spend response returned no pages")
    cycle_value = pages[0].payload.get("subscriptionCycleStart")
    if isinstance(cycle_value, bool) or not isinstance(cycle_value, (int, float)):
        raise ValueError("Cursor spend response lacks subscriptionCycleStart")
    cycle_start = datetime.fromtimestamp(cycle_value / 1000, tz=UTC)
    now = datetime.now(UTC)
    summary = run_report(
        session,
        target,
        PROVIDER,
        endpoint=ENDPOINT_COST_TOTAL,
        pages=lambda: iter(pages),
        start=cycle_start,
        end=now,
        normalize=lambda fetched: [spend_control_total(fetched.payload, fetched.request_params)],
        aggregate=list,
        upsert=lambda _session, _target, _amounts, _run_id: 0,
    )
    _apply_member_limits(session, target, pages)
    return summary


def _apply_member_limits(session: Session, target: Target, pages: list[FetchedPage]) -> None:
    limits: dict[str, Decimal | None] = {}
    for page in pages:
        limits.update(member_limits(page.payload))
    users = session.scalars(
        select(ProviderUser).where(
            ProviderUser.organization_id == target.org_id,
            ProviderUser.provider_account_id == target.account_id,
            ProviderUser.provider == PROVIDER,
        )
    )
    for user in users:
        email = user.email.strip().lower()
        if email in limits:
            user.limit_reported = True
            user.spend_limit = limits[email]
    session.commit()


def _aggregate(lines: list[Line]) -> list[Line]:
    cost = aggregate_cost_lines(line for line in lines if isinstance(line, CostLine))
    usage = aggregate_usage_lines(line for line in lines if isinstance(line, UsageLine))
    users = {line.external_id: line for line in lines if isinstance(line, UserRecord)}.values()
    return [*cost, *usage, *users]


def _upsert(session: Session, target: Target, lines: Sequence[Line], run_id: int) -> int:
    cost = [line for line in lines if isinstance(line, CostLine)]
    usage = [line for line in lines if isinstance(line, UsageLine)]
    users = [line for line in lines if isinstance(line, UserRecord)]
    return (
        upsert_cost_lines(session, target, cost, run_id)
        + upsert_usage_lines(session, target, usage, run_id)
        + write_records(
            session,
            ProviderUser,
            users,
            target,
            run_id,
            constraint="uq_provider_users_external_id",
            replace_columns=("email", "role", "added_at", "kind"),
        )
    )


def _replace_window(
    session: Session,
    target: Target,
    lines: Sequence[Line],
    run_id: int,
    start: datetime,
    end: datetime,
    cost_type: str,
) -> int:
    session.execute(
        delete(ProviderUser).where(
            ProviderUser.organization_id == target.org_id,
            ProviderUser.provider_account_id == target.account_id,
            ProviderUser.provider == PROVIDER,
            ProviderUser.external_id.in_(ABSENT_IDENTIFIER_VALUES),
        )
    )
    session.execute(
        delete(SpendCostLine).where(
            SpendCostLine.organization_id == target.org_id,
            SpendCostLine.provider_account_id == target.account_id,
            SpendCostLine.provider == PROVIDER,
            SpendCostLine.period_start >= start,
            SpendCostLine.period_start < end,
            SpendCostLine.cost_type == cost_type,
        )
    )
    usage_tier = (
        SpendUsageLine.service_tier == SEAT_COST_TYPE
        if cost_type == SEAT_COST_TYPE
        else SpendUsageLine.service_tier != SEAT_COST_TYPE
    )
    session.execute(
        delete(SpendUsageLine).where(
            SpendUsageLine.organization_id == target.org_id,
            SpendUsageLine.provider_account_id == target.account_id,
            SpendUsageLine.provider == PROVIDER,
            SpendUsageLine.period_start >= start,
            SpendUsageLine.period_start < end,
            usage_tier,
        )
    )
    return _upsert(session, target, lines, run_id)


__all__ = [
    "ENDPOINT_COST",
    "ENDPOINT_COST_TOTAL",
    "ENDPOINT_SEATS",
    "ENDPOINT_USAGE",
    "page_amount",
    "page_amount_with_settings",
    "run_cost_sync",
    "run_cost_total_sync",
    "run_seat_sync",
    "run_usage_sync",
]
