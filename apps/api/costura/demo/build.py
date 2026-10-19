"""Fill one organization with the sample dataset by running the real sync cycle against the
synthetic clients.

The timeline is the one a team connecting its providers a few days ago would have: a
backfill cycle over every month, then one scheduled cycle a day (`DAILY_CYCLES` and the
latest one, which runs now). Each earlier cycle's rows are moved back to the day it stands for,
so Sync, Runs and freshness read like a daily schedule. A build for an earlier `today` (a
reproducible test build) dates every cycle on its own day, the latest one included. The
manifest's failures make one cycle fail and one step recover on retry. Budgets come last,
sized against the month so far so each
lands in its intended state."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import cast

from sqlalchemy import DateTime, Table, func, select, update
from sqlalchemy.orm import Session

from costura import accounts
from costura.config import get_settings
from costura.demo.clients import CLIENTS
from costura.demo.manifest import (
    ACCOUNTS,
    BUDGETS,
    DAILY_CYCLES,
    DATASET_VERSION,
    FAILURES,
    MONTHS,
    Account,
    Budget,
)
from costura.models import SchedulerRun
from costura.models.organization import Organization
from costura.orgs import RESET_TABLES
from costura.providers.spec import AccountInfo
from costura.spend.budgets import evaluate_budgets, set_budget
from costura.spend.daily import daily_amounts
from costura.spend.ledger import costura_total
from costura.spend.projection import stored_projected_total, stored_projections
from costura.spend.scope import ALL
from costura.spend.window import Window, shift_month
from costura.sync_cycle import sync_all

LEASE_OWNER = "costura-demo"
# Timestamp columns a cycle writes as "now"; provider dates (`created_at` of a key) are older
# than the cycle and are left alone by the shift.
SHIFTED_COLUMNS = frozenset(
    {
        "started_at",
        "finished_at",
        "fetched_at",
        "first_seen_at",
        "last_seen_at",
        "missing_since",
        "data_refreshed_at",
        "created_at",
        "updated_at",
        "detected_at",
        "computed_at",
        "evaluated_at",
        "triggered_at",
        "heartbeat_at",
    }
)


@dataclass(frozen=True)
class Span:
    start: date
    end: date

    @property
    def months(self) -> list[str]:
        """Every month of the span, the oldest first: `sync_all` allocates and detects in
        the order given, and a month's detection reads the allocated months before it."""
        found: list[str] = []
        cursor = self.start
        while cursor < self.end:
            found.append(cursor.strftime("%Y-%m"))
            cursor = shift_month(cursor.replace(day=1), 1)
        return found


def span_for(today: date, months: int = MONTHS) -> Span:
    """`[first day of the month months-1 before today's, today)`."""
    return Span(shift_month(today.replace(day=1), -(months - 1)), today)


def build_dataset(
    session: Session,
    org: Organization,
    *,
    today: date,
    version: int = DATASET_VERSION,
    months: int = MONTHS,
    daily_cycles: int = DAILY_CYCLES,
) -> Span:
    """`months` and `daily_cycles` shrink the build for tests; the published sample uses the
    defaults."""
    span = span_for(today, months)
    ids = {
        (spec.provider, spec.key): _create_account(session, org.id, spec, span) for spec in ACCOUNTS
    }
    session.commit()
    now = datetime.now(UTC)
    past = today < now.date()
    anchor = datetime.combine(today, time(6), UTC) if past else now
    for days_ago in range(daily_cycles, -1, -1):
        as_of = today - timedelta(days=days_ago)
        backfill = days_ago == daily_cycles
        cycle_months = span.months if backfill else _recent_months(as_of, span)
        started = _clock(session)
        for spec in ACCOUNTS:
            _cycle(
                session,
                org.id,
                spec,
                ids[(spec.provider, spec.key)],
                as_of=as_of,
                months=cycle_months,
                version=version,
                trigger="connect" if backfill else "scheduler",
                failures={} if backfill else _failures(spec, days_ago),
            )
        if days_ago or past:
            _shift(session, org.id, since=started, by=(anchor - timedelta(days=days_ago)) - started)
    started = _clock(session)
    _budgets(session, org.id, today)
    if past:
        _shift(session, org.id, since=started, by=anchor - started)
    org.onboarding_dismissed_at = anchor - timedelta(days=daily_cycles)
    session.commit()
    return span


def _clock(session: Session) -> datetime:
    """The earlier of the database and process clocks: rows take timestamps from both, and a
    cycle's rows must all sort after its start."""
    database = session.scalar(select(func.clock_timestamp()))
    session.commit()
    process = datetime.now(UTC)
    return min(process, database) if database is not None else process


