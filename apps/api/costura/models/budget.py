"""Budgets per organization total, per workspace or per person over a month, an ISO week or a
UTC day, and the alerts they raise. A person budget belongs to provider `all`: it sums one
e-mail across every provider.

A budget mirrors the spend limit an administrator sets in the provider console; Costura
compares spend and projection against it and never enforces anything. The limits a provider
does report are read into `provider_limits`, `provider_api_keys` and `provider_users`.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, get_args

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from costura.db import Base
from costura.models.checks import one_of

BudgetScopeKind = Literal["org", "workspace", "person", "team"]
BUDGET_SCOPES: tuple[BudgetScopeKind, ...] = get_args(BudgetScopeKind)
# The provider a person budget is stored under: its spend crosses every provider.
PERSON_BUDGET_PROVIDER = "all"
BudgetAlertKind = Literal["threshold", "projection"]
ALERT_KINDS: tuple[BudgetAlertKind, ...] = get_args(BudgetAlertKind)
DEFAULT_THRESHOLDS = [50, 80, 100]
BudgetPeriod = Literal["month", "week", "day"]
BUDGET_PERIODS: tuple[BudgetPeriod, ...] = get_args(BudgetPeriod)


class SpendBudget(Base):
    __tablename__ = "spend_budgets"
    __table_args__ = (
        UniqueConstraint("organization_id", "provider", "scope_kind", "scope_id"),
        one_of("scope_kind", BUDGET_SCOPES),
        one_of("period", BUDGET_PERIODS),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    # "org" with scope_id "__org__", "workspace" with the provider workspace id, "person"
    # with the lowercased e-mail or "team" with the team slug (both under provider `all`).
    scope_kind: Mapped[BudgetScopeKind] = mapped_column(Text, nullable=False)
    scope_id: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="USD")
    # Sorted unique percentages of `amount` that raise a threshold alert when spend reaches them.
    thresholds: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    # The window `amount` applies to: the calendar month, the ISO week (Monday start) or the
    # UTC day. Day and week budgets raise their alerts once per period and have no projection.
    period: Mapped[BudgetPeriod] = mapped_column(
        Text, nullable=False, default="month", server_default="month"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SpendBudgetAlert(Base):
    __tablename__ = "spend_budget_alerts"
    __table_args__ = (
        # NULLS NOT DISTINCT so the projection alert (threshold null) dedupes like the others.
        UniqueConstraint(
            "budget_id",
            "month",
            "period_start",
            "kind",
            "threshold",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_spend_budget_alerts_org_provider_month", "organization_id", "provider", "month"),
        one_of("kind", ALERT_KINDS),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    budget_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("spend_budgets.id", ondelete="CASCADE"), nullable=False
    )
    month: Mapped[str] = mapped_column(Text, nullable=False)
    # First day of the week or day a day or week budget was crossed in; null for a month budget.
    # `month` is the month of that day.
    period_start: Mapped[date | None] = mapped_column(Date)
    # "threshold" (spend reached `threshold` percent) or "projection" (month-end estimate above
    # the amount; `threshold` is null).
    kind: Mapped[BudgetAlertKind] = mapped_column(Text, nullable=False)
    threshold: Mapped[int | None] = mapped_column(Integer)
    spent: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    projected: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
