"""OpenAI normalize, inventory (service accounts included), cost and usage sync (idempotent),
key-attributed allocation, reconcile with the per-key check."""

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura.models import (
    ProviderApiKey,
    ProviderReportPage,
    ProviderSyncRun,
    ProviderUser,
    ProviderWorkspace,
    ProviderWorkspaceMember,
    SpendActivityLine,
    SpendAllocatedLine,
    SpendCostLine,
    SpendUsageLine,
)
from costura.models.allocation import ALLOCATION_METHOD_KEY_ATTRIBUTED
from costura.providers.lines import ActivityLine, NormalizeError
from costura.providers.openai.client import OpenAIAdminClient
from costura.providers.openai.inventory import (
    ENDPOINT_API_KEYS,
    ENDPOINT_PROJECT_USERS,
    ENDPOINT_PROJECTS,
    ENDPOINT_SERVICE_ACCOUNTS,
    ENDPOINT_USERS,
    api_keys_from_payload,
    key_hint,
    key_owner_id,
    run_inventory_sync,
    service_accounts_from_payload,
)
from costura.providers.openai.normalize import (
    LINE_ITEM_KINDS,
    ParsedLineItem,
    activity_lines_from_page,
    cost_lines_from_page,
    parse_line_item,
    result_amount,
    usage_lines_from_page,
)
from costura.providers.openai.sync import (
    ACTIVITY_FAMILIES,
    ENDPOINT_COST,
    ENDPOINT_COST_BY_KEY,
    ENDPOINT_COST_TOTAL,
    ENDPOINT_USAGE,
    key_amounts,
    page_amount,
    run_activity_sync,
    run_cost_by_key_sync,
    run_cost_sync,
    run_cost_total_sync,
    run_usage_sync,
)
from costura.providers.records import USER_KIND_SERVICE_ACCOUNT, USER_KIND_USER
from costura.spend.allocate import run_allocation
from costura.spend.allocation_split import (
    REASON_NO_KEY,
    AllocationSummary,
    Bucket,
    CostBucket,
    UsageRow,
    attribute_by_key,
)
from costura.spend.key_check import key_check
from costura.spend.reconcile import reconcile
from costura.spend.usage import usage_report
from costura.spend.window import Window
from tests.conftest import ORG_ID, load_fixture, target
from tests.support.runs import cost_total, usage_total

PROVIDER = "openai"
START = datetime(2026, 8, 1, tzinfo=UTC)
END = datetime(2026, 9, 1, tzinfo=UTC)
DAY1 = datetime(2026, 8, 1, tzinfo=UTC)
DAY2 = datetime(2026, 8, 2, tzinfo=UTC)
# Fourteen costs results over two days, every one under a key: 14.46 on day one (0.80 of it
# web search, 0.06 embeddings) and 7.54 on day two. Per key: key_a1 7.00, key_a2 0.70 (a
# service account's key), key_b1 14.30.
FIXTURE_TOTAL = Decimal("22.00")
KEY_TOTALS = {"key_a1": Decimal("7.00"), "key_a2": Decimal("0.70"), "key_b1": Decimal("14.30")}