def _create_account(session: Session, org_id: int, spec: Account, span: Span) -> int:
    account = accounts.create_account(
        session,
        org_id,
        spec.provider,
        label=spec.label,
        info=AccountInfo(external_id=spec.external_id, name=spec.label),
    )
    connected = span.start - timedelta(days=31)
    account.created_at = datetime(connected.year, connected.month, connected.day, tzinfo=UTC)
    account.settings_effective_from = connected
    if spec.settings:
        account.settings = dict(spec.settings)
    session.flush()
    return account.id


def _recent_months(as_of: date, span: Span) -> list[str]:
    current = as_of.replace(day=1)
    previous = shift_month(current, -1)
    return [m.strftime("%Y-%m") for m in (previous, current) if m >= span.start.replace(day=1)]


def _failures(spec: Account, days_ago: int) -> dict[str, int]:
    return {
        failure.call: failure.attempts
        for failure in FAILURES
        if failure.provider == spec.provider
        and failure.account == spec.key
        and failure.days_ago == days_ago
    }


def _cycle(
    session: Session,
    org_id: int,
    spec: Account,
    account_id: int,
    *,
    as_of: date,
    months: list[str],
    version: int,
    trigger: str,
    failures: dict[str, int],
) -> None:
    now = datetime.now(UTC)
    run = SchedulerRun(
        organization_id=org_id,
        provider=spec.provider,
        provider_account_id=account_id,
        trigger=trigger,
        status="running",
        steps=[],
        attempt_count=1,
        lease_owner=LEASE_OWNER,
        lease_expires_at=now + timedelta(hours=1),
        heartbeat_at=now,
    )
    session.add(run)
    session.commit()
    client = CLIENTS[spec.provider](spec, version, as_of, failures=failures)
    sync_all(
        session,
        get_settings(),
        org_id,
        provider=spec.provider,
        account_id=account_id,
        months=months,
        sleep=lambda _seconds: None,
        run=run,
        client=client,
        today=as_of,
    )
    run.lease_owner = None
    run.lease_expires_at = None
    session.commit()


def _shift(session: Session, org_id: int, *, since: datetime, by: timedelta) -> None:
    """Move every timestamp a cycle wrote back to the day the cycle stands for."""
    models = (*RESET_TABLES, SchedulerRun)
    for model in models:
        table = cast(Table, model.__table__)
        org_column = table.c.organization_id
        for column in table.columns:
            if column.name not in SHIFTED_COLUMNS or not isinstance(column.type, DateTime):
                continue
            session.execute(
                update(table)
                .where(org_column == org_id, column >= since)
                .values({column.name: column + by})
            )
    session.commit()


def _budgets(session: Session, org_id: int, today: date) -> None:
    current = Window.for_month(today.strftime("%Y-%m"))
    month = today.strftime("%Y-%m")
    for budget in BUDGETS:
        series = daily_amounts(
            session,
            org_id,
            budget.provider,
            budget.scope_kind,
            current.start.date(),
            current.end.date(),
        ).get(budget.scope_id, {})
        spent = sum(series.values(), Decimal("0"))
        projected = (
            stored_projected_total(
                session, org_id, budget.provider, month, budget.scope_kind, budget.scope_id
            )
            or spent
        )
        set_budget(
            session,
            org_id,
            budget.provider,
            budget.scope_kind,
            budget.scope_id,
            _amount(budget, spent, projected),
            None,
        )
    spent_all, _ = costura_total(session, org_id, ALL, current)
    projected_all = sum(
        (
            Decimal(row.projected_total)
            for row in stored_projections(session, org_id, ALL, month, "org")
        ),
        Decimal("0"),
    )
    set_budget(
        session,
        org_id,
        ALL,
        "org",
        "__org__",
        _amount(
            Budget(provider=ALL, scope_kind="org", scope_id="__org__", state="near_limit"),
            spent_all,
            projected_all or spent_all,
        ),
        None,
    )
    previous = Window.for_month(shift_month(today.replace(day=1), -1).strftime("%Y-%m"))
    for provider in [*sorted({b.provider for b in BUDGETS}), ALL]:
        for window in (previous, current):
            evaluate_budgets(session, org_id, provider, window, today=today)


def _amount(budget: Budget, spent: Decimal, projected: Decimal) -> Decimal:
    """A round amount that puts the month in the budget's intended state: healthy well
    above the projection, near the limit just above it, exceeded below what is spent."""
    if budget.state == "healthy":
        return _round(projected * Decimal("1.8"), ROUND_CEILING)
    if budget.state == "near_limit":
        return _round(projected * Decimal("1.05"), ROUND_CEILING, step=Decimal("10"))
    return max(Decimal("10"), _round(spent * Decimal("0.85"), ROUND_FLOOR, step=Decimal("10")))


def _round(value: Decimal, rounding: str, *, step: Decimal = Decimal("100")) -> Decimal:
    rounded = (value / step).to_integral_value(rounding=rounding) * step
    return max(step, rounded)
