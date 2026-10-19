"""Budgets per organization total, workspace or person: compare the month's spend and
projection with the amount and raise alerts the first time a threshold is crossed. A person
budget sums one e-mail across every provider and has no projection. A day or week budget
compares each UTC day or ISO week with the amount, raises its alerts once per period, and
reads the period that holds today (the last one of a closed month).

Nothing here enforces a limit; the provider console holds the real cap and this module
tells the reader how close the month is to the number configured there.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import and_, delete, false, func, or_, select
from sqlalchemy.orm import Session

from costura.errors import DomainError
from costura.models import ProviderSyncRun, SpendBudget, SpendBudgetAlert, SpendProjection
from costura.models.budget import (
    BUDGET_PERIODS,
    BUDGET_SCOPES,
    DEFAULT_THRESHOLDS,
    PERSON_BUDGET_PROVIDER,
    BudgetPeriod,
)
from costura.models.intelligence import ORG_SERIES_ID
from costura.providers.http import stored_exception_text
from costura.spend.daily import Series, daily_amounts
from costura.spend.ledger import costura_total
from costura.spend.money import STORAGE_EXPONENT, to_percent
from costura.spend.scope import ALL, is_all, provider_clause, scope_providers
from costura.spend.usage import usage_report
from costura.spend.window import Window

BUDGET_ENDPOINT = "budget_evaluation"
TEAM_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
MIN_THRESHOLD = 1
MAX_THRESHOLD = 200


class InvalidBudget(ValueError, DomainError):
    status = 422
    code = "invalid_budget"

    pass


def normalize_thresholds(values: list[int] | None) -> list[int]:
    """Sorted unique percentages within 1..200; the default list when none are given."""
    if values is None:
        return list(DEFAULT_THRESHOLDS)
    if not values:
        raise InvalidBudget("at least one threshold is required")
    cleaned = sorted({int(v) for v in values})
    for value in cleaned:
        if value < MIN_THRESHOLD or value > MAX_THRESHOLD:
            raise InvalidBudget(f"thresholds must be between {MIN_THRESHOLD} and {MAX_THRESHOLD}")
    return cleaned


def validate_scope(scope_kind: str, scope_id: str) -> None:
    if scope_kind not in BUDGET_SCOPES:
        raise InvalidBudget(f"scope_kind must be one of {', '.join(BUDGET_SCOPES)}")
    if scope_kind == "org" and scope_id != ORG_SERIES_ID:
        raise InvalidBudget(f"an org budget uses scope_id {ORG_SERIES_ID}")
    if not scope_id:
        raise InvalidBudget("scope_id is required")
    if scope_kind == "person" and "@" not in scope_id:
        raise InvalidBudget("a person budget uses the person's e-mail as scope_id")
    if scope_kind == "team" and not TEAM_SLUG.match(scope_id):
        raise InvalidBudget("a team budget uses the team slug as scope_id")


def set_budget(
    session: Session,
    org_id: int,
    provider: str,
    scope_kind: str,
    scope_id: str,
    amount: Decimal,
    thresholds: list[int] | None,
    *,
    currency: str = "USD",
    period: BudgetPeriod = "month",
) -> SpendBudget:
    """Create or update the budget of one scope. Existing alerts stay: they record what was
    crossed at the time, against the amount in force then."""
    validate_scope(scope_kind, scope_id)
    if period not in BUDGET_PERIODS:
        raise InvalidBudget(f"period must be one of {', '.join(BUDGET_PERIODS)}")
    if period != "month" and scope_kind in ("person", "team"):
        raise InvalidBudget(f"a {scope_kind} budget is monthly")
    if scope_kind in ("person", "team") and provider != PERSON_BUDGET_PROVIDER:
        raise InvalidBudget(f"a {scope_kind} budget spans every provider; set it under all")
    if scope_kind == "workspace" and provider == PERSON_BUDGET_PROVIDER:
        raise InvalidBudget("a workspace budget belongs to one provider")
    if scope_kind == "person":
        scope_id = scope_id.strip().lower()
    if amount <= 0:
        raise InvalidBudget("amount must be positive")
    row = _budget(session, org_id, provider, scope_kind, scope_id)
    if row is None:
        row = SpendBudget(
            organization_id=org_id,
            provider=provider,
            scope_kind=scope_kind,
            scope_id=scope_id,
        )
        session.add(row)
    row.amount = amount.quantize(STORAGE_EXPONENT)
    row.currency = currency
    row.thresholds = normalize_thresholds(thresholds)
    row.period = period
    session.flush()
    session.refresh(row)
    return row


def delete_budget(
    session: Session, org_id: int, provider: str, scope_kind: str, scope_id: str
) -> bool:
    row = _budget(session, org_id, provider, scope_kind, scope_id)
    if row is None:
        return False
    session.execute(delete(SpendBudgetAlert).where(SpendBudgetAlert.budget_id == row.id))
    session.delete(row)
    session.flush()
    return True


def list_budgets(session: Session, org_id: int, provider: str) -> list[SpendBudget]:
    return list(
        session.scalars(
            select(SpendBudget)
            .where(
                SpendBudget.organization_id == org_id,
                or_(
                    provider_clause(SpendBudget.provider, provider),
                    SpendBudget.provider == PERSON_BUDGET_PROVIDER if is_all(provider) else false(),
                ),
            )
            .order_by(SpendBudget.provider, SpendBudget.scope_kind, SpendBudget.scope_id)
        )
    )


@dataclass
class BudgetStatus:
    budget: SpendBudget
    month: str
    spent: Decimal
    projected: Decimal | None
    alerts: list[SpendBudgetAlert] = field(default_factory=list)
    # A day or week budget: the period `spent` covers, and the spend of every period of the
    # month up to it, which the evaluation compares with the amount.
    period_start: date | None = None
    period_end: date | None = None
    periods: dict[date, Decimal] = field(default_factory=dict)

    @property
    def current_alerts(self) -> list[SpendBudgetAlert]:
        return [a for a in self.alerts if a.period_start == self.period_start]

    @property
    def percent(self) -> Decimal:
        return to_percent(self.spent / self.budget.amount * 100)

    @property
    def projected_percent(self) -> Decimal | None:
        if self.projected is None:
            return None
        return to_percent(self.projected / self.budget.amount * 100)

    @property
    def highest_crossed(self) -> int | None:
        crossed = [
            a.threshold for a in self.current_alerts if a.kind == "threshold" and a.threshold
        ]
        return max(crossed) if crossed else None

    @property
    def projection_exceeds(self) -> bool:
        return any(a.kind == "projection" for a in self.current_alerts)


@dataclass
class BudgetResult:
    run_id: int
    window: Window
    statuses: list[BudgetStatus] = field(default_factory=list)
    inserted: int = 0


def budget_statuses(
    session: Session,
    org_id: int,
    provider: str,
    window: Window,
    *,
    today: date | None = None,
) -> list[BudgetStatus]:
    """Spend, projection and stored alerts of every budget for the month of `window`.

    Computed from the cost lines each time, so a closed month reads its final total and a
    changed amount shows the new percentage; alerts are what the evaluation stored. Under the
    `all` scope the statuses of every provider are concatenated; each budget's spend is read
    from its own provider's lines."""
    if is_all(provider):
        return [
            *(
                status
                for name in scope_providers(provider)
                for status in budget_statuses(session, org_id, name, window, today=today)
            ),
            *person_statuses(session, org_id, window, today=today),
        ]
    today = today or datetime.now(UTC).date()
    month_start, month_end = window.start.date(), window.end.date()
    month = month_start.strftime("%Y-%m")
    current = month_start <= today < month_end
    budgets = list_budgets(session, org_id, provider)
    if not budgets:
        return []
    first = _first_day(budgets, month_start)
    daily: dict[tuple[str, str], Series] = {}
    for kind in ("org", "workspace"):
        if not any(b.scope_kind == kind for b in budgets):
            continue
        for series_id, series in daily_amounts(
            session, org_id, provider, kind, first, month_end
        ).items():
            daily[(kind, series_id)] = series
    alerts_by_budget = _alerts(session, org_id, provider, month, first, month_end)
    projected_totals = _projected_totals(session, org_id, provider, month) if current else {}
    statuses = []
    for budget in budgets:
        series = daily.get((budget.scope_kind, budget.scope_id), {})
        status = BudgetStatus(
            budget=budget,
            month=month,
            spent=_sum(series, month_start, month_end),
            projected=projected_totals.get((budget.scope_kind, budget.scope_id)),
            alerts=alerts_by_budget.get(budget.id, []),
        )
        statuses.append(_with_periods(status, series, window, today))
    return statuses