@pytest.mark.parametrize(
    ("line_item", "expected"),
    [
        (
            "gpt-4o-mini-2024-07-18, input",
            ParsedLineItem("gpt-4o-mini-2024-07-18", "uncached_input_tokens", "tokens", None),
        ),
        (
            "gpt-4o-mini-2024-07-18, cached input",
            ParsedLineItem("gpt-4o-mini-2024-07-18", "cache_read_input_tokens", "tokens", None),
        ),
        (
            "gpt-4o-mini-2024-07-18, cache writes",
            ParsedLineItem(
                "gpt-4o-mini-2024-07-18",
                "cache_creation.ephemeral_5m_input_tokens",
                "tokens",
                None,
            ),
        ),
        (
            "gpt-4o-2024-08-06, output",
            ParsedLineItem("gpt-4o-2024-08-06", "output_tokens", "tokens", None),
        ),
        (
            "gpt-5.6-sol, input, long context",
            ParsedLineItem("gpt-5.6-sol", "uncached_input_tokens", "tokens", "long_context"),
        ),
        (
            "gpt-5.6-sol, cached input, long context",
            ParsedLineItem("gpt-5.6-sol", "cache_read_input_tokens", "tokens", "long_context"),
        ),
        (
            "gpt-6-astra, Output_Tokens",
            ParsedLineItem("gpt-6-astra", "output_tokens", "tokens", None),
        ),
        ("web search tool calls", ParsedLineItem(None, None, "web_search", None)),
        ("Web search", ParsedLineItem(None, None, "web_search", None)),
        (
            "text-embedding-3-large",
            ParsedLineItem("text-embedding-3-large", None, "embeddings", None),
        ),
        ("gpt-image-1, image_output", ParsedLineItem("gpt-image-1", None, "images", None)),
        (
            "omni-moderation-latest",
            ParsedLineItem("omni-moderation-latest", None, "moderations", None),
        ),
        ("tts-1, characters", ParsedLineItem("tts-1", None, "audio", None)),
        ("Vector Store Usage", ParsedLineItem("Vector Store Usage", None, "vector_stores", None)),
        (
            "Code Interpreter Tool Call",
            ParsedLineItem("Code Interpreter Tool Call", None, "code_interpreter", None),
        ),
        (", input", ParsedLineItem("input", None, "other", None)),
        ("", ParsedLineItem(None, None, "other", None)),
    ],
)
def test_parse_line_item_reads_the_live_vocabulary(
    line_item: str, expected: ParsedLineItem
) -> None:
    assert parse_line_item(line_item) == expected


def test_line_item_kinds_map_onto_the_allocator_vocabulary() -> None:
    from costura.spend.allocation_split import TOKEN_TYPE_COLUMNS

    assert set(LINE_ITEM_KINDS.values()) <= set(TOKEN_TYPE_COLUMNS)


def test_cost_lines_keep_every_line_item_with_its_key() -> None:
    lines = cost_lines_from_page(load_fixture("costs_page1.json", "openai"))

    assert len(lines) == 9
    assert sum(line.amount for line in lines) == Decimal("14.46")
    assert all(line.api_key_id is not None for line in lines)
    by_type = {}
    for line in lines:
        by_type[line.cost_type] = by_type.get(line.cost_type, 0) + 1
    assert by_type == {"tokens": 7, "web_search": 1, "embeddings": 1}
    mini_output = next(
        line
        for line in lines
        if line.token_type == "output_tokens" and line.workspace_id == "proj_a"
    )
    assert mini_output.model == "gpt-4o-mini-2024-07-18" and mini_output.api_key_id == "key_a1"
    assert mini_output.service_tier == "standard" and mini_output.currency == "USD"
    assert mini_output.amount == Decimal("2.35") and mini_output.raw_amount_minor == "2.35"
    assert mini_output.period_start == DAY1 and mini_output.period_end == DAY2
    assert mini_output.description == "gpt-4o-mini-2024-07-18, output"
    assert mini_output.key[-1] == "key_a1"
    cache_write = next(line for line in lines if "cache writes" in line.description)
    assert cache_write.token_type == "cache_creation.ephemeral_5m_input_tokens"
    assert cache_write.api_key_id == "key_a2"
    long_context = [line for line in lines if line.context_window == "long_context"]
    assert {line.token_type for line in long_context} == {
        "uncached_input_tokens",
        "output_tokens",
    }
    web_search = next(line for line in lines if line.cost_type == "web_search")
    assert web_search.model is None and web_search.token_type is None
    assert web_search.service_tier is None and web_search.amount == Decimal("0.80")
    assert web_search.workspace_id == "proj_b" and web_search.api_key_id == "key_b1"
    embeddings = next(line for line in lines if line.cost_type == "embeddings")
    assert embeddings.model == "text-embedding-3-large" and embeddings.api_key_id == "key_a2"


