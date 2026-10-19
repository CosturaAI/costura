from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from costura.models import ProviderApiKey, ProviderWorkspace, SpendAllocatedLine
from costura.providers.anthropic.client import AnthropicAdminClient
from costura.providers.anthropic.inventory import run_inventory_sync
from costura.providers.anthropic.sync import run_cost_sync, run_usage_sync
from costura.providers.registry import provider_origin
from costura.spend.allocate import run_allocation
from costura.spend.dimensions import group_key
from costura.spend.filters import FilterClause
from costura.spend.inventory import InventoryResolver
from costura.spend.usage import daily_series, usage_report
from costura.spend.window import Window
from tests.conftest import ORG_ID, target
from tests.support.spend import AUGUST, FIXTURE_END, FIXTURE_START


def _synced(db_session: Session, client: AnthropicAdminClient, *, allocate: bool) -> None:
    run_cost_sync(
        db_session, target(db_session, ORG_ID, "anthropic"), client, FIXTURE_START, FIXTURE_END
    )
    run_usage_sync(
        db_session, target(db_session, ORG_ID, "anthropic"), client, FIXTURE_START, FIXTURE_END
    )
    run_inventory_sync(db_session, target(db_session, ORG_ID, "anthropic"), client)
    if allocate:
        run_allocation(db_session, ORG_ID, "anthropic", AUGUST)