def period_bounds(period: BudgetPeriod, day: date) -> tuple[date, date]:
    """The `[start, end)` days of the day or ISO week that holds `day`."""
    if period == "day":
        return day, day + timedelta(days=1)
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=7)


def _first_day(budgets: list[SpendBudget], month_start: date) -> date:
    if any(b.period == "week" for b in budgets):
        return period_bounds("week", month_start)[0]
    return month_start


def _sum(series: Series, start: date, end: date) -> Decimal:
    return sum((v for d, v in series.items() if start <= d < end), Decimal("0"))


def _with_periods(
    status: BudgetStatus, series: Series, window: Window, today: date
) -> BudgetStatus:
    """Set `spent` of a day or week budget to the period that holds today (the last day of a
    closed month), with every earlier period of the month for the evaluation; no projection."""
    period = status.budget.period
    if period == "month":
        return status
    month_start, month_end = window.start.date(), window.end.date()
    last = min(today, month_end - timedelta(days=1))
    if last < month_start:
        last = month_start
    start = period_bounds(period, month_start)[0]
    while start <= last:
        end = period_bounds(period, start)[1]
        status.periods[start] = _sum(series, start, end)
        status.period_start, status.period_end = start, end
        start = end
    status.spent = status.periods[status.period_start] if status.period_start else Decimal("0")
    status.projected = None
    return status


