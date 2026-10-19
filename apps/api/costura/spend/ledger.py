"""Readers over the stored cost lines of one provider scope and window: the totals, the
breakdown and the token sums every report and check starts from.

A unit is one `(provider, provider_account_id)` pair; readers over `all` add their units up."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura import accounts
from costura.errors import InvalidInput
from costura.models import (
    SpendCostLine,
    SpendUsageLine,
)
from costura.spend import BREAKDOWN_DIMENSIONS
from costura.spend.inventory import InventoryResolver
from costura.spend.scope import account_clause, provider_clause, scope_providers
from costura.spend.sql import utc_day
from costura.spend.window import Window

Unit = tuple[str, int]


@dataclass(frozen=True)
class BreakdownRow:
    label: str
    amount: Decimal


def in_window(column: Any, window: Window) -> Any:
    return (column >= window.start) & (column < window.end)


def cost_where(
    org_id: int, provider: str, window: Window, account_id: int | None = None
) -> tuple[Any, ...]:
    return (
        SpendCostLine.organization_id == org_id,
        provider_clause(SpendCostLine.provider, provider),
        account_clause(SpendCostLine.provider_account_id, account_id),
        in_window(SpendCostLine.period_start, window),
    )


def scope_units(session: Session, org_id: int, scope: str, account_id: int | None) -> list[Unit]:
    """`(provider, account_id)` pairs the scope covers: one pair when an account is named,
    else every account of every provider in the scope."""

    if account_id is not None:
        rows = [a for a in accounts.list_accounts(session, org_id) if a.id == account_id]
    else:
        rows = [
            a
            for name in scope_providers(scope)
            for a in accounts.list_accounts(session, org_id, name)
        ]
    return [(a.provider, a.id) for a in rows]


def costura_total(
    session: Session,
    org_id: int,
    provider: str,
    window: Window,
    account_id: int | None = None,
) -> tuple[Decimal, str | None]:
    where = cost_where(org_id, provider, window, account_id)
    total, currencies = session.execute(
        select(
            func.coalesce(func.sum(SpendCostLine.amount), 0),
            func.count(func.distinct(SpendCostLine.currency)),
        ).where(*where)
    ).one()
    currency = None
    if currencies == 1:
        currency = session.scalar(select(SpendCostLine.currency).where(*where).limit(1))
    return Decimal(total), currency


def currency_totals(
    session: Session, org_id: int, provider: str, window: Window
) -> dict[str, Decimal]:
    """Billed spend per currency; one key in the usual case."""
    rows = session.execute(
        select(SpendCostLine.currency, func.sum(SpendCostLine.amount))
        .where(*cost_where(org_id, provider, window))
        .group_by(SpendCostLine.currency)
        .order_by(SpendCostLine.currency)
    ).all()
    return {currency: Decimal(amount) for currency, amount in rows}


def breakdown(
    session: Session,
    org_id: int,
    provider: str,
    window: Window,
    dimension: str,
    account_id: int | None = None,
) -> list[BreakdownRow]:
    if dimension not in BREAKDOWN_DIMENSIONS:
        raise InvalidInput(
            f"unknown dimension {dimension!r}; expected one of {BREAKDOWN_DIMENSIONS}"
        )
    total = func.sum(SpendCostLine.amount)
    where = cost_where(org_id, provider, window, account_id)

    if dimension == "day":
        day = utc_day(SpendCostLine.period_start)
        rows = session.execute(select(day, total).where(*where).group_by(day)).all()
        by_day = {row[0]: Decimal(row[1]) for row in rows}
        return [
            BreakdownRow(label=day.isoformat(), amount=by_day.get(day, Decimal("0")))
            for day in window.days()
        ]

    column = {
        "workspace": SpendCostLine.workspace_id,
        "model": SpendCostLine.model,
        "token_type": SpendCostLine.token_type,
        "cost_type": SpendCostLine.cost_type,
        "service_tier": SpendCostLine.service_tier,
        "description": SpendCostLine.description,
    }[dimension]
    if dimension == "workspace":
        rows = session.execute(
            select(SpendCostLine.provider, column, total)
            .where(*where)
            .group_by(SpendCostLine.provider, column)
            .order_by(total.desc())
        ).all()
        resolver = InventoryResolver(session, org_id, provider)
        return [
            BreakdownRow(label=resolver.workspace_label(row[0], row[1]), amount=Decimal(row[2]))
            for row in rows
        ]
    rows = session.execute(
        select(column, total).where(*where).group_by(column).order_by(total.desc())
    ).all()
    return [
        BreakdownRow(label=row[0] if row[0] is not None else "(none)", amount=Decimal(row[1]))
        for row in rows
    ]


def has_cost_lines(
    session: Session, org_id: int, provider: str, window: Window, account_id: int | None = None
) -> bool:
    statement = (
        select(SpendCostLine.id).where(*cost_where(org_id, provider, window, account_id)).limit(1)
    )
    return session.scalar(statement) is not None


def token_totals(
    session: Session,
    org_id: int,
    provider: str,
    window: Window,
    account_id: int | None = None,
) -> dict[str, int]:
    columns = (
        SpendUsageLine.uncached_input_tokens,
        SpendUsageLine.cache_creation_5m_tokens,
        SpendUsageLine.cache_creation_1h_tokens,
        SpendUsageLine.cache_read_tokens,
        SpendUsageLine.output_tokens,
        SpendUsageLine.web_search_requests,
    )
    row = session.execute(
        select(*(func.coalesce(func.sum(column), 0) for column in columns)).where(
            SpendUsageLine.organization_id == org_id,
            provider_clause(SpendUsageLine.provider, provider),
            account_clause(SpendUsageLine.provider_account_id, account_id),
            in_window(SpendUsageLine.period_start, window),
        )
    ).one()
    return {column.key: int(value) for column, value in zip(columns, row, strict=True)}


def has_cost_amount(
    session: Session, org_id: int, provider: str, window: Window, account_id: int | None = None
) -> bool:
    statement = (
        select(SpendCostLine.id)
        .where(*cost_where(org_id, provider, window, account_id), SpendCostLine.amount != 0)
        .limit(1)
    )
    return session.scalar(statement) is not None