def test_usage_lines_split_the_prompt_and_name_the_key_owner() -> None:
    lines = usage_lines_from_page(load_fixture("usage_completions_page1.json", "openai"))

    assert len(lines) == 3
    first = lines[0]
    assert first.workspace_id == "proj_a" and first.api_key_id == "key_a1"
    assert first.account_id == "user_x" and first.model == "gpt-4o-mini-2024-07-18"
    assert first.service_tier == "standard" and first.context_window is None
    assert first.uncached_input_tokens == 8_000 and first.cache_read_tokens == 2_000
    assert first.cache_creation_5m_tokens == 0 and first.output_tokens == 4_000
    assert first.request_count == 50 and first.reasoning_tokens == 0
    assert first.amount is None and first.byok_amount is None
    service = lines[1]
    assert service.api_key_id == "key_a2" and service.account_id == "svc_eval"
    assert service.cache_creation_5m_tokens == 1_000 and service.uncached_input_tokens == 4_000

    without_uncached = {
        "object": "page",
        "data": [
            {
                "object": "bucket",
                "start_time": 1785542400,
                "end_time": 1785628800,
                "results": [
                    {
                        "input_tokens": 1_000,
                        "input_cached_tokens": 300,
                        "input_cache_write_tokens": 200,
                        "output_tokens": 10,
                        "num_model_requests": 1,
                        "model": "gpt-4o",
                        "project_id": "proj_a",
                        "api_key_id": None,
                        "user_id": None,
                    }
                ],
            }
        ],
    }
    (line,) = usage_lines_from_page(without_uncached)
    assert line.uncached_input_tokens == 500 and line.cache_creation_5m_tokens == 200
    assert line.cache_read_tokens == 300 and line.api_key_id is None


@pytest.mark.parametrize(
    ("family", "fixture", "unit", "quantity", "requests"),
    [
        ("images", "usage_images_page1.json", "images", Decimal("12"), 3),
        ("embeddings", "usage_embeddings.json", "input_tokens", Decimal("25000"), 5),
        ("moderations", "usage_moderations.json", "input_tokens", Decimal("6000"), 12),
        ("audio_speeches", "usage_audio_speeches.json", "characters", Decimal("18000"), 6),
        (
            "audio_transcriptions",
            "usage_audio_transcriptions.json",
            "seconds",
            Decimal("420"),
            7,
        ),
        ("vector_stores", "usage_vector_stores.json", "bytes", Decimal("1073741824"), 0),
        (
            "code_interpreter_sessions",
            "usage_code_interpreter.json",
            "sessions",
            Decimal("9"),
            0,
        ),
    ],
)
def test_activity_normalizers_use_each_family_counter(
    family: str, fixture: str, unit: str, quantity: Decimal, requests: int
) -> None:
    lines = activity_lines_from_page(load_fixture(fixture, "openai"), family)
    first = lines[0]
    assert isinstance(first, ActivityLine)
    assert (first.family, first.unit, first.quantity, first.request_count) == (
        family,
        unit,
        quantity,
        requests,
    )
    if family == "images":
        assert first.detail == '{"size":"1024x1024","source":"image.generation"}'
    else:
        assert first.detail is None
    if family in {"vector_stores", "code_interpreter_sessions"}:
        assert first.api_key_id is None and first.account_id is None and first.model is None


@pytest.mark.parametrize(
    "result",
    [
        {"amount": {"value": "abc", "currency": "usd"}, "line_item": "x, input"},
        {"amount": {"value": 1.0}, "line_item": "x, input"},
        {"amount": 1.0, "line_item": "x, input"},
    ],
)
def test_malformed_amounts_are_rejected(result: dict) -> None:
    with pytest.raises(NormalizeError):
        result_amount(result)