def test_usage_by_api_key_resolves_names_and_owners(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    _synced(db_session, anthropic_client, allocate=False)

    report = usage_report(
        db_session, org_id=ORG_ID, provider="anthropic", window=AUGUST, dimension="api_key"
    )

    assert not report.allocated and report.cost_total is None
    assert [row.label for row in report.rows] == [
        "(Claude Code logins, no API key)",
        "batch-ingest (apikey_redacted_2)",
        "billing-agent (apikey_redacted_1)",
        "(playground, no api key)",
    ]
    assert all(row.amount is None and row.share is None for row in report.rows)
    batch = report.rows[1]
    assert batch.total_tokens == 20000 + 1000 + 500 + 8000
    assert batch.tokens["cache_creation_1h_tokens"] == 1000
    assert batch.details == {
        "hint": "sk-ant-api03-...bbbb",
        "workspace": "Platform (wrkspc_redacted_a)",
        "created_by": "bob@example.com",
        "status": "active",
    }
    billing = report.rows[2]
    assert billing.web_search_requests == 2
    assert billing.details["workspace"] == "(default workspace)"
    assert billing.details["created_by"] == "alice@example.com"
    assert report.rows[0].details == {} and report.rows[3].details == {}


def test_usage_without_inventory_marks_unknown_ids(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    run_usage_sync(
        db_session,
        target(db_session, ORG_ID, "anthropic"),
        anthropic_client,
        FIXTURE_START,
        FIXTURE_END,
    )

    rows = usage_report(
        db_session, org_id=ORG_ID, provider="anthropic", window=AUGUST, dimension="api_key"
    ).rows

    labels = [row.label for row in rows]
    assert "apikey_redacted_2 (not in inventory)" in labels
    assert rows[[r.label for r in rows].index("apikey_redacted_2 (not in inventory)")].details == {}


def test_usage_with_allocation_adds_dollars_and_shares(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    _synced(db_session, anthropic_client, allocate=True)

    report = usage_report(
        db_session, org_id=ORG_ID, provider="anthropic", window=AUGUST, dimension="api_key"
    )

    assert report.allocated
    assert report.cost_total == Decimal("64.615")
    by_label = {row.label: row for row in report.rows}
    assert by_label["(Claude Code logins, no API key)"].amount == Decimal("50")
    key1 = by_label["billing-agent (apikey_redacted_1)"].amount
    playground = by_label["(playground, no api key)"].amount
    assert key1 is not None and playground is not None
    assert key1 + playground == Decimal("1.2378912") + Decimal("2.505")
    assert key1 > playground
    assert by_label["batch-ingest (apikey_redacted_2)"].amount == Decimal("0")
    unallocated = by_label["(unallocated cost)"]
    assert unallocated.amount == Decimal("10.8721088")
    assert unallocated.total_tokens == 0
    assert sum(row.amount for row in report.rows) == report.cost_total
    shares = sum(row.share for row in report.rows)
    assert abs(shares - Decimal("100")) <= Decimal("0.05")
    # Sorted by dollars first: the OAuth account's 50 USD tops the list.
    assert report.rows[0].label == "(Claude Code logins, no API key)"


def test_usage_by_account_and_creator(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    _synced(db_session, anthropic_client, allocate=True)

    accounts = usage_report(
        db_session, org_id=ORG_ID, provider="anthropic", window=AUGUST, dimension="account"
    ).rows
    assert [(r.label, r.amount) for r in accounts] == [
        ("alice@example.com", Decimal("50")),
        ("(unallocated cost)", Decimal("10.8721088")),
        ("(api key request)", Decimal("1.2378912") + Decimal("2.505")),
    ]

    creators = usage_report(
        db_session, org_id=ORG_ID, provider="anthropic", window=AUGUST, dimension="creator"
    ).rows
    by_label = {r.label: r for r in creators}
    # Alice created billing-agent and used OAuth herself; both land on her.
    assert by_label["alice@example.com"].amount > Decimal("50")
    assert by_label["alice@example.com"].web_search_requests == 2
    assert by_label["bob@example.com"].amount == Decimal("0")
    assert by_label["bob@example.com"].total_tokens == 29500
    assert by_label["(unknown creator)"].total_tokens == 15  # playground row


def test_usage_by_person_merges_oauth_and_multiple_keys_from_one_user(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    _synced(db_session, anthropic_client, allocate=True)
    original_key = db_session.scalar(
        select(ProviderApiKey).where(
            ProviderApiKey.organization_id == ORG_ID,
            ProviderApiKey.provider == "anthropic",
            ProviderApiKey.external_id == "apikey_redacted_1",
        )
    )
    original_line = db_session.scalar(
        select(SpendAllocatedLine).where(
            SpendAllocatedLine.organization_id == ORG_ID,
            SpendAllocatedLine.provider == "anthropic",
            SpendAllocatedLine.api_key_id == "apikey_redacted_1",
            SpendAllocatedLine.amount > 0,
        )
    )
    assert original_key is not None and original_line is not None

    split_amount = original_line.amount / 4
    original_line.amount -= split_amount * 3
    for suffix in ("second", "third"):
        key_id = f"alice_{suffix}_key"
        db_session.add(
            ProviderApiKey(
                organization_id=ORG_ID,
                provider="anthropic",
                provider_account_id=original_key.provider_account_id,
                external_id=key_id,
                name=f"claude_code_key_alice_{suffix}",
                workspace_external_id="wrkspc_redacted_a",
                created_by_external_id="user_redacted_alice",
                status="active",
                sync_run_id=original_key.sync_run_id,
            )
        )
        db_session.add(
            SpendAllocatedLine(
                organization_id=ORG_ID,
                provider="anthropic",
                provider_account_id=original_line.provider_account_id,
                period_start=original_line.period_start,
                period_end=original_line.period_end,
                workspace_id="wrkspc_redacted_a",
                description=original_line.description,
                api_key_id=key_id,
                account_id=None,
                cost_type=original_line.cost_type,
                model=original_line.model,
                token_type=original_line.token_type,
                service_tier=original_line.service_tier,
                context_window=original_line.context_window,
                inference_geo=original_line.inference_geo,
                tokens=max(1, original_line.tokens // 4),
                bucket_tokens=original_line.bucket_tokens,
                bucket_amount=original_line.bucket_amount,
                amount=split_amount,
                currency=original_line.currency,
                method=original_line.method,
                allocation_run_id=original_line.allocation_run_id,
            )
        )
    service_key_id = "alice_service_key"
    db_session.add(
        ProviderApiKey(
            organization_id=ORG_ID,
            provider="anthropic",
            provider_account_id=original_key.provider_account_id,
            external_id=service_key_id,
            name="Alice service",
            workspace_external_id="wrkspc_redacted_a",
            created_by_external_id="user_redacted_alice",
            status="active",
            sync_run_id=original_key.sync_run_id,
        )
    )
    db_session.add(
        SpendAllocatedLine(
            organization_id=ORG_ID,
            provider="anthropic",
            provider_account_id=original_line.provider_account_id,
            period_start=original_line.period_start,
            period_end=original_line.period_end,
            workspace_id="wrkspc_redacted_a",
            description=original_line.description,
            api_key_id=service_key_id,
            account_id=None,
            cost_type=original_line.cost_type,
            model=original_line.model,
            token_type=original_line.token_type,
            service_tier=original_line.service_tier,
            context_window=original_line.context_window,
            inference_geo=original_line.inference_geo,
            tokens=max(1, original_line.tokens // 4),
            bucket_tokens=original_line.bucket_tokens,
            bucket_amount=original_line.bucket_amount,
            amount=split_amount,
            currency=original_line.currency,
            method=original_line.method,
            allocation_run_id=original_line.allocation_run_id,
        )
    )
    claude_workspace_id = "wrkspc_claude_code"
    db_session.add(
        ProviderWorkspace(
            organization_id=ORG_ID,
            provider="anthropic",
            provider_account_id=original_key.provider_account_id,
            external_id=claude_workspace_id,
            name="Claude Code",
            sync_run_id=original_key.sync_run_id,
        )
    )
    db_session.add(
        ProviderApiKey(
            organization_id=ORG_ID,
            provider="anthropic",
            provider_account_id=original_key.provider_account_id,
            external_id="workspace_named_personal_key",
            name="Generated session key",
            workspace_external_id=claude_workspace_id,
            created_by_external_id="user_redacted_alice",
            status="active",
            sync_run_id=original_key.sync_run_id,
        )
    )
    db_session.flush()

    resolver = InventoryResolver(db_session, ORG_ID, "anthropic")
    assert (
        resolver.personal_key_owner("anthropic", "workspace_named_personal_key")
        == "user_redacted_alice"
    )

    filters = {"workspace": "wrkspc_redacted_a"}
    people = usage_report(
        db_session,
        org_id=ORG_ID,
        provider="anthropic",
        window=AUGUST,
        dimension="person",
        filters=filters,
    ).rows
    keys = usage_report(
        db_session,
        org_id=ORG_ID,
        provider="anthropic",
        window=AUGUST,
        dimension="api_key",
        filters=filters,
    ).rows

    alice = [row for row in people if row.label == "alice@example.com"]
    assert len(alice) == 1
    assert alice[0].amount == (Decimal("50") + split_amount * 2).quantize(Decimal("0.00000001"))
    service = next(row for row in people if row.label == "(api key request)")
    assert service.amount >= split_amount
    assert {"alice_second_key", "alice_third_key", service_key_id} <= {row.key for row in keys}


def test_usage_by_workspace_lists_admins_and_top_limits(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    _synced(db_session, anthropic_client, allocate=True)

    rows = usage_report(
        db_session, org_id=ORG_ID, provider="anthropic", window=AUGUST, dimension="workspace"
    ).rows
    assert [(r.label, r.details["admins"], r.amount) for r in rows] == [
        ("Platform (wrkspc_redacted_a)", "alice@example.com", Decimal("60.11")),
        ("(default workspace)", "", Decimal("4.505")),
    ]

    top = usage_report(
        db_session, org_id=ORG_ID, provider="anthropic", window=AUGUST, dimension="model", top=1
    ).rows
    assert [(r.label, r.amount) for r in top] == [("claude-sonnet-4-6", Decimal("50"))]

    models = usage_report(
        db_session, org_id=ORG_ID, provider="anthropic", window=AUGUST, dimension="model"
    ).rows
    assert {r.label: r.amount for r in models} == {
        "claude-sonnet-4-6": Decimal("50"),
        "claude-opus-5": Decimal("4.615"),
        "(unallocated cost)": Decimal("10"),  # web search has no model
    }


def test_usage_report_applies_clauses_to_taxonomy_and_token_types(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    _synced(db_session, anthropic_client, allocate=True)

    models = usage_report(
        db_session,
        org_id=ORG_ID,
        provider="anthropic",
        window=AUGUST,
        dimension="model",
        filters={"model_family": FilterClause("not_contains", ("Sonnet",))},
    )
    assert "claude-sonnet-4-6" not in {row.label for row in models.rows}
    assert "claude-opus-5" in {row.label for row in models.rows}

    inputs = usage_report(
        db_session,
        org_id=ORG_ID,
        provider="anthropic",
        window=AUGUST,
        dimension="api_key",
        filters={"token_type": FilterClause("one_of", ("Input",))},
    )
    assert inputs.rows
    assert all(
        row.tokens["cache_read_tokens"] == row.tokens["output_tokens"] == 0 for row in inputs.rows
    )


def test_daily_series_preserves_derived_filter_expansion(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    _synced(db_session, anthropic_client, allocate=True)
    common = {
        "org_id": ORG_ID,
        "provider": "anthropic",
        "window": AUGUST,
        "dimension": "provider",
    }

    person = daily_series(
        db_session,
        **common,
        filters={"person": FilterClause("one_of", ("alice@example.com", "nobody@example.com"))},
    )
    not_nobody = daily_series(
        db_session,
        **common,
        filters={"person": FilterClause("not_one_of", ("nobody@example.com",))},
    )
    origin = daily_series(
        db_session,
        **common,
        filters={"origin": FilterClause("is", (provider_origin("anthropic"),))},
    )
    creator = daily_series(
        db_session,
        **common,
        filters={"creator": FilterClause("is", ("user_redacted_alice",))},
    )
    provider_account = (
        usage_report(
            db_session,
            **{key: value for key, value in common.items() if key != "dimension"},
            dimension="provider_account",
        )
        .rows[0]
        .key
    )
    assert provider_account is not None
    by_account = daily_series(
        db_session,
        **common,
        filters={"provider_account": FilterClause("is", (provider_account,))},
    )

    assert sum(person.total) > 0
    assert sum(not_nobody.total) == sum(origin.total) == Decimal("64.615")
    assert sum(creator.total) > Decimal("50")
    assert sum(by_account.total) == Decimal("64.615")
    with pytest.raises(ValueError, match="person supports only"):
        daily_series(
            db_session,
            **common,
            filters={"person": FilterClause("exists")},
        )


def test_usage_route_accepts_filter_clause_in_json_and_csv(
    client: TestClient,
    db_session: Session,
    anthropic_client: AnthropicAdminClient,
) -> None:
    _synced(db_session, anthropic_client, allocate=True)
    path = "/api/v1/orgs/default/providers/anthropic/months/2026-08/usage"
    params = [("by", "account"), ("f", "person:contains:@example.com")]

    response = client.get(path, params=params)
    csv_response = client.get(path, params=[*params, ("format", "csv")])

    assert response.status_code == csv_response.status_code == 200
    assert {row["label"] for row in response.json()["rows"]} == {"alice@example.com"}
    assert "alice@example.com" in csv_response.text


def test_usage_outside_window_is_empty(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    run_usage_sync(
        db_session,
        target(db_session, ORG_ID, "anthropic"),
        anthropic_client,
        FIXTURE_START,
        FIXTURE_END,
    )

    assert (
        usage_report(
            db_session,
            org_id=ORG_ID,
            provider="anthropic",
            window=Window.for_month("2026-09"),
            dimension="model",
        ).rows
        == []
    )


def test_usage_rejects_unknown_dimension(db_session: Session) -> None:
    with pytest.raises(ValueError, match="unknown dimension"):
        usage_report(
            db_session, org_id=ORG_ID, provider="anthropic", window=AUGUST, dimension="colour"
        )


@pytest.mark.parametrize(
    ("dimension", "ids"),
    [
        ("api_key", ("same", None, None, "model")),
        ("account", ("same-key", "same", None, "model")),
        ("creator", (None, "same", None, "model")),
        ("workspace", ("same-key", None, "same", "model")),
        ("model", ("same-key", None, None, "same")),
        ("api_key", (None, None, None, "model")),
        ("account", ("same-key", None, None, "model")),
        ("creator", (None, None, None, "model")),
        ("workspace", ("same-key", None, None, "model")),
        ("model", ("same-key", None, None, None)),
    ],
)
def test_group_identity_qualifies_ids_and_sentinels_by_provider(
    db_session: Session, dimension: str, ids: tuple[str | None, str | None, str | None, str | None]
) -> None:
    resolver = InventoryResolver(db_session, ORG_ID, "all")

    anthropic = group_key(resolver, dimension, "anthropic", *ids)
    openrouter = group_key(resolver, dimension, "openrouter", *ids)

    assert anthropic[0] == "anthropic" and openrouter[0] == "openrouter"
    assert anthropic[1] == openrouter[1]
    assert anthropic != openrouter
