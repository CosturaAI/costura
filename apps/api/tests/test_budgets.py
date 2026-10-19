"""Budgets: thresholds crossed by month-to-date spend, the projection alert for the current
month only, dedupe on re-run, and alerts that outlive an amount change but not the budget
."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura.models import ProviderSyncRun, SpendBudgetAlert
from costura.spend.budgets import (
    BUDGET_ENDPOINT,
    InvalidBudget,
    budget_statuses,
    delete_budget,
    evaluate_budgets,
    list_budgets,
    normalize_thresholds,
    set_budget,
)
from costura.spend.projection import run_projection
from costura.spend.window import Window
from tests.seed import seed_days
from tests.test_anomalies import HISTORY_START, PROVIDER, steady

AUGUST = Window.for_month("2026-08")
TODAY = date(2026, 8, 21)  # data through Aug 20: 14 weekdays and 6 weekend days, 1,520 USD
ORG = ("org", "__org__")
WS_A = ("workspace", "ws_a")  # 60% of every day: 912 USD


def seed(db_session: Session, org_id: int) -> None:
    seed_days(db_session, org_id, PROVIDER, HISTORY_START, TODAY, steady)
    run_projection(db_session, org_id, PROVIDER, AUGUST, today=TODAY)


def test_normalize_thresholds_sorts_dedupes_and_bounds() -> None:
    assert normalize_thresholds(None) == [50, 80, 100]
    assert normalize_thresholds([100, 50, 80, 50]) == [50, 80, 100]
    with pytest.raises(InvalidBudget):
        normalize_thresholds([])
    with pytest.raises(InvalidBudget):
        normalize_thresholds([0, 50])
    with pytest.raises(InvalidBudget):
        normalize_thresholds([250])


def test_set_budget_validates_scope_and_amount(db_session: Session, org_id: int) -> None:
    with pytest.raises(InvalidBudget):
        set_budget(db_session, org_id, PROVIDER, "api_key", "k", Decimal("10"), None)
    with pytest.raises(InvalidBudget):
        set_budget(db_session, org_id, PROVIDER, "org", "ws_a", Decimal("10"), None)
    with pytest.raises(InvalidBudget):
        set_budget(db_session, org_id, PROVIDER, *ORG, Decimal("0"), None)

    created = set_budget(db_session, org_id, PROVIDER, *ORG, Decimal("1800"), None)
    updated = set_budget(db_session, org_id, PROVIDER, *ORG, Decimal("2000"), [90, 60])
    assert created.id == updated.id
    assert (updated.amount, updated.thresholds) == (Decimal("2000"), [60, 90])
    assert [b.scope_id for b in list_budgets(db_session, org_id, PROVIDER)] == ["__org__"]


def test_thresholds_and_projection_raise_alerts_once(db_session: Session, org_id: int) -> None:
    seed(db_session, org_id)
    set_budget(db_session, org_id, PROVIDER, *ORG, Decimal("1800"), None)
    set_budget(db_session, org_id, PROVIDER, *WS_A, Decimal("1000"), [50, 80, 100])

    result = evaluate_budgets(db_session, org_id, PROVIDER, AUGUST, today=TODAY)

    # org: 1,520 of 1,800 (84.44%) crosses 50 and 80; projected 2,300 is above the amount.
    # ws_a: 912 of 1,000 (91.2%) crosses 50 and 80; projected 1,380 is above the amount.
    assert result.inserted == 6
    by_scope = {(s.budget.scope_kind, s.budget.scope_id): s for s in result.statuses}
    org = by_scope[ORG]
    assert (org.spent, org.percent, org.projected) == (
        Decimal("1520"),
        Decimal("84.44"),
        Decimal("2300"),
    )
    assert org.highest_crossed == 80 and org.projection_exceeds
    assert sorted((a.kind, a.threshold) for a in org.alerts) == [
        ("projection", None),
        ("threshold", 50),
        ("threshold", 80),
    ]
    ws = by_scope[WS_A]
    assert (ws.spent, ws.percent, ws.projected_percent) == (
        Decimal("912"),
        Decimal("91.20"),
        Decimal("138.00"),
    )
    run = db_session.scalar(
        select(ProviderSyncRun).where(ProviderSyncRun.endpoint == BUDGET_ENDPOINT)
    )
    assert run is not None and run.status == "succeeded" and run.rows_upserted == 6

    # A second pass finds every line already recorded.
    again = evaluate_budgets(db_session, org_id, PROVIDER, AUGUST, today=TODAY)
    assert again.inserted == 0
    assert db_session.scalar(select(func.count(SpendBudgetAlert.id))) == 6


def test_closed_month_checks_thresholds_but_not_the_projection(
    db_session: Session, org_id: int
) -> None:
    seed(db_session, org_id)
    set_budget(db_session, org_id, PROVIDER, *ORG, Decimal("1500"), None)

    result = evaluate_budgets(db_session, org_id, PROVIDER, AUGUST, today=date(2026, 9, 14))

    [org] = result.statuses
    assert org.projected is None
    assert sorted(a.threshold for a in org.alerts) == [50, 80, 100]
    assert not org.projection_exceeds


def test_amount_change_keeps_alerts_and_delete_removes_them(
    db_session: Session, org_id: int
) -> None:
    seed(db_session, org_id)
    set_budget(db_session, org_id, PROVIDER, *ORG, Decimal("1800"), None)
    evaluate_budgets(db_session, org_id, PROVIDER, AUGUST, today=TODAY)

    set_budget(db_session, org_id, PROVIDER, *ORG, Decimal("5000"), None)
    result = evaluate_budgets(db_session, org_id, PROVIDER, AUGUST, today=TODAY)
    [org] = result.statuses
    assert result.inserted == 0
    assert org.percent == Decimal("30.40")
    assert len(org.alerts) == 3  # the 50, 80 and projection alerts recorded against 1,800
    assert org.alerts[0].amount == Decimal("1800")

    assert delete_budget(db_session, org_id, PROVIDER, *ORG) is True
    assert delete_budget(db_session, org_id, PROVIDER, *ORG) is False
    assert db_session.scalar(select(func.count(SpendBudgetAlert.id))) == 0
    assert budget_statuses(db_session, org_id, PROVIDER, AUGUST, today=TODAY) == []


def test_workspace_budget_reads_only_that_workspace(db_session: Session, org_id: int) -> None:
    seed(db_session, org_id)
    set_budget(db_session, org_id, PROVIDER, "workspace", "ws_b", Decimal("1000"), [50])

    result = evaluate_budgets(db_session, org_id, PROVIDER, AUGUST, today=TODAY)

    [ws_b] = result.statuses
    assert ws_b.spent == Decimal("608")  # 40% of 1,520
    assert [a.threshold for a in ws_b.alerts] == [50]
