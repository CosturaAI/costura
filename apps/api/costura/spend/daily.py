"""Daily USD amounts per series, the input shared by anomaly detection and projection.

A series is one value per day for one id of one kind: the organization total (`org`), a
workspace or a model (both from `spend_cost_lines`, the reconciled figure), or a principal:
an API key (`api_key`) or an OAuth account (`account`, usage made with a Claude Code login,
which has no key), both from `spend_allocated_lines`, since the cost report has neither
dimension. Rows without a natural id use the sentinels of `spend.usage` so ids round-trip to
the Explore filters.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from costura.models import SpendAllocatedLine, SpendCostLine
from costura.models.intelligence import ORG_SERIES_ID, PRINCIPAL_KINDS
from costura.spend.dimensions import KEY_DEFAULT_WORKSPACE, KEY_NO_MODEL
from costura.spend.scope import account_clause, provider_clause
from costura.spend.sql import utc_day

Series = dict[date, Decimal]
SeriesByKind = dict[str, Series]

# Child dimensions ranked as root causes for an anomaly of each kind: the organization total
# points at the principals behind it, then the model; a principal points at its models.
CHILD_KINDS: dict[str, tuple[str, ...]] = {
    "org": ("api_key", "account", "model"),
    "api_key": ("model",),
    "account": ("model",),
}


def daily_amounts(
    session: Session,
    org_id: int,
    provider: str,
    kind: str,
    start: date,
    end: date,
    *,
    parent: tuple[str, str] | None = None,
    account_id: int | None = None,
) -> SeriesByKind:
    """Daily sums for every series of `kind` with data in `[start, end)`.

    `parent=(kind, id)` restricts the rows to one workspace, model or key, so the same call
    yields the contributors of an anomaly; `account_id` restricts them to one provider
    account. Missing days are absent, not zero.
    """
    table = (
        SpendAllocatedLine if kind in PRINCIPAL_KINDS or _needs_allocated(parent) else SpendCostLine
    )
    day = utc_day(table.period_start)
    clauses = [
        table.organization_id == org_id,
        provider_clause(table.provider, provider),
        account_clause(table.provider_account_id, account_id),
        table.period_start >= _at_midnight(start),
        table.period_start < _at_midnight(end),
    ]
    if parent is not None:
        clauses.append(_id_clause(table, *parent))
    if kind == "org":
        rows = session.execute(
            select(day, func.sum(table.amount)).where(*clauses).group_by(day)
        ).all()
        return {ORG_SERIES_ID: {d: Decimal(amount) for d, amount in rows}}
    column = _column(table, kind)
    if kind == "api_key":
        clauses.append(column.is_not(None))
    elif kind == "account":
        # Account anomalies cover direct login usage, not key requests with an account id.
        clauses.append(column.is_not(None))
        clauses.append(table.api_key_id.is_(None))
    rows = session.execute(
        select(day, column, func.sum(table.amount)).where(*clauses).group_by(day, column)
    ).all()
    result: SeriesByKind = {}
    for d, series_id, amount in rows:
        result.setdefault(_series_id(kind, series_id), {})[d] = Decimal(amount)
    return result


def _needs_allocated(parent: tuple[str, str] | None) -> bool:
    return parent is not None and parent[0] in PRINCIPAL_KINDS


def _column(table: Any, kind: str) -> Any:
    name = {
        "workspace": "workspace_id",
        "model": "model",
        "api_key": "api_key_id",
        "account": "account_id",
    }[kind]
    return getattr(table, name)


def _id_clause(table: Any, kind: str, series_id: str) -> Any:
    column = _column(table, kind)
    if series_id in (KEY_DEFAULT_WORKSPACE, KEY_NO_MODEL):
        return column.is_(None)
    if kind == "account":
        return and_(column == series_id, table.api_key_id.is_(None))
    return column == series_id


def _series_id(kind: str, raw: str | None) -> str:
    if raw is not None:
        return raw
    return KEY_DEFAULT_WORKSPACE if kind == "workspace" else KEY_NO_MODEL


def _at_midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def value_on(series: Series, day: date) -> Decimal:
    return series.get(day, Decimal("0"))


def first_day(series: Series) -> date | None:
    """First day with a non-zero amount; None for an empty series."""
    days = sorted(d for d, amount in series.items() if amount != 0)
    return days[0] if days else None


def trailing_samples(series: Series, day: date, days: int) -> list[Decimal]:
    """Amounts on the `days` days before `day`, zero-filled from the series' first day."""
    start = first_day(series)
    if start is None:
        return []
    return [
        value_on(series, day - timedelta(days=k))
        for k in range(1, days + 1)
        if day - timedelta(days=k) >= start
    ]


def median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return Decimal("0")
    if n % 2:
        return ordered[n // 2]
    return (ordered[n // 2 - 1] + ordered[n // 2]) / 2
