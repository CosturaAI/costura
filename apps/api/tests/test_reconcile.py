from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from costura.models import ProviderReportPage, ProviderSyncRun, SpendCostLine
from costura.providers.anthropic.client import AnthropicAdminClient
from costura.providers.anthropic.inventory import run_inventory_sync
from costura.providers.anthropic.sync import run_cost_sync, run_cost_total_sync, run_usage_sync
from costura.spend.allocate import run_allocation
from costura.spend.ledger import breakdown
from costura.spend.provider_totals import provider_total_of_latest_run
from costura.spend.reconcile import reconcile
from costura.spend.window import Window
from tests.conftest import ORG_ID, account_of, target
from tests.support.spend import AUGUST, FIXTURE_END, FIXTURE_START
from tests.test_anthropic_normalize import COST_FIXTURE_TOTAL, USAGE_FIXTURE_TOTALS


def _add_cost_line(session: Session, period_start: datetime, amount: str) -> None:
    account_id = account_of(session, ORG_ID, "anthropic")
    run = ProviderSyncRun(
        organization_id=ORG_ID,
        provider="anthropic",
        provider_account_id=account_id,
        endpoint="cost_report",
        window_start=period_start,
        window_end=period_start,
        status="succeeded",
    )
    session.add(run)
    session.flush()
    session.add(
        SpendCostLine(
            organization_id=ORG_ID,
            provider="anthropic",
            provider_account_id=account_id,
            period_start=period_start,
            period_end=period_start,
            workspace_id=None,
            description="manual",
            cost_type="tokens",
            model="m",
            token_type="output_tokens",
            service_tier="standard",
            context_window="0-200k",
            inference_geo="global",
            amount=Decimal(amount),
            currency="USD",
            raw_amount_minor=amount,
            sync_run_id=run.id,
        )
    )
    session.commit()


def test_window_for_month_is_half_open_utc() -> None:
    assert AUGUST.start == datetime(2026, 8, 1, tzinfo=UTC)
    assert AUGUST.end == datetime(2026, 9, 1, tzinfo=UTC)
    assert len(list(AUGUST.days())) == 31
    assert Window.for_month("2026-02").end == datetime(2026, 3, 1, tzinfo=UTC)
    with pytest.raises(ValueError):
        Window.for_month("2026-13")


def test_window_for_dates_cuts_at_months_and_precedes_by_its_length() -> None:
    from datetime import date

    span = Window.for_dates(date(2026, 7, 15), date(2026, 9, 2))
    assert span.last_day == date(2026, 9, 2)
    assert [(p.start.date(), p.last_day) for p in span.month_parts()] == [
        (date(2026, 7, 15), date(2026, 7, 31)),
        (date(2026, 8, 1), date(2026, 8, 31)),
        (date(2026, 9, 1), date(2026, 9, 2)),
    ]
    assert AUGUST.month_parts() == [AUGUST]
    before = span.preceding()
    assert (before.start.date(), before.last_day) == (date(2026, 5, 26), date(2026, 7, 14))
    with pytest.raises(ValueError):
        Window.for_dates(date(2026, 8, 2), date(2026, 8, 1))


def test_cursor_provider_total_is_current_cycle_only(db_session: Session) -> None:
    now = datetime.now(UTC)
    current = Window.for_month(f"{now.year:04d}-{now.month:02d}")
    previous_day = current.start.replace(day=1) - timedelta(days=1)
    previous = Window.for_month(f"{previous_day.year:04d}-{previous_day.month:02d}")
    account_id = account_of(db_session, ORG_ID, "cursor")
    run = ProviderSyncRun(
        organization_id=ORG_ID,
        provider="cursor",
        provider_account_id=account_id,
        endpoint="spend",
        window_start=current.start,
        window_end=now,
        status="succeeded",
    )
    db_session.add(run)
    db_session.flush()
    db_session.add(
        ProviderReportPage(
            organization_id=ORG_ID,
            sync_run_id=run.id,
            provider="cursor",
            endpoint="spend",
            page_index=0,
            request_params={"_costura_control_field": "overallSpendCents"},
            payload={"teamMemberSpend": [{"overallSpendCents": 1234}]},
        )
    )
    db_session.commit()

    current_run, current_total = provider_total_of_latest_run(
        db_session, ORG_ID, "cursor", current, account_id
    )
    old_run, old_total = provider_total_of_latest_run(
        db_session, ORG_ID, "cursor", previous, account_id
    )

    assert current_run == run.id
    assert current_total == Decimal("12.34")
    assert (old_run, old_total) == (None, None)