def test_page_amount_and_key_amounts_respect_the_window() -> None:
    total = load_fixture("costs_total.json", "openai")
    assert page_amount(total, START, END) == FIXTURE_TOTAL
    assert page_amount(total, DAY2, END) == Decimal("7.54")

    by_key = load_fixture("costs_by_key.json", "openai")
    amounts = key_amounts(by_key, START, END)
    assert amounts == KEY_TOTALS
    assert sum(amounts.values()) == FIXTURE_TOTAL


def test_key_records_take_the_owner_and_the_redacted_tail() -> None:
    payload = load_fixture("project_api_keys_proj_a.json", "openai")
    records = api_keys_from_payload(payload, project_id="proj_a")

    user_key, service_key = records
    assert user_key.external_id == "key_a1" and user_key.name == "assistants-prod"
    assert user_key.partial_key_hint == "def1" and user_key.workspace_external_id == "proj_a"
    assert user_key.created_by_external_id == "user_x" and user_key.status == "active"
    assert service_key.created_by_external_id == "svc_eval"
    assert service_key.principal_external_id == "svc_eval"
    assert key_owner_id({"type": "user", "user": {"id": "u"}}) == "u"
    assert key_owner_id({"type": "service_account"}) is None
    assert key_owner_id(None) is None
    assert key_hint("sk-abc...ef22") == "ef22" and key_hint(None) is None

    (service_account,) = service_accounts_from_payload(payload, project_id="proj_a")
    assert service_account.external_id == "svc_eval" and service_account.email == "Eval bot"
    assert service_account.kind == USER_KIND_SERVICE_ACCOUNT and service_account.role == "member"
    assert service_account.added_at == datetime.fromtimestamp(1780550000, tz=UTC)
    assert (
        service_accounts_from_payload({"data": [{"owner": {"type": "user"}}]}, project_id="p") == []
    )


def test_inventory_sync_maps_projects_users_keys_and_members(
    db_session: Session, openai_client: OpenAIAdminClient
) -> None:
    summaries = run_inventory_sync(db_session, target(db_session, ORG_ID, "openai"), openai_client)

    by_endpoint = {s.endpoint: s for s in summaries}
    assert list(by_endpoint) == [
        ENDPOINT_PROJECTS,
        ENDPOINT_USERS,
        ENDPOINT_API_KEYS,
        ENDPOINT_SERVICE_ACCOUNTS,
        ENDPOINT_PROJECT_USERS,
    ]
    assert by_endpoint[ENDPOINT_PROJECTS].rows_upserted == 3
    assert by_endpoint[ENDPOINT_USERS].rows_upserted == 2
    assert by_endpoint[ENDPOINT_API_KEYS].rows_upserted == 3
    assert by_endpoint[ENDPOINT_API_KEYS].skipped_workspaces == ["proj_old"]
    assert by_endpoint[ENDPOINT_SERVICE_ACCOUNTS].rows_upserted == 1
    assert by_endpoint[ENDPOINT_PROJECT_USERS].rows_upserted == 3
    assert by_endpoint[ENDPOINT_PROJECT_USERS].skipped_workspaces == ["proj_old"]
    workspaces = {
        w.external_id: w
        for w in db_session.scalars(
            select(ProviderWorkspace).where(ProviderWorkspace.provider == PROVIDER)
        )
    }
    assert workspaces["proj_a"].name == "Assistants" and workspaces["proj_a"].archived_at is None
    assert workspaces["proj_old"].archived_at is not None
    assert workspaces["proj_old"].tags == {"status": "archived"}
    assert workspaces["proj_a"].created_at == datetime.fromtimestamp(1780000000, tz=UTC)

    users = {
        u.external_id: u
        for u in db_session.scalars(select(ProviderUser).where(ProviderUser.provider == PROVIDER))
    }
    assert users["user_x"].email == "Alice@example.com" and users["user_x"].role == "owner"
    assert users["user_x"].kind == USER_KIND_USER
    assert (
        users["svc_eval"].email == "Eval bot"
        and users["svc_eval"].kind == USER_KIND_SERVICE_ACCOUNT
    )

    keys = {
        k.external_id: k
        for k in db_session.scalars(
            select(ProviderApiKey).where(ProviderApiKey.provider == PROVIDER)
        )
    }
    assert set(keys) == {"key_a1", "key_a2", "key_b1"}
    assert keys["key_b1"].workspace_external_id == "proj_b"
    assert keys["key_a2"].created_by_external_id == "svc_eval"

    members = list(
        db_session.scalars(
            select(ProviderWorkspaceMember).where(ProviderWorkspaceMember.provider == PROVIDER)
        )
    )
    assert {(m.workspace_external_id, m.user_external_id, m.role) for m in members} == {
        ("proj_a", "user_x", "owner"),
        ("proj_a", "user_y", "member"),
        ("proj_b", "user_x", "owner"),
    }
    stored = db_session.scalar(
        select(ProviderReportPage.request_params).where(
            ProviderReportPage.sync_run_id == by_endpoint[ENDPOINT_API_KEYS].run_id
        )
    )
    assert stored["project_id"] == "proj_a" and stored["owner_project_access"] == "any"
    runs = list(
        db_session.scalars(select(ProviderSyncRun).where(ProviderSyncRun.provider == PROVIDER))
    )
    assert {r.status for r in runs} == {"succeeded"}

    # A second listing keeps every row live: nothing is marked missing, and in particular the
    # users listing (which never returns service accounts) leaves the service account alone.
    run_inventory_sync(db_session, target(db_session, ORG_ID, "openai"), openai_client)
    assert (
        db_session.scalar(
            select(ProviderUser.missing_since).where(ProviderUser.external_id == "svc_eval")
        )
        is None
    )


