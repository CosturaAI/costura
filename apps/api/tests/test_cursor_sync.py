"""Cursor normalization, member inventory, sync, direct allocation, and origin queries."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura import accounts
from costura.models import (
    ProviderAccount,
    ProviderReportPage,
    ProviderUser,
    SpendAllocatedLine,
    SpendCostLine,
    SpendUsageLine,
)
from costura.models.allocation import ALLOCATION_METHOD_PROVIDER_ATTRIBUTED
from costura.providers.cursor.client import CursorAdminClient
from costura.providers.cursor.inventory import run_inventory_sync, users_from_payload
from costura.providers.cursor.normalize import (
    UserDirectory,
    lines_from_events,
    page_amount,
    parse_event_time,
    seat_lines_from_daily_usage,
    spend_control_total,
)
from costura.providers.cursor.sync import ENDPOINT_COST, run_cost_sync
from costura.providers.lines import NormalizeError
from costura.spend.allocate import run_allocation
from costura.spend.query import QuerySpec, query_spend
from costura.spend.usage import usage_report
from costura.spend.window import Window
from tests.conftest import ORG_ID, load_fixture, target
from tests.support.runs import cost_total, usage_total

PROVIDER = "cursor"
START = datetime(2026, 8, 1, tzinfo=UTC)
END = datetime(2026, 8, 3, tzinfo=UTC)
TOTAL = Decimal("0.9089164")


def test_cursor_settings_preserve_history_and_move_price_changes_forward(
    db_session: Session,
) -> None:
    unit = target(db_session, ORG_ID, PROVIDER)
    account = db_session.get(ProviderAccount, unit.account_id)
    assert account is not None

    configured = accounts.set_cursor_settings(
        account,
        seat_price_usd=Decimal("30"),
        include_included_in_business=True,
    )
    initial_boundary = max(datetime.now(UTC).date(), account.created_at.date())
    assert configured.effective_from == initial_boundary

    configured = accounts.set_cursor_settings(
        account,
        seat_price_usd=Decimal("30"),
        include_included_in_business=False,
    )
    assert configured.effective_from == initial_boundary
    assert configured.include_included_in_business is False

    configured = accounts.set_cursor_settings(
        account,
        seat_price_usd=Decimal("40"),
        include_included_in_business=False,
    )
    assert configured.effective_from == datetime.now(UTC).date() + timedelta(days=1)


def test_member_inventory_uses_ids_emails_roles_and_removed_state(
    db_session: Session, cursor_client: CursorAdminClient
) -> None:
    records = users_from_payload(load_fixture("members.json", PROVIDER))
    assert [(row.external_id, row.email, row.role) for row in records] == [
        ("user_alex", "developer@example.com", "member"),
        ("user_admin", "admin@example.com", "owner"),
    ]

    summaries = run_inventory_sync(db_session, target(db_session, ORG_ID, PROVIDER), cursor_client)
    [summary] = summaries

    assert summary.endpoint == "members"
    assert summary.items == 3 and summary.rows_upserted == 2
    users = db_session.scalars(select(ProviderUser).where(ProviderUser.provider == PROVIDER)).all()
    assert {(user.external_id, user.email, user.kind) for user in users} == {
        ("user_alex", "developer@example.com", "user"),
        ("user_admin", "admin@example.com", "user"),
    }
    assert {user.provider_account_id for user in users} == {
        target(db_session, ORG_ID, PROVIDER).account_id
    }


def test_events_normalize_hourly_rows_to_daily_user_model_kind_lines() -> None:
    first = load_fixture("usage_page1.json", PROVIDER)
    directory = UserDirectory.from_rows(
        [("developer@example.com", "user_alex"), ("admin@example.com", "user_admin")]
    )
    cost, usage, services = lines_from_events(first["usageEvents"], directory)

    assert len(cost) == len(usage) == 3
    assert all(line.period_start == START for line in [*cost, *usage])
    assert usage[0].account_id == "user_alex"
    assert usage[0].service_tier == "Usage-based"
    assert usage[0].amount == Decimal("0.2136232")
    assert (
        usage[0].uncached_input_tokens,
        usage[0].cache_creation_5m_tokens,
        usage[0].cache_read_tokens,
        usage[0].output_tokens,
    ) == (126, 6112, 11964, 450)
    assert usage[0].account_id == "user_alex"
    assert {(service.external_id, service.email, service.kind) for service in services} == {
        ("sa_nightly", "Nightly CI Agent", "service_account")
    }
    assert cost[0].description == cost[0].service_tier == "Usage-based"
    assert cost[0].raw_amount_minor == "21.36232"


def test_included_business_filter_applies_to_backfills() -> None:
    payload = load_fixture("usage_page1.json", PROVIDER)
    events = [
        *payload["usageEvents"],
        {**payload["usageEvents"][0], "kind": "Included in Business"},
    ]
    directory = UserDirectory.from_rows([])
    included, _, _ = lines_from_events(events, directory)
    excluded, usage, _ = lines_from_events(
        events,
        directory,
        include_included_in_business=False,
    )

    assert len(excluded) < len(included)
    assert all(line.service_tier != "Included in Business" for line in [*excluded, *usage])


def test_seat_lines_are_daily_prorated_and_member_attributed_without_double_counting() -> None:
    directory = UserDirectory.from_rows([("a@example.com", "user_a"), ("b@example.com", "user_b")])
    rows = [
        {"day": "2026-09-18", "email": "a@example.com", "isActive": True},
        {"day": "2026-09-18", "email": "b@example.com", "isActive": False},
        {"day": "2026-09-18", "email": "a@example.com", "isActive": True},
        {"day": "2026-09-17", "email": "a@example.com", "isActive": True},
    ]

    cost, usage = seat_lines_from_daily_usage(
        rows,
        directory,
        seat_price_usd=Decimal("30"),
        effective_from=date(2026, 9, 18),
    )

    assert len(cost) == 1 and cost[0].cost_type == "seat"
    assert cost[0].amount == Decimal("2")
    assert len(usage) == 2
    assert {line.account_id for line in usage} == {"user_a", "user_b"}
    assert sum((line.amount or Decimal("0") for line in usage), Decimal("0")) == cost[0].amount


def test_spend_control_total_selects_overall_or_on_demand_without_seats() -> None:
    payload = {
        "teamMemberSpend": [
            {"spendCents": 100, "includedSpendCents": 150},
            {"spendCents": 50, "includedSpendCents": 25},
        ]
    }
    assert spend_control_total(payload, {"_costura_control_field": "spendCents"}) == Decimal("1.5")
    assert spend_control_total(payload, {"_costura_control_field": "overallSpendCents"}) == Decimal(
        "3.25"
    )
    overall_payload = {
        "teamMemberSpend": [
            {"spendCents": 100, "overallSpendCents": 250},
            {"spendCents": 50, "overallSpendCents": 75},
        ]
    }
    assert spend_control_total(
        overall_payload, {"_costura_control_field": "overallSpendCents"}
    ) == Decimal("3.25")


@pytest.mark.parametrize("value", [None, "not-ms", True])
def test_events_reject_invalid_timestamps(value: object) -> None:
    with pytest.raises(NormalizeError, match="timestamp"):
        parse_event_time(value)


def test_cost_sync_is_idempotent_and_creates_service_accounts(
    db_session: Session, cursor_client: CursorAdminClient
) -> None:
    unit = target(db_session, ORG_ID, PROVIDER)
    run_inventory_sync(db_session, unit, cursor_client)
    summary = run_cost_sync(db_session, unit, cursor_client, START, END)

    assert summary.endpoint == ENDPOINT_COST
    assert summary.pages_fetched == 2 and summary.raw_results == 5
    assert summary.rows_upserted == 9
    assert cost_total(db_session, summary.run_id) == TOTAL
    assert usage_total(db_session, summary.run_id, "request_count") == 5
    assert db_session.scalar(select(func.count()).select_from(SpendCostLine)) == 3
    assert db_session.scalar(select(func.count()).select_from(SpendUsageLine)) == 4
    service = db_session.scalar(
        select(ProviderUser).where(ProviderUser.external_id == "sa_nightly")
    )
    assert service is not None and service.kind == "service_account"
    assert service.provider_account_id == unit.account_id
    event_user = db_session.scalar(
        select(ProviderUser).where(ProviderUser.external_id == "new@example.com")
    )
    assert event_user is not None and event_user.kind == "user"
    run_inventory_sync(db_session, unit, cursor_client)
    db_session.refresh(service)
    assert service.missing_since is None

    alex = db_session.scalar(select(SpendUsageLine).where(SpendUsageLine.account_id == "user_alex"))
    assert alex is not None
    assert Decimal(alex.amount) == Decimal("0.6152932")
    assert alex.request_count == 2
    assert alex.cache_creation_5m_tokens == 18076
    assert page_amount(load_fixture("usage_page1.json", PROVIDER), START, END) == Decimal(
        "0.8289164"
    )

    before = (
        db_session.scalar(select(func.count()).select_from(SpendCostLine)),
        db_session.scalar(select(func.count()).select_from(SpendUsageLine)),
    )
    stale = db_session.scalar(
        select(SpendUsageLine).where(SpendUsageLine.account_id == "user_alex")
    )
    assert stale is not None
    stale.account_id = "null"
    db_session.add(
        ProviderUser(
            organization_id=ORG_ID,
            provider=PROVIDER,
            provider_account_id=unit.account_id,
            external_id="null",
            email="null",
            role="service_account",
            kind="service_account",
            sync_run_id=summary.run_id,
        )
    )
    db_session.flush()
    again = run_cost_sync(db_session, unit, cursor_client, START, END)
    assert (
        db_session.scalar(select(func.count()).select_from(SpendCostLine)),
        db_session.scalar(select(func.count()).select_from(SpendUsageLine)),
    ) == before
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(SpendUsageLine)
            .where(SpendUsageLine.account_id == "null")
        )
        == 0
    )
    assert (
        db_session.scalar(
            select(func.count()).select_from(ProviderUser).where(ProviderUser.external_id == "null")
        )
        == 0
    )
    assert again.run_id != summary.run_id
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(ProviderReportPage)
            .where(
                ProviderReportPage.provider == PROVIDER,
                ProviderReportPage.endpoint == ENDPOINT_COST,
            )
        )
        == 4
    )


def test_account_only_direct_allocation_people_and_origin_query(
    db_session: Session, cursor_client: CursorAdminClient
) -> None:
    unit = target(db_session, ORG_ID, PROVIDER)
    run_inventory_sync(db_session, unit, cursor_client)
    run_cost_sync(db_session, unit, cursor_client, START, END)
    window = Window(start=START, end=END)

    allocation = run_allocation(db_session, ORG_ID, PROVIDER, window, account_id=unit.account_id)

    assert allocation.balanced
    assert allocation.cost_total == allocation.allocated_total == TOTAL
    assert allocation.unallocated_total == 0
    allocated = db_session.scalars(select(SpendAllocatedLine)).all()
    assert all(row.api_key_id is None for row in allocated)
    assert {row.method for row in allocated} == {ALLOCATION_METHOD_PROVIDER_ATTRIBUTED}
    assert {row.account_id for row in allocated} == {
        "user_alex",
        "user_admin",
        "sa_nightly",
        "new@example.com",
    }

    people = usage_report(
        db_session,
        org_id=ORG_ID,
        provider=PROVIDER,
        window=window,
        dimension="person",
    )
    alex = next(row for row in people.rows if row.key == "developer@example.com")
    assert alex.person == "developer@example.com"
    assert alex.amount == Decimal("0.6152932")
    new_user = next(row for row in people.rows if row.key == "new@example.com")
    assert new_user.person == "new@example.com"

    keys = usage_report(
        db_session,
        org_id=ORG_ID,
        provider=PROVIDER,
        window=window,
        dimension="api_key",
    )
    direct = next(row for row in keys.rows if row.key is None)
    assert direct.label == "(direct user usage, no API key)"

    result = query_spend(
        db_session,
        org_id=ORG_ID,
        spec=QuerySpec(
            measure="billed_usd",
            dimensions=("origin",),
            filters={"origin": "Cursor"},
            start=START.date(),
            end=(END.date()),
            interval="day",
            top=10,
        ),
    )
    assert result.series[0].keys == {"origin": "Cursor"}
    assert result.series[0].labels == {"origin": "Cursor"}
    assert result.series[0].total == TOTAL


def test_direct_allocation_records_no_user_remainder(
    db_session: Session, cursor_client: CursorAdminClient
) -> None:
    unit = target(db_session, ORG_ID, PROVIDER)
    run_inventory_sync(db_session, unit, cursor_client)
    run_cost_sync(db_session, unit, cursor_client, START, END)
    alex = db_session.scalar(select(SpendUsageLine).where(SpendUsageLine.account_id == "user_alex"))
    assert alex is not None
    alex.amount = Decimal(alex.amount) - Decimal("0.1")
    db_session.commit()

    allocation = run_allocation(
        db_session,
        ORG_ID,
        PROVIDER,
        Window(start=START, end=END),
        account_id=unit.account_id,
    )

    assert allocation.balanced
    assert allocation.unallocated_total == Decimal("0.1")
    assert allocation.unallocated_by_reason == {"no_user": Decimal("0.1")}
    remainder = db_session.scalar(
        select(SpendAllocatedLine).where(SpendAllocatedLine.unallocated_reason == "no_user")
    )
    assert remainder is not None
    assert remainder.account_id is None and Decimal(remainder.amount) == Decimal("0.1")
