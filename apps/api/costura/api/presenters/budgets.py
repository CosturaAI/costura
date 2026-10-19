"""Response shapes for budgets, owner assignments and personal keys."""

from costura.api import schemas
from costura.api.presenters.common import series_label
from costura.models import SpendBudget, SpendBudgetAlert
from costura.spend import budgets
from costura.spend.assignments import OwnerAssignmentView, PersonalKeyView
from costura.spend.inventory import InventoryResolver


def budget_out(resolver: InventoryResolver, row: SpendBudget) -> schemas.BudgetOut:
    return schemas.BudgetOut(
        id=row.id,
        provider=row.provider,
        scope_kind=row.scope_kind,
        scope_id=row.scope_id,
        label=series_label(resolver, row.provider, row.scope_kind, row.scope_id),
        amount=schemas.money(row.amount) or "0.00",
        currency=row.currency,
        thresholds=list(row.thresholds),
        period=row.period,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def budget_alert_out(
    resolver: InventoryResolver, budget: SpendBudget, row: SpendBudgetAlert
) -> schemas.BudgetAlertOut:
    return schemas.BudgetAlertOut(
        id=row.id,
        budget_id=row.budget_id,
        scope_kind=budget.scope_kind,
        scope_id=budget.scope_id,
        label=series_label(resolver, budget.provider, budget.scope_kind, budget.scope_id),
        month=row.month,
        period_start=row.period_start,
        kind=row.kind,
        threshold=row.threshold,
        spent=schemas.money(row.spent) or "0.00",
        projected=schemas.money(row.projected),
        amount=schemas.money(row.amount) or "0.00",
        currency=row.currency,
        triggered_at=row.triggered_at,
    )


def budget_status_out(
    resolver: InventoryResolver, s: budgets.BudgetStatus
) -> schemas.BudgetStatusOut:
    crossed_at = {a.threshold: a.triggered_at for a in s.current_alerts if a.kind == "threshold"}
    return schemas.BudgetStatusOut(
        budget=budget_out(resolver, s.budget),
        period_start=s.period_start,
        period_end=s.period_end,
        spent=schemas.money(s.spent) or "0.00",
        percent=f"{s.percent:.2f}",
        projected=schemas.money(s.projected),
        projected_percent=None if s.projected_percent is None else f"{s.projected_percent:.2f}",
        thresholds=[
            schemas.BudgetThresholdOut(percent=t, crossed_at=crossed_at.get(t))
            for t in s.budget.thresholds
        ],
        highest_crossed=s.highest_crossed,
        projection_exceeds=s.projection_exceeds,
        alerts=[budget_alert_out(resolver, s.budget, a) for a in s.alerts],
    )


def budget_statuses_out(
    resolver: InventoryResolver, month: str, statuses: list[budgets.BudgetStatus]
) -> schemas.BudgetStatusesOut:
    alerts = sorted(
        (a for s in statuses for a in s.alerts), key=lambda a: (a.triggered_at, a.id), reverse=True
    )
    by_id = {s.budget.id: s.budget for s in statuses}
    return schemas.BudgetStatusesOut(
        month=month,
        statuses=[budget_status_out(resolver, s) for s in statuses],
        alerts=[budget_alert_out(resolver, by_id[a.budget_id], a) for a in alerts],
    )


def owner_assignment_out(
    resolver: InventoryResolver, view: OwnerAssignmentView
) -> schemas.OwnerAssignmentOut:
    row = view.row
    return schemas.OwnerAssignmentOut(
        provider=row.provider,
        kind=row.kind,
        external_id=row.external_id,
        label=series_label(resolver, row.provider, row.kind, row.external_id),
        email=row.email,
        note=row.note,
        assigned_by=view.assigned_by,
        updated_at=row.updated_at,
    )


def personal_key_out(resolver: InventoryResolver, view: PersonalKeyView) -> schemas.PersonalKeyOut:
    row = view.row
    return schemas.PersonalKeyOut(
        provider=row.provider,
        api_key_id=row.api_key_id,
        label=resolver.api_key_label(row.provider, row.api_key_id),
        email=row.email,
        assigned_by=view.assigned_by,
        updated_at=row.updated_at,
    )