def test_cost_sync_is_idempotent_and_keeps_raw_pages(
    db_session: Session, openai_client: OpenAIAdminClient
) -> None:
    summary = run_cost_sync(
        db_session, target(db_session, ORG_ID, "openai"), openai_client, START, END
    )

    assert summary.endpoint == ENDPOINT_COST
    assert summary.pages_fetched == 2 and summary.raw_results == 14
    assert summary.rows_upserted == 14
    assert cost_total(db_session, summary.run_id) == FIXTURE_TOTAL

    def state() -> tuple[int, Decimal]:
        count, total = db_session.execute(
            select(func.count(), func.coalesce(func.sum(SpendCostLine.amount), 0)).where(
                SpendCostLine.provider == PROVIDER
            )
        ).one()
        return count, Decimal(total)

    first = state()
    assert first == (14, FIXTURE_TOTAL)
    again = run_cost_sync(
        db_session, target(db_session, ORG_ID, "openai"), openai_client, START, END
    )
    assert state() == first and again.run_id != summary.run_id
    pages = db_session.scalar(
        select(func.count())
        .select_from(ProviderReportPage)
        .where(
            ProviderReportPage.provider == PROVIDER, ProviderReportPage.endpoint == ENDPOINT_COST
        )
    )
    assert pages == 4

    usage = run_usage_sync(
        db_session, target(db_session, ORG_ID, "openai"), openai_client, START, END
    )
    assert usage.endpoint == ENDPOINT_USAGE
    assert usage.pages_fetched == 2 and usage.rows_upserted == 5
    assert usage_total(db_session, usage.run_id, "uncached_input_tokens") == 30_000
    assert usage_total(db_session, usage.run_id, "cache_read_tokens") == 2_000
    assert usage_total(db_session, usage.run_id, "cache_creation_5m_tokens") == 1_000
    assert usage_total(db_session, usage.run_id, "output_tokens") == 13_000
    assert usage_total(db_session, usage.run_id, "request_count") == 140
    assert db_session.scalar(select(func.count()).select_from(SpendUsageLine)) == 5

    total = run_cost_total_sync(
        db_session, target(db_session, ORG_ID, "openai"), openai_client, START, END
    )
    assert total.endpoint == ENDPOINT_COST_TOTAL and total.rows_upserted == 0
    by_key = run_cost_by_key_sync(
        db_session, target(db_session, ORG_ID, "openai"), openai_client, START, END
    )
    assert by_key.endpoint == ENDPOINT_COST_BY_KEY and by_key.rows_upserted == 0


