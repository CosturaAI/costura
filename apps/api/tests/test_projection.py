"""Month-end projection: weekday medians for the remaining days with a p10/p90 band over 8
weeks (min/max when fewer than 6 samples), stored per series for the current month only
."""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from costura.models import SpendProjection
from costura.spend.projection import project, run_projection
from costura.spend.window import Window
from tests.seed import seed_days
from tests.test_anomalies import HISTORY_START, PROVIDER, steady

AUGUST = Window.for_month("2026-08")
AS_OF = date(2026, 8, 20)  # Thursday; 11 days remain (Fri 21 .. Mon 31)


def test_project_adds_weekday_medians_and_a_band_to_month_to_date() -> None:
    # Weekdays 100, weekends 20, except one Friday at 160 within the sample window.
    series: dict[date, Decimal] = {}
    day = HISTORY_START
    while day <= AS_OF:
        series[day] = Decimal("20") if day.weekday() >= 5 else Decimal("100")
        day = date.fromordinal(day.toordinal() + 1)
    series[date(2026, 8, 14)] = Decimal("160")

    projection = project(series, AUGUST, AS_OF)

    assert projection is not None
    # Aug 1-20: 14 weekdays (one at 160) and 6 weekend days.
    assert projection.mtd == Decimal("13") * 100 + 160 + Decimal("6") * 20
    assert [d.day.isoformat() for d in projection.days][:2] == ["2026-08-21", "2026-08-22"]
    assert len(projection.days) == 11
    friday = projection.days[0]
    # Expected from 4 weeks: Aug 14 (160), Aug 7, Jul 31, Jul 24 (100): median 100. Band from
    # 8 Fridays (one at 160, seven at 100): p10 100, p90 100 + 60 x 0.3 = 118, not the max.
    assert (friday.expected, friday.low, friday.high, friday.samples) == (
        Decimal("100"),
        Decimal("100"),
        Decimal("118"),
        8,
    )
    saturday = projection.days[1]
    assert (saturday.expected, saturday.low, saturday.high) == (
        Decimal("20"),
        Decimal("20"),
        Decimal("20"),
    )
    # Remaining: 7 weekdays and 4 weekend days at their medians.
    assert projection.projected_total == projection.mtd + 7 * 100 + 4 * 20
    assert projection.low == projection.projected_total
    # Aug 28 sees 7 Fridays (Aug 21 is in the future): p90 = 100 + 60 x 0.4 = 124.
    assert projection.days[7].samples == 7
    assert projection.high == projection.projected_total + 18 + 24


def test_band_falls_back_to_min_and_max_with_fewer_than_six_samples() -> None:
    # Five weeks of history: 5 Friday samples, below the 6 the percentiles need.
    series: dict[date, Decimal] = {}
    day = date(2026, 7, 16)
    while day <= AS_OF:
        series[day] = Decimal("20") if day.weekday() >= 5 else Decimal("100")
        day = date.fromordinal(day.toordinal() + 1)
    series[date(2026, 8, 14)] = Decimal("160")

    projection = project(series, AUGUST, AS_OF)

    assert projection is not None
    friday = projection.days[0]
    assert (friday.expected, friday.low, friday.high, friday.samples) == (
        Decimal("100"),
        Decimal("100"),
        Decimal("160"),
        4,
    )


def test_project_only_samples_days_known_through_as_of() -> None:
    # A series that started on Aug 18: the Friday Aug 21 has no earlier Friday, so its
    # expected amount is 0 and the band collapses; Aug 25 (Tuesday) sees Aug 18.
    series = {
        date(2026, 8, 18): Decimal("30"),
        date(2026, 8, 19): Decimal("30"),
        AS_OF: Decimal("30"),
    }

    projection = project(series, AUGUST, AS_OF)

    assert projection is not None
    assert projection.mtd == Decimal("90")
    by_day = {d.day: d for d in projection.days}
    assert by_day[date(2026, 8, 21)].expected == Decimal("0")
    assert by_day[date(2026, 8, 25)].expected == Decimal("30")
    assert by_day[date(2026, 8, 28)].expected == Decimal("0")


def test_project_returns_none_without_month_to_date_spend() -> None:
    assert project({date(2026, 7, 3): Decimal("5")}, AUGUST, AS_OF) is None


def test_run_projection_stores_every_series_for_the_current_month(
    db_session: Session, org_id: int
) -> None:
    seed_days(db_session, org_id, PROVIDER, HISTORY_START, date(2026, 8, 21), steady)

    result = run_projection(db_session, org_id, PROVIDER, AUGUST, today=date(2026, 8, 21))

    assert result.as_of_day == AS_OF
    kinds = sorted((p.series_kind, p.series_id) for p in result.projections)
    assert kinds == [
        ("api_key", "apikey_a"),
        ("api_key", "apikey_b"),
        ("model", "claude-opus-4-1"),
        ("model", "claude-sonnet-4"),
        ("org", "__org__"),
        ("workspace", "ws_a"),
        ("workspace", "ws_b"),
    ]
    org = db_session.scalar(
        select(SpendProjection).where(
            SpendProjection.organization_id == org_id,
            SpendProjection.provider == PROVIDER,
            SpendProjection.month == "2026-08",
            SpendProjection.series_kind == "org",
            SpendProjection.series_id == "__org__",
        )
    )
    assert org is not None
    # Aug 1-20: 14 weekdays and 6 weekend days; 11 days remain: 7 weekdays and 4 weekend days.
    assert org.mtd == Decimal("14") * 100 + Decimal("6") * 20
    assert org.projected_total == org.mtd + 7 * 100 + 4 * 20
    assert org.low == org.high == org.projected_total
    assert org.as_of_day == AS_OF
    assert len(org.days) == 11
    assert org.days[0] == {
        "day": "2026-08-21",
        "expected": "100.00000000",
        "low": "100.00000000",
        "high": "100.00000000",
        "samples": 8,
    }
    assert org.currency == "USD"

    # A second run replaces the rows instead of duplicating them.
    run_projection(db_session, org_id, PROVIDER, AUGUST, today=date(2026, 8, 21))
    assert len(list(db_session.scalars(select(SpendProjection)))) == 7


def test_run_projection_clears_rows_for_a_closed_month(db_session: Session, org_id: int) -> None:
    seed_days(db_session, org_id, PROVIDER, HISTORY_START, date(2026, 8, 21), steady)
    run_projection(db_session, org_id, PROVIDER, AUGUST, today=date(2026, 8, 21))
    assert len(list(db_session.scalars(select(SpendProjection)))) == 7

    closed = run_projection(db_session, org_id, PROVIDER, AUGUST, today=date(2026, 9, 14))

    assert closed.projections == []
    assert list(db_session.scalars(select(SpendProjection))) == []


def test_run_projection_leaves_todays_partial_day_out(db_session: Session, org_id: int) -> None:
    seed_days(db_session, org_id, PROVIDER, HISTORY_START, date(2026, 8, 21), steady)
    result = run_projection(db_session, org_id, PROVIDER, AUGUST, today=date(2026, 8, 21))
    assert result.as_of_day == date(2026, 8, 20)
    org = next(p for p in result.projections if p.series_kind == "org")
    assert org.days[0].day == date(2026, 8, 21)
