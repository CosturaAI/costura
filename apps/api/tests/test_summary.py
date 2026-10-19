from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from costura.providers.anthropic.client import AnthropicAdminClient
from costura.providers.anthropic.sync import run_cost_sync, run_usage_sync
from costura.spend.allocate import run_allocation
from costura.spend.ledger import costura_total
from costura.spend.summary import previous_month, summary
from costura.spend.window import Window, comparison_window
from tests.conftest import ORG_ID, SAMPLE_TODAY, seed_sample, target
from tests.support.spend import AUGUST, FIXTURE_END, FIXTURE_START


def test_previous_month_wraps_the_year() -> None:
    assert previous_month("2026-08") == "2026-07"
    assert previous_month("2026-01") == "2025-12"


def test_projection_only_for_the_current_month(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    run_cost_sync(
        db_session,
        target(db_session, ORG_ID, "anthropic"),
        anthropic_client,
        FIXTURE_START,
        FIXTURE_END,
    )
    run_usage_sync(
        db_session,
        target(db_session, ORG_ID, "anthropic"),
        anthropic_client,
        FIXTURE_START,
        FIXTURE_END,
    )
    run_allocation(db_session, ORG_ID, "anthropic", AUGUST)

    closed = summary(
        db_session, org_id=ORG_ID, provider="anthropic", month="2026-08", today=date(2026, 9, 14)
    )
    assert closed.is_current_month is False
    assert closed.projected_total is None
    # Anthropic reports no BYOK figure, so the summary carries none rather than zero.
    assert closed.byok_total is None
    assert closed.last_day_with_data is not None
    elapsed = (closed.last_day_with_data - date(2026, 8, 1)).days + 1
    assert closed.daily_average == (closed.total / elapsed).quantize(Decimal("0.01"))

    open_month = summary(
        db_session, org_id=ORG_ID, provider="anthropic", month="2026-08", today=date(2026, 8, 20)
    )
    assert open_month.is_current_month is True
    assert open_month.projected_total == (open_month.total / elapsed * 31).quantize(Decimal("0.01"))
    assert open_month.projected_total > open_month.total


def test_a_month_in_progress_compares_with_the_same_days_of_the_month_before() -> None:
    october = Window.for_month("2026-10")
    assert comparison_window(october, "2026-10", through=date(2026, 10, 14)) == (
        Window.for_dates(date(2026, 9, 1), date(2026, 9, 14))
    )
    assert comparison_window(october, "2026-10", through=date(2026, 10, 31)) == (
        Window.for_month("2026-09")
    )
    march = Window.for_month("2026-03")
    assert comparison_window(march, "2026-03", through=date(2026, 3, 30)) == (
        Window.for_month("2026-02")
    )
    assert comparison_window(october, "2026-10") == Window.for_month("2026-09")


def test_a_range_still_compares_with_the_days_right_before_it() -> None:
    days = Window.for_dates(date(2026, 10, 5), date(2026, 10, 14))
    assert comparison_window(days, "2026-10", through=date(2026, 10, 14)) == days.preceding()


def test_summary_of_a_month_in_progress_compares_like_for_like(db_session: Session) -> None:
    org_id = seed_sample(db_session).organization.id
    current = summary(
        db_session, org_id=org_id, provider="all", month="2026-09", today=SAMPLE_TODAY
    )
    assert current.is_current_month is True
    assert current.last_day_with_data is not None
    assert current.comparison_basis == "month_to_date"
    assert current.previous_start == date(2026, 8, 1)
    assert current.previous_end == date(2026, 8, current.last_day_with_data.day)
    same_days, _ = costura_total(
        db_session,
        org_id,
        "all",
        Window.for_dates(current.previous_start, current.previous_end),
    )
    assert current.previous_total == same_days
    assert current.change_percent == ((current.total - same_days) / same_days * 100).quantize(
        Decimal("0.01")
    )

    closed = summary(db_session, org_id=org_id, provider="all", month="2026-08", today=SAMPLE_TODAY)
    assert closed.comparison_basis == "full_month"
    assert (closed.previous_start, closed.previous_end) == (date(2026, 7, 1), date(2026, 7, 31))


def test_a_month_in_progress_without_data_has_no_change(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    run_cost_sync(
        db_session,
        target(db_session, ORG_ID, "anthropic"),
        anthropic_client,
        FIXTURE_START,
        FIXTURE_END,
    )
    september = summary(
        db_session, org_id=ORG_ID, provider="anthropic", month="2026-09", today=date(2026, 9, 3)
    )
    assert september.comparison_basis == "month_to_date"
    assert (september.previous_start, september.previous_end) == (
        date(2026, 8, 1),
        date(2026, 8, 1),
    )
    assert september.previous_total is not None
    assert september.change_percent is None
