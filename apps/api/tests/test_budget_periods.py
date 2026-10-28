"""Day and week budgets: one alert per period and threshold, the period that holds today as
the status, a week that began in the previous month, and no projection."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from costura.api.presenters.signals import detail_of
from costura.spend.budgets import InvalidBudget, evaluate_budgets, period_bounds, set_budget
from costura.spend.signals import budget_signals
from costura.spend.window import Window
from tests.seed import seed_days
from tests.test_anomalies import HISTORY_START, PROVIDER, SPIKE_DAY, steady

AUGUST = Window.for_month("2026-08")
TODAY = date(2026, 8, 21)
ORG = ("org", "__org__")


def seed(db_session: Session, org_id: int) -> None:
    # 100 USD on weekdays, 20 on weekends; Tuesday Aug 11 spends 940.
    seed_days(
        db_session, org_id, PROVIDER, HISTORY_START, TODAY, lambda d: steady(d, Decimal("900"))
    )


def test_period_bounds_are_the_utc_day_and_the_iso_week() -> None:
    assert period_bounds("day", date(2026, 8, 11)) == (date(2026, 8, 11), date(2026, 8, 12))
    assert period_bounds("week", date(2026, 8, 1)) == (date(2026, 7, 27), date(2026, 8, 3))


def test_a_daily_budget_alerts_on_the_spike_day_once(db_session: Session, org_id: int) -> None:
    seed(db_session, org_id)
    set_budget(db_session, org_id, PROVIDER, *ORG, Decimal("200"), [100], period="day")

    result = evaluate_budgets(db_session, org_id, PROVIDER, AUGUST, today=TODAY)

    assert result.inserted == 1
    (status,) = result.statuses
    (alert,) = status.alerts
    assert (alert.period_start, alert.month, alert.spent) == (
        SPIKE_DAY,
        "2026-08",
        Decimal("940"),
    )
    assert (status.period_start, status.spent, status.projected) == (TODAY, Decimal("0"), None)
    assert status.highest_crossed is None
    assert evaluate_budgets(db_session, org_id, PROVIDER, AUGUST, today=TODAY).inserted == 0

    (signal,) = budget_signals(db_session, org_id, PROVIDER, "2026-08")
    assert detail_of(signal) == "100% of the daily budget on 2026-08-11"


def test_a_weekly_budget_reads_iso_weeks_across_the_month_start(
    db_session: Session, org_id: int
) -> None:
    seed(db_session, org_id)
    set_budget(db_session, org_id, PROVIDER, *ORG, Decimal("600"), [80, 100], period="week")

    result = evaluate_budgets(db_session, org_id, PROVIDER, AUGUST, today=TODAY)

    (status,) = result.statuses
    crossed = sorted((a.period_start, a.threshold, a.month) for a in status.alerts)
    # Full weeks spend 540 (90%); the week of the spike spends 1,380; Aug 17-20 spend 400.
    assert crossed == [
        (date(2026, 7, 27), 80, "2026-07"),
        (date(2026, 8, 3), 80, "2026-08"),
        (date(2026, 8, 10), 80, "2026-08"),
        (date(2026, 8, 10), 100, "2026-08"),
    ]
    assert (status.period_start, status.period_end, status.spent) == (
        date(2026, 8, 17),
        date(2026, 8, 24),
        Decimal("400"),
    )
    assert evaluate_budgets(db_session, org_id, PROVIDER, AUGUST, today=TODAY).inserted == 0


def test_a_week_that_began_last_month_still_signals_this_month(
    db_session: Session, org_id: int
) -> None:
    seed(db_session, org_id)
    set_budget(db_session, org_id, PROVIDER, *ORG, Decimal("600"), [80], period="week")
    evaluate_budgets(db_session, org_id, PROVIDER, AUGUST, today=date(2026, 8, 2))

    (signal,) = budget_signals(db_session, org_id, PROVIDER, "2026-08")
    assert signal.alert is not None and signal.alert.period_start == date(2026, 7, 27)
    assert budget_signals(db_session, org_id, PROVIDER, "2026-09") == []


def test_a_person_budget_stays_monthly(db_session: Session, org_id: int) -> None:
    with pytest.raises(InvalidBudget):
        set_budget(
            db_session,
            org_id,
            "all",
            "person",
            "ana@example.com",
            Decimal("10"),
            None,
            period="day",
        )


def test_the_all_provider_budget_reads_days_across_providers(
    db_session: Session, org_id: int
) -> None:
    seed(db_session, org_id)
    set_budget(db_session, org_id, "all", *ORG, Decimal("900"), [100], period="day")

    result = evaluate_budgets(db_session, org_id, "all", AUGUST, today=TODAY)

    (status,) = result.statuses
    assert [(a.period_start, a.provider) for a in status.alerts] == [(SPIKE_DAY, "all")]
    assert status.projected is None