def test_activity_sync_is_idempotent_across_every_family(
    db_session: Session, openai_client: OpenAIAdminClient
) -> None:
    unit = target(db_session, ORG_ID, "openai")
    first_runs = [
        run_activity_sync(db_session, unit, openai_client, START, END, family=family)
        for family in ACTIVITY_FAMILIES
    ]
    assert [summary.rows_upserted for summary in first_runs] == [2, 1, 1, 1, 1, 1, 1]
    assert db_session.scalar(select(func.count()).select_from(SpendActivityLine)) == 8

    first = list(
        db_session.execute(
            select(
                SpendActivityLine.family,
                func.sum(SpendActivityLine.quantity),
                func.sum(SpendActivityLine.request_count),
            )
            .group_by(SpendActivityLine.family)
            .order_by(SpendActivityLine.family)
        )
    )
    second_runs = [
        run_activity_sync(db_session, unit, openai_client, START, END, family=family)
        for family in ACTIVITY_FAMILIES
    ]
    second = list(
        db_session.execute(
            select(
                SpendActivityLine.family,
                func.sum(SpendActivityLine.quantity),
                func.sum(SpendActivityLine.request_count),
            )
            .group_by(SpendActivityLine.family)
            .order_by(SpendActivityLine.family)
        )
    )
    assert second == first
    assert all(
        second_summary.run_id != first_summary.run_id
        for first_summary, second_summary in zip(first_runs, second_runs, strict=True)
    )
    coverage = reconcile(
        db_session,
        org_id=ORG_ID,
        provider=PROVIDER,
        window=Window.for_month("2026-08"),
        reported_total=Decimal("0"),
    ).activity_coverage
    assert coverage is not None and coverage.complete
    assert coverage.covered_families == list(ACTIVITY_FAMILIES)