def _alerts(
    session: Session, org_id: int, provider: str, month: str, first: date, month_end: date
) -> dict[int, list[SpendBudgetAlert]]:
    """The month's alerts, and those of a week that began in the previous month."""
    by_budget: dict[int, list[SpendBudgetAlert]] = {}
    for alert in session.scalars(
        select(SpendBudgetAlert)
        .where(
            SpendBudgetAlert.organization_id == org_id,
            SpendBudgetAlert.provider == provider,
            or_(
                SpendBudgetAlert.month == month,
                and_(
                    SpendBudgetAlert.period_start >= first,
                    SpendBudgetAlert.period_start < month_end,
                ),
            ),
        )
        .order_by(SpendBudgetAlert.triggered_at, SpendBudgetAlert.id)
    ):
        by_budget.setdefault(alert.budget_id, []).append(alert)
    return by_budget


def person_statuses(
    session: Session, org_id: int, window: Window, *, today: date | None = None
) -> list[BudgetStatus]:
    """Spend of every budget held under `all` for the month of `window`. A person budget
    reads the e-mail's `person` row across every provider, with no projection, since
    projections are stored per provider series. The organization budget reads every
    provider's total, and in the current month the sum of every provider's projection."""
    budgets = list(
        session.scalars(
            select(SpendBudget)
            .where(
                SpendBudget.organization_id == org_id,
                SpendBudget.provider == PERSON_BUDGET_PROVIDER,
            )
            .order_by(SpendBudget.scope_id)
        )
    )
    if not budgets:
        return []
    month = window.start.strftime("%Y-%m")
    people = usage_report(
        session,
        org_id=org_id,
        provider=PERSON_BUDGET_PROVIDER,
        window=window,
        dimension="person",
    )
    spent = {
        ("person", row.key): row.amount or Decimal("0")
        for row in people.rows
        if row.key is not None and row.details.get("kind") == "person"
    }
    if any(b.scope_kind == "team" for b in budgets):
        teams = usage_report(
            session,
            org_id=org_id,
            provider=PERSON_BUDGET_PROVIDER,
            window=window,
            dimension="team",
        )
        spent.update(
            {("team", row.key): row.amount or Decimal("0") for row in teams.rows if row.key}
        )
    month_start, month_end = window.start.date(), window.end.date()
    first = _first_day(budgets, month_start)
    alerts_by_budget = _alerts(session, org_id, PERSON_BUDGET_PROVIDER, month, first, month_end)
    today = today or datetime.now(UTC).date()
    current = month_start <= today < month_end
    statuses: list[BudgetStatus] = []
    for budget in budgets:
        projected = None
        if budget.scope_kind == "org":
            amount, _ = costura_total(session, org_id, ALL, window)
            if current:
                projected = _all_projected(session, org_id, month)
        else:
            amount = spent.get((budget.scope_kind, budget.scope_id), Decimal("0"))
        status = BudgetStatus(
            budget=budget,
            month=month,
            spent=amount,
            projected=projected,
            alerts=alerts_by_budget.get(budget.id, []),
        )
        if budget.period != "month":
            series = daily_amounts(session, org_id, ALL, "org", first, month_end).get(
                ORG_SERIES_ID, {}
            )
            status = _with_periods(status, series, window, today)
        statuses.append(status)
    return statuses


def _all_projected(session: Session, org_id: int, month: str) -> Decimal | None:
    total = session.scalar(
        select(func.sum(SpendProjection.projected_total)).where(
            SpendProjection.organization_id == org_id,
            SpendProjection.month == month,
            SpendProjection.series_kind == "org",
        )
    )
    return None if total is None else Decimal(total)


