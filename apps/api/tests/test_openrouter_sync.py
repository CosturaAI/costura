"""OpenRouter normalize, inventory, cost sync (idempotent), direct attribution, reconcile."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura import accounts
from costura.models import (
    ProviderApiKey,
    ProviderReportPage,
    ProviderSyncRun,
    ProviderUser,
    ProviderWorkspace,
    SpendAllocatedLine,
    SpendCostLine,
    SpendUsageLine,
)
from costura.models.allocation import ALLOCATION_METHOD_PROVIDER_ATTRIBUTED
from costura.providers.lines import NormalizeError
from costura.providers.openrouter.client import OpenRouterManagementClient
from costura.providers.openrouter.inventory import (
    ENDPOINT_USERS,
    ENDPOINT_WORKSPACE_MEMBERS,
    run_inventory_sync,
)
from costura.providers.openrouter.normalize import (
    KeyDirectory,
    KeyRef,
    billed_amount,
    byok_amount,
    lines_from_rows,
    total_amounts,
)
from costura.providers.openrouter.sync import (
    ENDPOINT_COST,
    ENDPOINT_COST_TOTAL,
    page_amount,
    run_cost_sync,
    run_cost_total_sync,
)
from costura.providers.runs import Target
from costura.spend.allocate import run_allocation
from costura.spend.reconcile import reconcile
from costura.spend.summary import summary as month_summary
from costura.spend.usage import usage_report
from costura.spend.window import Window
from tests.conftest import ORG_ID, load_fixture, target
from tests.support.runs import cost_total, usage_total

PROVIDER = "openrouter"
START = datetime(2026, 8, 1, tzinfo=UTC)
END = datetime(2026, 9, 1, tzinfo=UTC)
H1, H2, H3 = "a1" * 32, "b2" * 32, "c3" * 32
WS1 = "0f0e0d0c-0000-4000-8000-000000000001"
WS2 = "0f0e0d0c-0000-4000-8000-000000000002"
# Sum of `credits_usage` (what OpenRouter bills) over the six fixture rows; `total_usage` adds
# up to 31.5 because two prod-backend rows carry 8.0 and 9.0 of BYOK inference.
FIXTURE_TOTAL = Decimal("14.5")
FIXTURE_BYOK = Decimal("17.0")


def _directory() -> KeyDirectory:
    return KeyDirectory.from_rows(
        [
            ("prod-backend", H1, WS1, "user_alice"),
            ("research", H2, WS2, "user_bob"),
            ("ci-bot", H3, WS1, "user_alice"),
        ]
    )


def test_lines_from_rows_resolve_key_names_and_split_token_subsets() -> None:
    rows = load_fixture("analytics_query_page1.json", PROVIDER)["data"]["data"]
    cost, usage = lines_from_rows(rows, _directory())

    assert len(cost) == len(usage) == 6
    first = usage[0]
    assert first.provider == PROVIDER
    assert first.period_start == START and first.period_end == datetime(2026, 8, 2, tzinfo=UTC)
    assert first.api_key_id == H1 and first.account_id == "user_alice" and first.workspace_id == WS1
    assert first.model == "openai/gpt-5.2" and first.service_tier == "standard"
    # 1,000,000 prompt of which 400,000 cached; 200,000 completion, no reasoning.
    assert (first.uncached_input_tokens, first.cache_read_tokens) == (600_000, 400_000)
    assert (first.output_tokens, first.reasoning_tokens) == (200_000, 0)
    # total_usage 10.5 = credits_usage 2.5 + byok_usage 8.0: the cost is what OpenRouter bills.
    assert first.request_count == 120 and first.amount == Decimal("2.5")
    assert first.byok_amount == Decimal("8.0")

    grok = next(u for u in usage if u.model.startswith("x-ai/") and u.period_start == START)
    assert (grok.output_tokens, grok.reasoning_tokens) == (20_000, 20_000)
    assert grok.amount == Decimal("2.0") and grok.byok_amount == Decimal("0")

    # A name with no current key keeps the name as id; nothing is dropped.
    old = next(u for u in usage if u.api_key_id == "old-key")
    assert old.workspace_id is None and old.account_id is None and old.amount == Decimal("1.25")

    line = cost[0]
    assert line.provider == PROVIDER and line.workspace_id == WS1
    assert (line.description, line.cost_type, line.token_type) == ("credits", "tokens", None)
    assert line.amount == Decimal("2.5") and line.currency == "USD"
    assert line.raw_amount_minor == "2.5"
    assert sum(c.amount for c in cost) == FIXTURE_TOTAL
    assert sum(u.byok_amount for u in usage) == FIXTURE_BYOK
    assert sum(total_amounts(rows)) == FIXTURE_TOTAL


def test_billed_amount_reads_credits_usage() -> None:
    row = {
        "date__day": "2026-08-01",
        "api_key_id": "k",
        "model": "m",
        "total_usage": 3.75,
        "credits_usage": 1.0,
        "byok_usage": 2.75,
    }
    assert billed_amount(row) == Decimal("1.0")
    assert byok_amount(row) == Decimal("2.75")
    cost, usage = lines_from_rows([row], _directory())
    assert cost[0].amount == Decimal("1.0") and cost[0].raw_amount_minor == "1.0"
    assert usage[0].amount == Decimal("1.0") and usage[0].byok_amount == Decimal("2.75")

    without = {"date__day": "2026-08-01", "api_key_id": "k", "model": "m", "total_usage": 3.75}
    assert byok_amount(without) is None
    with pytest.raises(NormalizeError, match="credits_usage"):
        billed_amount(without)
    with pytest.raises(NormalizeError):
        lines_from_rows([without], _directory())


def test_page_amount_sums_credits_usage() -> None:
    payload = load_fixture("analytics_total.json", PROVIDER)
    assert page_amount(payload, START, END) == FIXTURE_TOTAL
    assert page_amount(payload, START, datetime(2026, 8, 2, tzinfo=UTC)) == Decimal("8.75")


def test_key_directory_treats_duplicate_names_as_unknown() -> None:
    directory = KeyDirectory.from_rows([("dup", "h1", WS1, None), ("dup", "h2", WS2, None)])
    assert directory.resolve("dup") == KeyRef("dup", None, None)


def test_inventory_sync_for_a_personal_account(
    db_session: Session, openrouter_client: OpenRouterManagementClient
) -> None:
    summaries = run_inventory_sync(
        db_session, target(db_session, ORG_ID, "openrouter"), openrouter_client
    )

    by_endpoint = {s.endpoint: s for s in summaries}
    assert by_endpoint["workspaces"].rows_upserted == 2
    assert by_endpoint["keys"].rows_upserted == 3
    assert by_endpoint["keys"].pages_fetched == 1  # 3 keys < page size: no second request
    assert by_endpoint[ENDPOINT_USERS].rows_upserted == 0
    assert by_endpoint[ENDPOINT_USERS].skipped_workspaces == ["organization"]
    assert by_endpoint[ENDPOINT_WORKSPACE_MEMBERS].skipped_workspaces == [WS1, WS2]

    keys = {
        k.external_id: k
        for k in db_session.scalars(
            select(ProviderApiKey).where(ProviderApiKey.provider == PROVIDER)
        )
    }
    assert keys[H3].status == "disabled" and keys[H1].status == "active"
    assert keys[H1].partial_key_hint == "sk-or-v1-a1a...1a1a"
    assert keys[H1].workspace_external_id == WS1
    assert keys[H1].created_by_external_id == "user_alice"
    workspaces = list(
        db_session.scalars(select(ProviderWorkspace).where(ProviderWorkspace.provider == PROVIDER))
    )
    assert {w.name for w in workspaces} == {"Production", "Research"}
    assert workspaces[0].tags in ({"slug": "production"}, {"slug": "research"})
    assert db_session.scalar(select(func.count()).select_from(ProviderUser)) == 0
    runs = list(
        db_session.scalars(select(ProviderSyncRun).where(ProviderSyncRun.provider == PROVIDER))
    )
    assert {r.status for r in runs} == {"succeeded"}


def test_cost_sync_is_idempotent_and_keeps_raw_pages(
    db_session: Session, openrouter_client: OpenRouterManagementClient
) -> None:
    run_inventory_sync(db_session, target(db_session, ORG_ID, "openrouter"), openrouter_client)
    summary = run_cost_sync(
        db_session, target(db_session, ORG_ID, "openrouter"), openrouter_client, START, END
    )

    assert summary.endpoint == ENDPOINT_COST
    assert summary.pages_fetched == 1 and summary.raw_results == 6
    assert summary.rows_upserted == 6 + 6
    assert cost_total(db_session, summary.run_id) == FIXTURE_TOTAL
    assert usage_total(db_session, summary.run_id, "byok_amount") == FIXTURE_BYOK
    assert usage_total(db_session, summary.run_id, "reasoning_tokens") == 35_000
    assert usage_total(db_session, summary.run_id, "request_count") == 313

    def state() -> tuple[int, Decimal, int, Decimal]:
        cost = db_session.execute(
            select(func.count(), func.coalesce(func.sum(SpendCostLine.amount), 0))
        ).one()
        usage = db_session.execute(
            select(func.count(), func.coalesce(func.sum(SpendUsageLine.amount), 0))
        ).one()
        return cost[0], Decimal(cost[1]), usage[0], Decimal(usage[1])

    first = state()
    assert first == (6, FIXTURE_TOTAL, 6, FIXTURE_TOTAL)
    again = run_cost_sync(
        db_session, target(db_session, ORG_ID, "openrouter"), openrouter_client, START, END
    )
    assert state() == first
    assert again.run_id != summary.run_id
    pages = db_session.scalar(
        select(func.count())
        .select_from(ProviderReportPage)
        .where(
            ProviderReportPage.provider == PROVIDER, ProviderReportPage.endpoint == ENDPOINT_COST
        )
    )
    assert pages == 2
    stored = db_session.scalar(
        select(ProviderReportPage.request_params).where(
            ProviderReportPage.sync_run_id == again.run_id
        )
    )
    assert stored["dimensions"] == ["api_key_id", "model"]

    usage_row = db_session.scalar(
        select(SpendUsageLine).where(
            SpendUsageLine.api_key_id == H1,
            SpendUsageLine.model == "openai/gpt-5.2",
            SpendUsageLine.period_start == START,
        )
    )
    assert usage_row is not None and usage_row.currency == "USD"
    assert Decimal(usage_row.amount) == Decimal("2.5")
    assert Decimal(usage_row.byok_amount) == Decimal("8.0")
    stored_byok = db_session.scalar(select(func.sum(SpendUsageLine.byok_amount)))
    assert Decimal(stored_byok) == FIXTURE_BYOK


@pytest.mark.integration
def test_two_openrouter_accounts_keep_rows_isolated_and_aggregate(
    db_session: Session, openrouter_client: OpenRouterManagementClient
) -> None:
    first = target(db_session, ORG_ID, PROVIDER)
    second_account = accounts.create_account(
        db_session, ORG_ID, PROVIDER, label="OpenRouter second"
    )
    db_session.commit()
    second = Target(org_id=ORG_ID, account_id=second_account.id)

    for unit in (first, second):
        run_inventory_sync(db_session, unit, openrouter_client)
        run_cost_sync(db_session, unit, openrouter_client, START, END)

    totals = dict(
        db_session.execute(
            select(
                SpendCostLine.provider_account_id,
                func.sum(SpendCostLine.amount),
            ).group_by(SpendCostLine.provider_account_id)
        ).all()
    )
    assert {key: Decimal(value) for key, value in totals.items()} == {
        first.account_id: FIXTURE_TOTAL,
        second.account_id: FIXTURE_TOTAL,
    }
    assert db_session.scalar(select(func.sum(SpendCostLine.amount))) == FIXTURE_TOTAL * 2


def test_direct_attribution_balances_and_reconciles(
    db_session: Session, openrouter_client: OpenRouterManagementClient
) -> None:
    run_inventory_sync(db_session, target(db_session, ORG_ID, "openrouter"), openrouter_client)
    run_cost_sync(
        db_session, target(db_session, ORG_ID, "openrouter"), openrouter_client, START, END
    )
    total = run_cost_total_sync(
        db_session, target(db_session, ORG_ID, "openrouter"), openrouter_client, START, END
    )
    assert total.endpoint == ENDPOINT_COST_TOTAL and total.rows_upserted == 0

    window = Window.for_month("2026-08")
    allocation = run_allocation(db_session, ORG_ID, PROVIDER, window)
    assert allocation.balanced
    assert allocation.cost_total == FIXTURE_TOTAL
    assert allocation.allocated_total == FIXTURE_TOTAL
    assert allocation.unallocated_total == 0
    rows = list(db_session.scalars(select(SpendAllocatedLine)))
    assert {r.method for r in rows} == {ALLOCATION_METHOD_PROVIDER_ATTRIBUTED}
    by_key = {}
    for row in rows:
        by_key[row.api_key_id] = by_key.get(row.api_key_id, Decimal("0")) + Decimal(row.amount)
    assert by_key == {
        H1: Decimal("9.75"),
        H2: Decimal("3.5"),
        "old-key": Decimal("1.25"),
    }

    result = reconcile(
        db_session, org_id=ORG_ID, provider=PROVIDER, window=window, reported_total=FIXTURE_TOTAL
    )
    assert result.costura_total == FIXTURE_TOTAL
    # The control total is the sum of `credits_usage` on the ungrouped pages, not `total_usage`.
    assert result.provider_total_latest_run == FIXTURE_TOTAL
    assert result.provider_matches is True
    assert result.raw_vs_normalized_delta == 0
    assert result.allocation is not None
    assert result.allocation.delta(result.costura_total) == 0

    report = usage_report(
        session=db_session, org_id=ORG_ID, provider=PROVIDER, window=window, dimension="api_key"
    )
    assert report.allocated and report.cost_total == FIXTURE_TOTAL
    top = report.rows[0]
    assert top.key == H1 and top.label.startswith("prod-backend")
    assert top.amount == Decimal("9.75") and top.byok_amount == FIXTURE_BYOK
    assert top.tokens["reasoning_tokens"] == 0
    assert (report.rows[0].details.get("workspace") or "").startswith("Production")
    research = next(r for r in report.rows if r.key == H2)
    assert research.amount == Decimal("3.5") and research.byok_amount == Decimal("0")
    unknown = next(r for r in report.rows if r.key == "old-key")
    assert unknown.amount == Decimal("1.25")

    overview = month_summary(db_session, org_id=ORG_ID, provider=PROVIDER, month="2026-08")
    assert overview.total == FIXTURE_TOTAL and overview.byok_total == FIXTURE_BYOK


def test_direct_attribution_absorbs_one_storage_unit(
    db_session: Session, openrouter_client: OpenRouterManagementClient
) -> None:
    run_inventory_sync(db_session, target(db_session, ORG_ID, "openrouter"), openrouter_client)
    run_cost_sync(
        db_session, target(db_session, ORG_ID, "openrouter"), openrouter_client, START, END
    )
    usage = db_session.scalar(select(SpendUsageLine).where(SpendUsageLine.amount.is_not(None)))
    assert usage is not None
    usage.amount = Decimal(usage.amount) + Decimal("0.00000001")
    db_session.commit()

    allocation = run_allocation(db_session, ORG_ID, PROVIDER, Window.for_month("2026-08"))

    assert allocation.balanced
    assert all(row.amount >= 0 for row in db_session.scalars(select(SpendAllocatedLine)))


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        (Decimal("0.00000002"), "maximum residue"),
        (Decimal("-1"), "must be non-negative"),
    ],
)
def test_invalid_direct_attribution_keeps_the_previous_rows(
    db_session: Session,
    openrouter_client: OpenRouterManagementClient,
    replacement: Decimal,
    message: str,
) -> None:
    run_inventory_sync(db_session, target(db_session, ORG_ID, "openrouter"), openrouter_client)
    run_cost_sync(
        db_session, target(db_session, ORG_ID, "openrouter"), openrouter_client, START, END
    )
    window = Window.for_month("2026-08")
    first = run_allocation(db_session, ORG_ID, PROVIDER, window)
    before = [
        (row.id, row.allocation_run_id, row.amount)
        for row in db_session.scalars(select(SpendAllocatedLine).order_by(SpendAllocatedLine.id))
    ]
    usage = db_session.scalar(select(SpendUsageLine).where(SpendUsageLine.amount.is_not(None)))
    assert usage is not None
    usage.amount = Decimal(usage.amount) + replacement if replacement >= 0 else replacement
    db_session.commit()

    with pytest.raises(ValueError, match=message):
        run_allocation(db_session, ORG_ID, PROVIDER, window)

    after = [
        (row.id, row.allocation_run_id, row.amount)
        for row in db_session.scalars(select(SpendAllocatedLine).order_by(SpendAllocatedLine.id))
    ]
    assert after == before
    later = [run for run in db_session.scalars(select(ProviderSyncRun)) if run.id > first.run_id]
    assert [run.status for run in later] == ["failed"]


@pytest.mark.parametrize("bad", [{"date__day": 20260801}, {"date__day": "2026-08-01", "model": ""}])
def test_lines_from_rows_reject_malformed_rows(bad: dict) -> None:
    row = {"api_key_id": "k", "model": "m", "total_usage": 1, **bad}
    with pytest.raises(ValueError):
        lines_from_rows([row], _directory())