def test_key_attributed_allocation_balances_and_reconciles_per_key(
    db_session: Session, openai_client: OpenAIAdminClient
) -> None:
    run_inventory_sync(db_session, target(db_session, ORG_ID, "openai"), openai_client)
    run_cost_sync(db_session, target(db_session, ORG_ID, "openai"), openai_client, START, END)
    run_usage_sync(db_session, target(db_session, ORG_ID, "openai"), openai_client, START, END)
    run_cost_total_sync(db_session, target(db_session, ORG_ID, "openai"), openai_client, START, END)
    window = Window.for_month("2026-08")

    # Before the per-key run exists the check is pending, not failed.
    run_allocation(db_session, ORG_ID, PROVIDER, window)
    assert key_check(db_session, ORG_ID, PROVIDER, window) is None

    run_cost_by_key_sync(
        db_session, target(db_session, ORG_ID, "openai"), openai_client, START, END
    )
    allocation = run_allocation(db_session, ORG_ID, PROVIDER, window)
    assert allocation.balanced and allocation.cost_total == FIXTURE_TOTAL
    # Every line item is under a key, web search and embeddings included: nothing is left.
    assert allocation.allocated_total == FIXTURE_TOTAL
    assert allocation.unallocated_total == 0 and allocation.unallocated_by_reason == {}
    rows = list(
        db_session.scalars(
            select(SpendAllocatedLine).where(SpendAllocatedLine.provider == PROVIDER)
        )
    )
    assert all(r.unallocated_reason is None for r in rows)
    assert {r.method for r in rows} == {ALLOCATION_METHOD_KEY_ATTRIBUTED}
    by_key: dict[str | None, Decimal] = {}
    for row in rows:
        by_key[row.api_key_id] = by_key.get(row.api_key_id, Decimal("0")) + Decimal(row.amount)
    assert by_key == KEY_TOTALS
    web_search = next(r for r in rows if r.cost_type == "web_search")
    assert web_search.api_key_id == "key_b1" and web_search.account_id == "user_x"
    assert web_search.amount == Decimal("0.80")
    # key_a2 belongs to a service account: day one names it in the usage rows, day two has no
    # completions for the key, so the inventory owner takes the embeddings line.
    service_rows = [r for r in rows if r.api_key_id == "key_a2"]
    assert {r.account_id for r in service_rows} == {"svc_eval"}
    day_two = next(r for r in service_rows if r.period_start == DAY2)
    assert day_two.amount == Decimal("0.04") and day_two.cost_type == "embeddings"

    result = reconcile(
        db_session, org_id=ORG_ID, provider=PROVIDER, window=window, reported_total=FIXTURE_TOTAL
    )
    assert result.costura_total == FIXTURE_TOTAL and result.matches
    assert result.provider_total_latest_run == FIXTURE_TOTAL and result.provider_matches is True
    assert result.raw_vs_normalized_delta == 0
    assert result.allocation is not None and result.allocation.delta(FIXTURE_TOTAL) == 0
    assert result.key_check_supported is True
    check = result.key_check
    assert check is not None and check.ok and check.keys_compared == 3
    assert check.provider_total == FIXTURE_TOTAL
    assert check.allocated_total == FIXTURE_TOTAL

    report = usage_report(
        session=db_session, org_id=ORG_ID, provider=PROVIDER, window=window, dimension="api_key"
    )
    assert report.allocated and report.cost_total == FIXTURE_TOTAL
    top = report.rows[0]
    assert top.key == "key_b1" and top.label.startswith("batch-runner")
    assert top.amount == Decimal("14.30")
    assert (top.details.get("workspace") or "").startswith("Batch jobs")
    accounts = usage_report(
        session=db_session, org_id=ORG_ID, provider=PROVIDER, window=window, dimension="account"
    )
    assert all(r.key is not None for r in accounts.rows)
    ada = next(r for r in accounts.rows if r.key == "user_x")
    assert ada.label.startswith("Alice@example.com") or ada.label.startswith("Ada")
    service = next(r for r in accounts.rows if r.key == "svc_eval")
    assert service.label.startswith("Eval bot") and service.amount == Decimal("0.70")


def _cost(
    day: datetime, amount: str, *, api_key_id: str | None, token_type: str | None
) -> CostBucket:
    cost_type = "tokens" if token_type else "web_search"
    bucket = Bucket(
        day,
        "proj_a",
        cost_type,
        "gpt-4o" if token_type else None,
        token_type,
        "standard" if token_type else None,
        None,
        None,
        api_key_id,
    )
    return CostBucket(bucket=bucket, period_end=day, amount=Decimal(amount), currency="USD")


def _usage(day: datetime, key: str | None, account: str | None, **tokens: int) -> UsageRow:
    counters = {
        "uncached_input_tokens": 0,
        "cache_creation_5m_tokens": 0,
        "cache_creation_1h_tokens": 0,
        "cache_read_tokens": 0,
        "output_tokens": 0,
        "web_search_requests": 0,
    }
    counters.update(tokens)
    return UsageRow(day, "proj_a", key, account, "gpt-4o", "standard", None, None, counters)