def evaluate_budgets(
    session: Session,
    org_id: int,
    provider: str,
    window: Window,
    *,
    today: date | None = None,
) -> BudgetResult:
    """Raise the alerts the month's spend and projection justify and record a
    `provider_sync_runs` row with endpoint `budget_evaluation`.

    A threshold alert is inserted once per (budget, month, threshold) when spend reaches
    `amount x threshold / 100`; a projection alert once per (budget, month) when the stored
    month-end estimate of the current month is above the amount. Re-runs insert nothing new
    unless spend or projection moved past another line. Under `all` only the person budgets
    are evaluated; each provider evaluates its own."""
    run = ProviderSyncRun(
        organization_id=org_id,
        provider=provider,
        endpoint=BUDGET_ENDPOINT,
        window_start=window.start,
        window_end=window.end,
    )
    session.add(run)
    session.commit()
    result = BudgetResult(run_id=run.id, window=window)
    try:
        statuses = (
            person_statuses(session, org_id, window, today=today)
            if is_all(provider)
            else budget_statuses(session, org_id, provider, window, today=today)
        )
        for status in statuses:
            budget = status.budget
            if budget.period != "month":
                result.inserted += _evaluate_periods(session, status)
                continue
            existing = {(a.kind, a.threshold) for a in status.alerts}
            # A person budget is evaluated after each provider's import, so the first
            # evaluation of a month may see part of the person's spend. The alert stays one
            # row; its figure follows the month until every provider has landed.
            if budget.provider == PERSON_BUDGET_PROVIDER:
                for alert in status.alerts:
                    if alert.kind == "threshold" and alert.spent < status.spent:
                        alert.spent = status.spent.quantize(STORAGE_EXPONENT)
            for threshold in budget.thresholds:
                if ("threshold", threshold) in existing:
                    continue
                if status.spent >= budget.amount * threshold / 100:
                    status.alerts.append(_alert(status, "threshold", threshold, session=session))
                    result.inserted += 1
            if (
                status.projected is not None
                and ("projection", None) not in existing
                and status.projected > budget.amount
            ):
                status.alerts.append(_alert(status, "projection", None, session=session))
                result.inserted += 1
        session.flush()
        result.statuses = statuses
        run.status = "succeeded"
        run.finished_at = datetime.now(UTC)
        run.rows_upserted = result.inserted
        session.commit()
    except Exception as exc:
        session.rollback()
        run.status = "failed"
        run.finished_at = datetime.now(UTC)
        run.error = stored_exception_text(exc)
        session.commit()
        raise
    return result


def _evaluate_periods(session: Session, status: BudgetStatus) -> int:
    """Threshold alerts of a day or week budget, once per (period, threshold)."""
    budget = status.budget
    existing = {(a.period_start, a.threshold) for a in status.alerts if a.kind == "threshold"}
    inserted = 0
    for start, spent in status.periods.items():
        for threshold in budget.thresholds:
            if (start, threshold) in existing or spent < budget.amount * threshold / 100:
                continue
            status.alerts.append(
                _alert(status, "threshold", threshold, session=session, period=(start, spent))
            )
            inserted += 1
    return inserted


def _alert(
    status: BudgetStatus,
    kind: str,
    threshold: int | None,
    *,
    session: Session,
    period: tuple[date, Decimal] | None = None,
) -> SpendBudgetAlert:
    spent = status.spent if period is None else period[1]
    alert = SpendBudgetAlert(
        organization_id=status.budget.organization_id,
        provider=status.budget.provider,
        budget_id=status.budget.id,
        month=status.month if period is None else period[0].strftime("%Y-%m"),
        period_start=None if period is None else period[0],
        kind=kind,
        threshold=threshold,
        spent=spent.quantize(STORAGE_EXPONENT),
        projected=None if status.projected is None else status.projected.quantize(STORAGE_EXPONENT),
        amount=status.budget.amount,
        currency=status.budget.currency,
    )
    session.add(alert)
    return alert


def _budget(
    session: Session, org_id: int, provider: str, scope_kind: str, scope_id: str
) -> SpendBudget | None:
    return session.scalar(
        select(SpendBudget).where(
            SpendBudget.organization_id == org_id,
            SpendBudget.provider == provider,
            SpendBudget.scope_kind == scope_kind,
            SpendBudget.scope_id == scope_id,
        )
    )


def _projected_totals(
    session: Session, org_id: int, provider: str, month: str
) -> dict[tuple[str, str], Decimal]:
    """The projected month total of every series, summed over the provider's accounts, in one
    query (what `stored_projected_total` answers for one series)."""
    rows = session.execute(
        select(
            SpendProjection.series_kind,
            SpendProjection.series_id,
            func.sum(SpendProjection.projected_total),
        )
        .where(
            SpendProjection.organization_id == org_id,
            SpendProjection.provider == provider,
            SpendProjection.month == month,
        )
        .group_by(SpendProjection.series_kind, SpendProjection.series_id)
    )
    return {(kind, series_id): Decimal(total) for kind, series_id, total in rows}