def test_month_total_delta_and_match(
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

    exact = reconcile(
        db_session,
        org_id=ORG_ID,
        provider="anthropic",
        window=AUGUST,
        reported_total=Decimal("64.62"),
    )
    assert exact.costura_total == COST_FIXTURE_TOTAL
    assert exact.currency == "USD"
    assert exact.delta == Decimal("-0.005")
    assert exact.matches is True
    assert exact.token_totals == USAGE_FIXTURE_TOTALS

    off = reconcile(
        db_session, org_id=ORG_ID, provider="anthropic", window=AUGUST, reported_total=Decimal("70")
    )
    assert off.delta == Decimal("-5.385")
    assert off.delta_percent == Decimal("-7.69")
    assert off.matches is False


def test_breakdown_by_day_covers_every_day_of_the_month(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    run_cost_sync(
        db_session,
        target(db_session, ORG_ID, "anthropic"),
        anthropic_client,
        FIXTURE_START,
        FIXTURE_END,
    )

    rows = breakdown(db_session, ORG_ID, "anthropic", AUGUST, "day")

    assert [row.label for row in rows][:3] == ["2026-08-01", "2026-08-02", "2026-08-03"]
    assert len(rows) == 31
    assert rows[0].amount == Decimal("13.7428912")  # 123.78912 + 250.5 + 1000 cents
    assert rows[1].amount == Decimal("0.7621088")
    assert rows[2].amount == Decimal("50.11")  # 10.5 + 0.5 + 5000 cents
    assert all(row.amount == 0 for row in rows[3:])
    assert sum((row.amount for row in rows), Decimal("0")) == COST_FIXTURE_TOTAL


def test_breakdown_by_workspace_labels_default_workspace(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    run_cost_sync(
        db_session,
        target(db_session, ORG_ID, "anthropic"),
        anthropic_client,
        FIXTURE_START,
        FIXTURE_END,
    )

    by_workspace = breakdown(db_session, ORG_ID, "anthropic", AUGUST, "workspace")
    rows = {row.label: row.amount for row in by_workspace}

    assert rows == {
        "wrkspc_redacted_a (not in inventory)": Decimal("60.11"),
        "(default workspace)": Decimal("4.505"),
    }


def test_allocation_check_missing_then_ok(
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

    before = reconcile(
        db_session,
        org_id=ORG_ID,
        provider="anthropic",
        window=AUGUST,
        reported_total=Decimal("64.615"),
    )
    assert before.allocation is None

    summary = run_allocation(db_session, ORG_ID, "anthropic", AUGUST)
    after = reconcile(
        db_session,
        org_id=ORG_ID,
        provider="anthropic",
        window=AUGUST,
        reported_total=Decimal("64.615"),
    )

    assert after.allocation is not None
    assert after.allocation.run_id == summary.run_id
    assert after.allocation.allocated_total == Decimal("53.7428912")
    assert after.allocation.unallocated_total == Decimal("10.8721088")
    assert after.allocation.unallocated_by_reason == {"no_usage": Decimal("10.8721088")}
    assert after.allocation.delta(after.costura_total) == Decimal("0")


def test_breakdown_by_workspace_uses_inventory_names(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    run_cost_sync(
        db_session,
        target(db_session, ORG_ID, "anthropic"),
        anthropic_client,
        FIXTURE_START,
        FIXTURE_END,
    )
    run_inventory_sync(db_session, target(db_session, ORG_ID, "anthropic"), anthropic_client)

    labels = [row.label for row in breakdown(db_session, ORG_ID, "anthropic", AUGUST, "workspace")]

    assert labels == ["Platform (wrkspc_redacted_a)", "(default workspace)"]


def test_breakdown_rejects_unknown_dimension(db_session: Session) -> None:
    with pytest.raises(ValueError, match="unknown dimension"):
        breakdown(db_session, ORG_ID, "anthropic", AUGUST, "colour")


def test_utc_month_boundary(db_session: Session) -> None:
    _add_cost_line(db_session, datetime(2026, 8, 31, tzinfo=UTC), "1")
    _add_cost_line(db_session, datetime(2026, 9, 1, tzinfo=UTC), "100")
    _add_cost_line(db_session, datetime(2026, 7, 31, 23, 59, 59, tzinfo=UTC), "1000")

    report = reconcile(
        db_session, org_id=ORG_ID, provider="anthropic", window=AUGUST, reported_total=Decimal("1")
    )

    assert report.costura_total == Decimal("1")
    assert report.matches is True
    assert report.latest_run_id is None
    assert report.raw_vs_normalized_delta is None


def test_raw_vs_normalized_is_zero_after_sync(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    partial = run_cost_sync(
        db_session,
        target(db_session, ORG_ID, "anthropic"),
        anthropic_client,
        FIXTURE_START,
        FIXTURE_END,
    )
    report = reconcile(
        db_session,
        org_id=ORG_ID,
        provider="anthropic",
        window=AUGUST,
        reported_total=COST_FIXTURE_TOTAL,
    )
    # A run whose window does not cover the month is not used for the raw check.
    assert report.latest_run_id is None

    covering = run_cost_sync(
        db_session,
        target(db_session, ORG_ID, "anthropic"),
        anthropic_client,
        AUGUST.start,
        AUGUST.end,
    )
    report = reconcile(
        db_session,
        org_id=ORG_ID,
        provider="anthropic",
        window=AUGUST,
        reported_total=COST_FIXTURE_TOTAL,
    )

    assert covering.run_id != partial.run_id
    assert report.latest_run_id == covering.run_id
    assert report.raw_total_latest_run == COST_FIXTURE_TOTAL
    assert report.raw_vs_normalized_delta == 0
    assert report.matches is True


def test_provider_total_check_missing_then_ok_then_mismatch(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    run_cost_sync(
        db_session,
        target(db_session, ORG_ID, "anthropic"),
        anthropic_client,
        AUGUST.start,
        AUGUST.end,
    )
    report = reconcile(
        db_session, org_id=ORG_ID, provider="anthropic", window=AUGUST, reported_total=Decimal(0)
    )
    assert report.provider_total_run_id is None
    assert report.provider_delta is None and report.provider_matches is None

    total_run = run_cost_total_sync(
        db_session,
        target(db_session, ORG_ID, "anthropic"),
        anthropic_client,
        AUGUST.start,
        AUGUST.end,
    )
    report = reconcile(
        db_session, org_id=ORG_ID, provider="anthropic", window=AUGUST, reported_total=Decimal(0)
    )
    assert report.provider_total_run_id == total_run.run_id
    assert report.provider_total_latest_run == COST_FIXTURE_TOTAL
    assert report.provider_delta == 0 and report.provider_matches is True

    # The provider's own total moves while the stored rows do not: the check fails.
    page = db_session.scalars(
        select(ProviderReportPage).where(ProviderReportPage.sync_run_id == total_run.run_id)
    ).one()
    payload = dict(page.payload)
    payload["data"] = [dict(b) for b in payload["data"]]
    payload["data"][0] = {**payload["data"][0], "results": [{"amount": "5000", "currency": "USD"}]}
    page.payload = payload
    db_session.commit()
    report = reconcile(
        db_session, org_id=ORG_ID, provider="anthropic", window=AUGUST, reported_total=Decimal(0)
    )
    assert report.provider_matches is False
    assert report.provider_delta is not None and report.provider_delta < 0