def test_key_attributed_allocation_splits_shared_keys_and_names_keyless_buckets() -> None:
    summary = AllocationSummary(provider=PROVIDER, window=Window.for_month("2026-08"), run_id=1)
    costs = [
        # One key, two users on the day: split by output tokens 3:1.
        _cost(DAY1, "4.00", api_key_id="key_shared", token_type="output_tokens"),
        # Web search on a key with no completions on the day and no inventory owner.
        _cost(DAY1, "1.00", api_key_id="key_lonely", token_type=None),
        # No key at all: token share over the day's usage still applies.
        _cost(DAY1, "2.00", api_key_id=None, token_type="output_tokens"),
        # No key and no basis: unallocated as no_key.
        _cost(DAY2, "0.50", api_key_id=None, token_type=None),
    ]
    usage = [
        _usage(DAY1, "key_shared", "user_a", output_tokens=300),
        _usage(DAY1, "key_shared", "user_b", output_tokens=100),
    ]
    rows = attribute_by_key(
        costs, usage, {"key_other": "svc"}, summary, run_id=1, provider=PROVIDER
    )

    allocated = [r for r in rows if r["unallocated_reason"] is None]
    keyed = [r for r in allocated if r["method"] == ALLOCATION_METHOD_KEY_ATTRIBUTED]
    shared = sorted(
        (r["account_id"], Decimal(r["amount"])) for r in keyed if r["api_key_id"] == "key_shared"
    )
    assert shared == [("user_a", Decimal("3.00")), ("user_b", Decimal("1.00"))]
    lonely = next(r for r in keyed if r["api_key_id"] == "key_lonely")
    assert lonely.get("account_id") is None and Decimal(lonely["amount"]) == Decimal("1.00")
    assert lonely["method"] == ALLOCATION_METHOD_KEY_ATTRIBUTED
    keyless = [r for r in allocated if r["method"] != ALLOCATION_METHOD_KEY_ATTRIBUTED]
    assert sum(Decimal(r["amount"]) for r in keyless) == Decimal("2.00")
    (unallocated,) = [r for r in rows if r["unallocated_reason"] is not None]
    assert unallocated["unallocated_reason"] == REASON_NO_KEY
    assert Decimal(unallocated["amount"]) == Decimal("0.50")
    assert summary.unallocated_by_reason == {REASON_NO_KEY: Decimal("0.50")}
    assert summary.cost_total == Decimal("7.50")
    assert summary.allocated_total == Decimal("7.00")


def test_key_check_reports_the_keys_outside_the_tolerance(
    db_session: Session, openai_client: OpenAIAdminClient
) -> None:
    run_inventory_sync(db_session, target(db_session, ORG_ID, "openai"), openai_client)
    run_cost_sync(db_session, target(db_session, ORG_ID, "openai"), openai_client, START, END)
    run_usage_sync(db_session, target(db_session, ORG_ID, "openai"), openai_client, START, END)
    run_cost_by_key_sync(
        db_session, target(db_session, ORG_ID, "openai"), openai_client, START, END
    )
    window = Window.for_month("2026-08")
    run_allocation(db_session, ORG_ID, PROVIDER, window)

    # Move one dollar of the provider's figure from key_b1 to a key Costura never saw.
    page = db_session.scalar(
        select(ProviderReportPage).where(ProviderReportPage.endpoint == ENDPOINT_COST_BY_KEY)
    )
    assert page is not None
    payload = deepcopy(page.payload)
    results = payload["data"][1]["results"]
    results[2]["amount"]["value"] = 3.5
    results.append(
        {
            "amount": {"value": 1.0, "currency": "usd"},
            "project_id": "proj_b",
            "api_key_id": "key_ghost",
        }
    )
    page.payload = payload
    db_session.commit()

    check = key_check(db_session, ORG_ID, PROVIDER, window)
    assert check is not None and not check.ok and check.keys_compared == 4
    assert [(k.api_key_id, k.delta) for k in check.keys_off] == [
        ("key_b1", Decimal("1.00")),
        ("key_ghost", Decimal("-1.00")),
    ]


def test_all_scope_has_no_key_check(db_session: Session) -> None:
    assert key_check(db_session, ORG_ID, "all", Window.for_month("2026-08")) is None
    assert key_check(db_session, ORG_ID, "anthropic", Window.for_month("2026-08")) is None
