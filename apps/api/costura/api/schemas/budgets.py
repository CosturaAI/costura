"""Budget, budget status, owner assignment, personal key and invoice shapes."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field

from costura.api.schemas.common import (
    BudgetAlertKind,
    BudgetPeriod,
    BudgetScopeKind,
    OwnerAssignmentKind,
)


class OwnerAssignmentIn(BaseModel):
    email: str
    note: str | None = None


class OwnerAssignmentOut(BaseModel):
    provider: str
    kind: OwnerAssignmentKind
    external_id: str
    label: str
    email: str
    note: str | None
    assigned_by: str | None
    updated_at: datetime


class PersonalKeyIn(BaseModel):
    email: str


class PersonalKeyOut(BaseModel):
    provider: str
    api_key_id: str
    label: str
    email: str
    assigned_by: str | None
    updated_at: datetime


class InvoiceIn(BaseModel):
    amount: Annotated[Decimal, Field(ge=0, lt=Decimal("1e14"))]
    note: str | None = None


class InvoiceOut(BaseModel):
    provider: str
    account_id: int
    account_label: str
    month: str
    amount: str
    currency: str
    note: str | None
    entered_by: str | None
    updated_at: datetime


class InvoicesOut(BaseModel):
    month: str
    items: list[InvoiceOut]


class BudgetIn(BaseModel):
    amount: Decimal
    # Percentages of `amount`; omitted means the default 50, 80, 100.
    thresholds: list[int] | None = None
    # The window `amount` applies to; a person budget is monthly.
    period: BudgetPeriod = "month"


class BudgetOut(BaseModel):
    id: int
    provider: str
    scope_kind: BudgetScopeKind
    # "__org__", the provider workspace id or the person's e-mail.
    scope_id: str
    label: str
    amount: str
    currency: str
    thresholds: list[int]
    period: BudgetPeriod
    created_at: datetime
    updated_at: datetime


class BudgetsOut(BaseModel):
    budgets: list[BudgetOut]


class BudgetAlertOut(BaseModel):
    id: int
    budget_id: int
    scope_kind: BudgetScopeKind
    scope_id: str
    label: str
    month: str
    # The day or the Monday of the week a day or week budget was crossed in; null for a month.
    period_start: date | None
    kind: BudgetAlertKind
    threshold: int | None
    spent: str
    projected: str | None
    amount: str
    currency: str
    triggered_at: datetime


class BudgetThresholdOut(BaseModel):
    percent: int
    crossed_at: datetime | None


class BudgetStatusOut(BaseModel):
    budget: BudgetOut
    # A day or week budget: the `[start, end)` days `spent` covers, the period holding today.
    period_start: date | None
    period_end: date | None
    spent: str
    percent: str
    projected: str | None
    projected_percent: str | None
    thresholds: list[BudgetThresholdOut]
    highest_crossed: int | None
    projection_exceeds: bool
    alerts: list[BudgetAlertOut]


class BudgetStatusesOut(BaseModel):
    month: str
    statuses: list[BudgetStatusOut]
    alerts: list[BudgetAlertOut]  # every alert of the month, newest first
