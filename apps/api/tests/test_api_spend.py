import csv
import io
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from costura import secrets
from costura.accounts import create_account
from costura.api.deps import (
    get_session,
)
from costura.config import get_settings
from costura.models import (
    ProviderApiKey,
    ProviderSyncRun,
    ProviderUser,
    ProviderWorkspace,
    SpendAllocatedLine,
    SpendCostLine,
    User,
)
from costura.orgs import RESET_TABLES, create_org
from costura.providers.anthropic.client import AnthropicAdminClient
from costura.providers.anthropic.inventory import run_inventory_sync
from costura.providers.anthropic.sync import run_cost_sync, run_cost_total_sync, run_usage_sync
from costura.providers.openai import inventory as openai_inventory
from costura.providers.openai import sync as openai_sync
from costura.providers.openai.client import OpenAIAdminClient
from costura.providers.openrouter import inventory as openrouter_inventory
from costura.providers.openrouter import sync as openrouter_sync
from costura.providers.openrouter.client import OpenRouterManagementClient
from costura.spend.allocate import run_allocation
from costura.spend.projection import run_projection
from tests.conftest import (
    ORG_ID,
    OWNER_EMAIL,
    account_of,
    anthropic_fixture_handler,
    request_session,
    target,
)
from tests.support.queries import counted_statements
from tests.support.spend import AUGUST, FIXTURE_END, FIXTURE_START

BASE = "/api/v1/orgs/default/providers/anthropic"

ALL_BASE = "/api/v1/orgs/default/providers/all"

OPENROUTER_BASE = "/api/v1/orgs/default/providers/openrouter"

OPENAI_BASE = "/api/v1/orgs/default/providers/openai"

PERSON = "alice@example.com"

WRITE_ROUTES = {
    ("DELETE", "/orgs/{org}/accounts/{account_id}/credit-prices/{price_id}"),
    ("DELETE", "/orgs/{org}/invitations/{invitation_id}"),
    ("DELETE", "/orgs/{org}/members/{user_id}"),
    ("DELETE", "/orgs/{org}/providers/{provider}/accounts/{account_id}"),
    ("DELETE", "/orgs/{org}/providers/{provider}/accounts/{account_id}/key"),
    ("DELETE", "/orgs/{org}/providers/{provider}/budgets/{scope_kind}/{scope_id}"),
    ("DELETE", "/orgs/{org}/providers/{provider}/connection"),
    ("DELETE", "/orgs/{org}/providers/{provider}/owners/{kind}/{external_id}"),
    ("PATCH", "/orgs/{org}"),
    ("PATCH", "/orgs/{org}/members/{user_id}"),
    ("PATCH", "/orgs/{org}/providers/{provider}/accounts/{account_id}"),
    ("PATCH", "/orgs/{org}/providers/{provider}/anomalies/{anomaly_id}"),
    ("POST", "/orgs/{org}/accounts/{account_id}/credit-prices"),
    ("POST", "/orgs/{org}/alerts/read"),
    ("POST", "/orgs/{org}/invitations"),
    ("POST", "/orgs/{org}/providers/{provider}/accounts"),
    ("POST", "/orgs/{org}/providers/{provider}/sync"),
    ("POST", "/orgs/{org}/setup/dismiss"),
    ("POST", "/orgs/{org}/setup/reset"),
    ("PUT", "/orgs/{org}/alerts/settings"),
    ("PUT", "/orgs/{org}/providers/{provider}/accounts/{account_id}/key"),
    ("PUT", "/orgs/{org}/providers/{provider}/budgets/{scope_kind}/{scope_id}"),
    ("PUT", "/orgs/{org}/providers/{provider}/connection"),
    ("PUT", "/orgs/{org}/providers/{provider}/owners/{kind}/{external_id}"),
}

OWNER_ROUTES = {
    ("DELETE", "/orgs/{org}/invitations/{invitation_id}"),
    ("DELETE", "/orgs/{org}/providers/{provider}/accounts/{account_id}"),
    ("DELETE", "/orgs/{org}/providers/{provider}/accounts/{account_id}/key"),
    ("DELETE", "/orgs/{org}/providers/{provider}/budgets/{scope_kind}/{scope_id}"),
    ("DELETE", "/orgs/{org}/providers/{provider}/connection"),
    ("PATCH", "/orgs/{org}"),
    ("PATCH", "/orgs/{org}/members/{user_id}"),
    ("PATCH", "/orgs/{org}/providers/{provider}/accounts/{account_id}"),
    ("POST", "/orgs/{org}/invitations"),
    ("POST", "/orgs/{org}/providers/{provider}/accounts"),
    ("POST", "/orgs/{org}/setup/reset"),
    ("PUT", "/orgs/{org}/providers/{provider}/accounts/{account_id}/key"),
    ("PUT", "/orgs/{org}/providers/{provider}/budgets/{scope_kind}/{scope_id}"),
    ("PUT", "/orgs/{org}/providers/{provider}/connection"),
}

OPERATOR_ROUTES = {
    ("DELETE", "/orgs/{org}/accounts/{account_id}/credit-prices/{price_id}"),
    ("DELETE", "/orgs/{org}/providers/{provider}/owners/{kind}/{external_id}"),
    ("PATCH", "/orgs/{org}/providers/{provider}/anomalies/{anomaly_id}"),
    ("POST", "/orgs/{org}/accounts/{account_id}/credit-prices"),
    ("POST", "/orgs/{org}/providers/{provider}/sync"),
    ("POST", "/orgs/{org}/setup/dismiss"),
    ("PUT", "/orgs/{org}/providers/{provider}/owners/{kind}/{external_id}"),
}

PERSONAL_ROUTES = {
    ("DELETE", "/orgs/{org}/members/{user_id}"),
    ("POST", "/orgs/{org}/alerts/read"),
    ("PUT", "/orgs/{org}/alerts/settings"),
}

UNSCOPED_WRITE_ROUTES = {
    ("DELETE", "/auth/sessions"),
    ("POST", "/auth/dev-sign-in"),
    ("POST", "/auth/google/authorization"),
    ("POST", "/auth/google/callback"),
    ("POST", "/auth/sign-out"),
    ("POST", "/invitations/claim"),
    ("POST", "/invitations/{invitation_id}/accept"),
    ("POST", "/orgs"),
}

SEMANTIC_POST_ROUTES: set[tuple[str, str]] = set()

SETUP = "/api/v1/orgs/default/setup"


def _owner(session: Session) -> User:
    """The signed-in user behind the `api` client (see `conftest.owner_auth`)."""
    return session.scalar(select(User).where(User.email == OWNER_EMAIL))


@pytest.fixture
def api(db_session: Session, owner_auth: str) -> Iterator[TestClient]:
    from costura.main import app

    app.dependency_overrides[get_session] = request_session(db_session)
    try:
        with TestClient(app, headers={"Authorization": owner_auth}) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def synced(db_session: Session, anthropic_client: AnthropicAdminClient) -> None:
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
    run_inventory_sync(db_session, target(db_session, ORG_ID, "anthropic"), anthropic_client)
    run_allocation(db_session, ORG_ID, "anthropic", AUGUST)


@pytest.fixture
def both_synced(
    db_session: Session, synced: None, openrouter_client: OpenRouterManagementClient
) -> None:
    """Anthropic (64.62) and OpenRouter (14.50 billed, 17.00 BYOK) fixtures for August, both
    allocated."""
    openrouter_inventory.run_inventory_sync(
        db_session, target(db_session, ORG_ID, "openrouter"), openrouter_client
    )
    openrouter_sync.run_cost_sync(
        db_session,
        target(db_session, ORG_ID, "openrouter"),
        openrouter_client,
        AUGUST.start,
        AUGUST.end,
    )
    openrouter_sync.run_cost_total_sync(
        db_session,
        target(db_session, ORG_ID, "openrouter"),
        openrouter_client,
        AUGUST.start,
        AUGUST.end,
    )
    run_allocation(db_session, ORG_ID, "openrouter", AUGUST)


@pytest.fixture
def people_synced(db_session: Session, synced: None, openai_client: OpenAIAdminClient) -> None:
    """Anthropic and OpenAI fixtures for August, both allocated. `alice@example.com` is a user
    on both providers (`user_redacted_alice`, `user_x`); the OpenAI row spells it
    `Alice@example.com`."""
    openai_inventory.run_inventory_sync(
        db_session, target(db_session, ORG_ID, "openai"), openai_client
    )
    openai_sync.run_cost_sync(
        db_session, target(db_session, ORG_ID, "openai"), openai_client, AUGUST.start, AUGUST.end
    )
    openai_sync.run_usage_sync(
        db_session, target(db_session, ORG_ID, "openai"), openai_client, AUGUST.start, AUGUST.end
    )
    run_allocation(db_session, ORG_ID, "openai", AUGUST)


def _dependency_calls(dependant) -> set:
    calls = set()
    for dep in dependant.dependencies:
        calls.add(dep.call)
        calls |= _dependency_calls(dep)
    return calls


@pytest.fixture
def secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "costura_secret_key", SecretStr(secrets.generate_key()))


@pytest.fixture
def fixture_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """Route the clients the routes build at the JSON fixtures; a key ending in `-bad` is
    rejected with 401."""
    original_init = AnthropicAdminClient.__init__

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.headers["x-api-key"]
        if key.endswith("-bad"):
            return httpx.Response(401, json={"error": {"message": "invalid x-api-key"}})
        if key.endswith("-rate"):
            return httpx.Response(429, json={"error": {"message": "rate limited"}})
        if key.endswith("-down"):
            return httpx.Response(503, json={"error": {"message": "unavailable"}})
        if key.endswith("-timeout"):
            raise httpx.ReadTimeout("timed out", request=request)
        if key.endswith("-protocol"):
            return httpx.Response(400, json={"error": {"message": "unexpected request"}})
        return anthropic_fixture_handler(request)

    def patched_init(self, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        kwargs["sleep"] = lambda _: None
        original_init(self, **kwargs)

    monkeypatch.setattr(AnthropicAdminClient, "__init__", patched_init)
    monkeypatch.setattr("costura.sync_cycle.RETRY_BACKOFF_SECONDS", (0.0, 0.0))


@pytest.fixture
def intelligence(db_session: Session) -> None:
    """Ten weeks of synthetic spend with one spike, detected and projected as of Aug 21."""
    from datetime import date

    from costura.spend.anomalies import run_detection
    from tests.seed import seed_days
    from tests.test_anomalies import HISTORY_START, spiked

    seed_days(db_session, ORG_ID, "anthropic", HISTORY_START, date(2026, 8, 21), spiked)
    run_detection(db_session, ORG_ID, "anthropic", AUGUST)
    run_projection(db_session, ORG_ID, "anthropic", AUGUST, today=date(2026, 8, 21))


def _org_rows(session: Session, org_id: int) -> dict[str, int]:
    """Rows per tenant-scoped table (`RESET_TABLES`), so a reset can be checked table by table."""
    return {
        model.__tablename__: session.scalar(
            select(func.count()).select_from(model).where(model.organization_id == org_id)
        )
        or 0
        for model in RESET_TABLES
    }


def drain_queued_syncs() -> None:
    """Run every queued sync to completion, the way the worker does between requests."""
    from costura.ops.worker import drain

    drain(sleep=lambda _seconds: None)


def test_person_route_lists_identities_in_scope(api: TestClient, people_synced: None) -> None:
    body = api.get(f"{ALL_BASE}/months/2026-08/people/Alice@Example.com").json()

    assert body["email"] == PERSON and body["providers"] == ["anthropic", "openai"]
    identities = {(i["provider"], i["external_id"]): i for i in body["identities"]}
    assert set(identities) == {("anthropic", "user_redacted_alice"), ("openai", "user_x")}
    assert identities[("openai", "user_x")]["role"] == "owner"
    # key_a1 and key_b1 belong to user_x; key_a2 to the service account.
    assert identities[("openai", "user_x")]["keys_created"] == 2
    assert identities[("anthropic", "user_redacted_alice")]["missing"] is False

    concrete = api.get(f"{BASE}/months/2026-08/people/{PERSON}").json()
    assert concrete["providers"] == ["anthropic"] and len(concrete["identities"]) == 1

    assert api.get(f"{ALL_BASE}/months/2026-08/people/nobody@example.com").status_code == 404
    # A service account's name is not an address.
    assert api.get(f"{OPENAI_BASE}/months/2026-08/people/Eval bot").status_code == 404


def test_usage_by_person_folds_accounts_across_providers(
    api: TestClient, people_synced: None
) -> None:
    accounts = api.get(f"{ALL_BASE}/months/2026-08/usage", params={"by": "account"}).json()
    anthropic_alice = next(
        r
        for r in accounts["rows"]
        if r["key"] == "user_redacted_alice" and r["provider"] == "anthropic"
    )
    openai_alice = next(r for r in accounts["rows"] if r["key"] == "user_x")
    assert anthropic_alice["person"] == PERSON and openai_alice["person"] == PERSON
    service = next(r for r in accounts["rows"] if r["key"] == "svc_eval")
    assert service["person"] is None and service["label"].startswith("Eval bot")

    people = api.get(f"{ALL_BASE}/months/2026-08/usage", params={"by": "person"}).json()
    assert people["dimension"] == "person" and people["allocated"] is True
    alice = next(r for r in people["rows"] if r["key"] == PERSON)
    assert alice["label"] == PERSON and alice["person"] == PERSON
    assert alice["provider"] == "anthropic"
    assert alice["details"] == {"kind": "person", "providers": "anthropic"}
    assert alice["amount"] == anthropic_alice["amount"]
    assert alice["total_tokens"] == anthropic_alice["total_tokens"]
    # Service API keys remain provider-scoped and do not imply personal spend.
    still_service = next(
        r for r in people["rows"] if r["key"] is None and r["provider"] == "openai"
    )
    assert still_service["provider"] == "openai"
    assert still_service["person"] is None
    assert "(unallocated cost)" in [r["label"] for r in people["rows"]]

    # Under a concrete provider the person row is that provider's account only.
    openai_only = api.get(f"{OPENAI_BASE}/months/2026-08/usage", params={"by": "person"}).json()
    assert PERSON not in {row["key"] for row in openai_only["rows"]}


def test_person_filter_keeps_one_email_across_providers(
    api: TestClient, people_synced: None
) -> None:
    by_account = api.get(
        f"{ALL_BASE}/months/2026-08/usage", params={"by": "account", "person": PERSON}
    ).json()
    assert {(r["provider"], r["key"]) for r in by_account["rows"]} == {
        ("anthropic", "user_redacted_alice"),
    }
    by_provider = api.get(
        f"{ALL_BASE}/months/2026-08/usage", params={"by": "provider", "person": PERSON}
    ).json()
    assert {r["key"] for r in by_provider["rows"]} == {"anthropic"}
    by_clause = api.get(
        f"{ALL_BASE}/months/2026-08/usage",
        params=[
            ("by", "provider"),
            ("f", f"person:one_of:{PERSON},nobody@example.com"),
        ],
    ).json()
    assert {r["key"] for r in by_clause["rows"]} == {"anthropic"}
    by_key = api.get(
        f"{ALL_BASE}/months/2026-08/usage", params={"by": "api_key", "person": PERSON}
    ).json()
    assert {r["key"] for r in by_key["rows"]} == {None}

    series = api.get(
        f"{ALL_BASE}/months/2026-08/series", params={"by": "provider", "person": PERSON}
    ).json()
    assert {s["key"] for s in series["series"]} == {"anthropic"}
    assert sum(Decimal(value) for value in series["total"]) > 0

    nobody = api.get(
        f"{ALL_BASE}/months/2026-08/usage", params={"by": "account", "person": "nobody@x.io"}
    ).json()
    assert nobody["rows"] == []


def test_query_filter_clause_rejects_unknown_operator(client: TestClient) -> None:
    response = client.get(
        "/api/v1/orgs/default/query",
        params={
            "start": "2026-08-01",
            "end": "2026-08-31",
            "f": "workspace:equals:platform",
        },
    )

    assert response.status_code == 422
    assert "filter op must be one of" in response.json()["detail"]


def test_activity_route_aggregates_and_filters_openai_usage(
    db_session: Session, client: TestClient, openai_client: OpenAIAdminClient
) -> None:
    unit = target(db_session, ORG_ID, "openai")
    openai_sync.run_cost_sync(db_session, unit, openai_client, FIXTURE_START, FIXTURE_END)
    openai_sync.run_activity_sync(
        db_session,
        unit,
        openai_client,
        FIXTURE_START,
        FIXTURE_END,
        family="embeddings",
    )

    response = client.get(
        "/api/v1/orgs/default/activity",
        params={
            "since": "2026-08-01",
            "until": "2026-08-31",
            "family": "embeddings",
            "provider_account": unit.account_id,
            "workspace": "proj_a",
        },
    )
    assert response.status_code == 200
    assert response.headers["X-Total-Count"] == "1"
    assert response.json() == [
        {
            "family": "embeddings",
            "unit": "input_tokens",
            "quantity": "25000.00000000",
            "requests": 5,
            "billed_usd": "0.10",
            "cost_per_unit": "0.00000400",
        }
    ]

    by_key = client.get(
        "/api/v1/orgs/default/activity",
        params={
            "since": "2026-08-01",
            "until": "2026-08-31",
            "family": "embeddings",
            "api_key": "key_a1",
        },
    )
    assert by_key.status_code == 200
    assert by_key.json()[0]["billed_usd"] == "0.00"
    assert (
        client.get(
            "/api/v1/orgs/default/activity",
            params={"since": "2026-09-01", "until": "2026-08-01"},
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/api/v1/orgs/default/activity",
            params={"since": "2026-08-01", "until": "2026-08-31", "family": "unknown"},
        ).status_code
        == 422
    )


def test_orgs_and_months(api: TestClient, db_session: Session, synced: None) -> None:
    # The listing is the caller's memberships: `acme` appears once the owner is a member.
    create_org(db_session, "acme", "Acme", owner=_owner(db_session))

    response = api.get("/api/v1/orgs")
    assert response.status_code == 200
    assert [{k: v for k, v in o.items() if k != "created_at"} for o in response.json()] == [
        {"slug": "acme", "name": "Acme", "is_demo": False, "role": "owner"},
        {"slug": "default", "name": "Default", "is_demo": False, "role": "owner"},
    ]

    assert api.get(f"{BASE}/months").json() == {"months": ["2026-08"]}
    assert api.get("/api/v1/orgs/acme/providers/anthropic/months").json() == {"months": []}


def test_unknown_org_provider_and_bad_month(api: TestClient, db_session: Session) -> None:
    assert api.get("/api/v1/orgs/ghost/providers/anthropic/months").status_code == 404
    assert api.get("/api/v1/orgs/default/providers/bedrock/months").status_code == 404
    assert api.get(f"{OPENROUTER_BASE}/months").json() == {"months": []}
    bad_month = api.get(f"{BASE}/months/2026-13/summary")
    assert bad_month.status_code == 422
    assert api.get(f"{BASE}/months/202608/summary").status_code == 422
    assert api.get(f"{BASE}/months/2026-08/usage?by=colour").status_code == 422
    assert api.get(f"{BASE}/months/2026-08/usage?top=0").status_code == 422
    assert api.get(f"{BASE}/months/2026-08/reconcile?by=colour").status_code == 422


def test_usage_matches_cli_report(api: TestClient, synced: None) -> None:
    body = api.get(f"{BASE}/months/2026-08/usage", params={"by": "api_key"}).json()

    assert body["dimension"] == "api_key" and body["allocated"] is True
    assert body["cost_total"] == "64.62"
    labels = [row["label"] for row in body["rows"]]
    assert "batch-ingest (apikey_redacted_2)" in labels
    assert "(unallocated cost)" in labels
    batch = next(row for row in body["rows"] if row["key"] == "apikey_redacted_2")
    assert batch["total_tokens"] == 29500
    assert batch["details"]["created_by"] == "bob@example.com"
    assert batch["amount"] is not None and batch["share"] is not None

    top = api.get(f"{BASE}/months/2026-08/usage", params={"by": "workspace", "top": 1}).json()
    assert len(top["rows"]) == 1
    assert top["rows"][0]["label"] == "Platform (wrkspc_redacted_a)"

    empty = api.get(f"{BASE}/months/2026-09/usage").json()
    assert empty["rows"] == [] and empty["allocated"] is False

    spanning = {"start": "2026-07-15", "end": "2026-09-15"}
    assert api.get(f"{BASE}/months/2026-09/usage", params=spanning).json()["cost_total"] == "64.62"
    series = api.get(f"{BASE}/months/2026-09/series", params=spanning).json()
    assert (series["days"][0], series["days"][-1]) == ("2026-07-15", "2026-09-15")
    reconciled = api.get(f"{BASE}/months/2026-09/reconcile", params=spanning).json()
    assert reconciled["costura_total"] == "64.62"


def test_usage_filters_drill_down(api: TestClient, synced: None) -> None:
    everything = api.get(f"{BASE}/months/2026-08/usage", params={"by": "model"}).json()
    platform = api.get(
        f"{BASE}/months/2026-08/usage", params={"by": "model", "workspace": "wrkspc_redacted_a"}
    ).json()
    assert platform["allocated"] is True
    assert Decimal(platform["cost_total"]) < Decimal(everything["cost_total"])
    assert all(row["amount"] is not None for row in platform["rows"])

    by_key = api.get(
        f"{BASE}/months/2026-08/usage", params={"by": "api_key", "workspace": "wrkspc_redacted_a"}
    ).json()
    assert "batch-ingest (apikey_redacted_2)" in [row["label"] for row in by_key["rows"]]

    default_ws = api.get(
        f"{BASE}/months/2026-08/usage",
        params={"by": "api_key", "workspace": "__default_workspace__"},
    ).json()
    assert default_ws["rows"], "sentinel filter selects lines with NULL workspace_id"

    nothing = api.get(f"{BASE}/months/2026-08/usage", params={"api_key": "apikey_ghost"}).json()
    assert nothing["rows"] == []


def test_movers_ranks_both_directions_and_names_the_keys_that_appeared(
    api: TestClient, db_session: Session
) -> None:
    from tests.seed import seed_days

    def july(day: date) -> list[tuple[str | None, str, str, Decimal]]:
        return [
            ("wrkspc_a", "claude-sonnet-4", "apikey_steady", Decimal("10.00")),
            ("wrkspc_a", "claude-sonnet-4", "apikey_gone", Decimal("6.00")),
        ]

    def august(day: date) -> list[tuple[str | None, str, str, Decimal]]:
        return [
            ("wrkspc_a", "claude-sonnet-4", "apikey_steady", Decimal("10.00")),
            ("wrkspc_a", "claude-opus-4-1", "apikey_new", Decimal("20.00")),
        ]

    seed_days(db_session, ORG_ID, "anthropic", date(2026, 7, 1), date(2026, 8, 1), july)
    seed_days(db_session, ORG_ID, "anthropic", date(2026, 8, 1), date(2026, 9, 1), august)

    body = api.get(f"{BASE}/months/2026-08/movers", params={"by": "api_key"}).json()

    assert body["dimension"] == "api_key" and body["allocated"] is True
    assert body["previous_month"] == "2026-07"
    rows = {row["key"]: row for row in body["rows"]}
    # 31 days of 20.00 that July did not have, against 31 days of 6.00 that stopped.
    assert [row["key"] for row in body["rows"]] == ["apikey_new", "apikey_gone"]
    assert rows["apikey_new"]["delta"] == "620.00"
    assert rows["apikey_new"]["previous_amount"] == "0.00"
    assert rows["apikey_new"]["change_percent"] is None
    assert rows["apikey_new"]["is_new"] is True and rows["apikey_new"]["is_gone"] is False
    assert rows["apikey_gone"]["delta"] == "-186.00"
    assert rows["apikey_gone"]["change_percent"] == "-100.00"
    assert rows["apikey_gone"]["is_gone"] is True
    # A key that spent the same on both sides moved nothing, so it is not a mover.
    assert "apikey_steady" not in rows

    top = api.get(f"{BASE}/months/2026-08/movers", params={"by": "api_key", "top": 1}).json()
    assert [row["key"] for row in top["rows"]] == ["apikey_new"]

    ten_days = api.get(
        f"{BASE}/months/2026-08/movers",
        params={"by": "api_key", "start": "2026-08-01", "end": "2026-08-10"},
    ).json()
    assert (ten_days["previous_start"], ten_days["previous_end"]) == ("2026-07-22", "2026-07-31")
    assert {row["key"]: row["delta"] for row in ten_days["rows"]} == {
        "apikey_new": "200.00",
        "apikey_gone": "-60.00",
    }
    assert api.get(f"{BASE}/months/2026-08/movers", params={"by": "colour"}).status_code == 422
    assert api.get(f"{BASE}/months/2026-08/movers", params={"top": 0}).status_code == 422


def test_movers_of_a_month_in_progress_compare_the_same_days(
    api: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from costura.spend import summary as summary_module
    from tests.seed import seed_days

    def steady(day: date) -> list[tuple[str | None, str, str, Decimal]]:
        return [("wrkspc_a", "claude-sonnet-4", "apikey_steady", Decimal("10.00"))]

    class FixedDatetime:
        @staticmethod
        def now(tz: object) -> datetime:
            return datetime(2026, 8, 15, tzinfo=tz)  # type: ignore[arg-type]

    seed_days(db_session, ORG_ID, "anthropic", date(2026, 7, 1), date(2026, 8, 1), steady)
    seed_days(db_session, ORG_ID, "anthropic", date(2026, 8, 1), date(2026, 8, 15), steady)
    monkeypatch.setattr(summary_module, "datetime", FixedDatetime)

    body = api.get(f"{BASE}/months/2026-08/movers", params={"by": "api_key"}).json()

    assert (body["previous_start"], body["previous_end"]) == ("2026-07-01", "2026-07-14")
    assert body["allocated"] is True and body["rows"] == []


def test_movers_reports_no_ranking_when_a_month_has_no_allocation(
    api: TestClient, synced: None
) -> None:
    # August is allocated, July has nothing: every delta would be August's whole amount.
    body = api.get(f"{BASE}/months/2026-08/movers").json()

    assert body["allocated"] is False and body["rows"] == []
    assert body["previous_month"] == "2026-07"


def test_usage_csv(api: TestClient, synced: None) -> None:
    response = api.get(f"{BASE}/months/2026-08/usage", params={"by": "api_key", "format": "csv"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "usage-by-api_key.csv" in response.headers["content-disposition"]
    lines = response.text.strip().splitlines()
    assert lines[0].startswith("key,label,provider,amount,share,uncached_input_tokens,")
    assert any("apikey_redacted_2,batch-ingest (apikey_redacted_2)," in line for line in lines)
    assert api.get(f"{BASE}/months/2026-08/usage", params={"format": "xml"}).status_code == 422


def test_usage_csv_neutralizes_provider_text_without_changing_json_or_numbers(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from costura.spend.usage import TOKEN_COLUMNS, UsageReport, UsageRow

    dangerous = ("=SUM(A1:A2)", "\t+cmd", "\u200b-10", " @payload")
    tokens = {name: index + 1 for index, name in enumerate(TOKEN_COLUMNS)}
    report = UsageReport(
        dimension="api_key",
        allocated=True,
        cost_total=Decimal("12.34"),
        rows=[
            UsageRow(
                key=dangerous[0],
                label=dangerous[1],
                provider="anthropic",
                amount=Decimal("12.34"),
                share=Decimal("100.00"),
                tokens=tokens,
                web_search_requests=7,
            ),
            UsageRow(
                key=dangerous[2],
                label=dangerous[3],
                provider="anthropic",
                amount=Decimal("0"),
                share=Decimal("0"),
                tokens=tokens,
                web_search_requests=8,
            ),
        ],
    )
    monkeypatch.setattr("costura.api.routers.spend.usage_report", lambda *_args, **_kwargs: report)

    path = f"{BASE}/months/2026-08/usage"
    csv_rows = list(csv.reader(io.StringIO(api.get(path, params={"format": "csv"}).text)))
    assert csv_rows[1][:5] == [
        f"'{dangerous[0]}",
        f"'{dangerous[1]}",
        "anthropic",
        "12.34",
        "100.00",
    ]
    assert csv_rows[2][:5] == [
        f"'{dangerous[2]}",
        f"'{dangerous[3]}",
        "anthropic",
        "0.00",
        "0.00",
    ]
    assert csv_rows[1][-2] == "7"

    json_rows = api.get(path).json()["rows"]
    assert [(row["key"], row["label"]) for row in json_rows] == [
        (dangerous[0], dangerous[1]),
        (dangerous[2], dangerous[3]),
    ]


def test_series_csv_neutralizes_provider_controlled_headers_only(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from costura.spend.usage import DailySeries, Series

    labels = ("=formula", " +formula", "\t-formula", "\u200b@formula")
    result = DailySeries(
        dimension="model",
        days=[date(2026, 8, 1)],
        series=[
            Series(key=str(index), label=label, values=[Decimal(index)], provider="anthropic")
            for index, label in enumerate(labels, start=1)
        ],
        other=None,
        total=[Decimal("10")],
        source="cost",
    )
    monkeypatch.setattr("costura.api.routers.spend.daily_series", lambda *_args, **_kwargs: result)

    path = f"{BASE}/months/2026-08/series"
    csv_rows = list(csv.reader(io.StringIO(api.get(path, params={"format": "csv"}).text)))
    assert csv_rows[0] == ["day", *(f"'{label}" for label in labels)]
    assert csv_rows[1] == ["2026-08-01", "1.00", "2.00", "3.00", "4.00"]
    assert [series["label"] for series in api.get(path).json()["series"]] == list(labels)


def test_series(api: TestClient, synced: None) -> None:
    reconcile_total = Decimal(api.get(f"{BASE}/months/2026-08/reconcile").json()["costura_total"])

    body = api.get(f"{BASE}/months/2026-08/series", params={"by": "workspace"}).json()
    assert body["dimension"] == "workspace" and body["source"] == "allocated"
    assert len(body["days"]) == 31 and body["days"][0] == "2026-08-01"
    assert all(len(s["values"]) == 31 for s in body["series"])
    assert len(body["total"]) == 31
    assert Decimal(body["month_total"]) == reconcile_total
    # Per-day values are rounded to cents individually; the sum may differ by rounding only.
    assert abs(sum(Decimal(v) for v in body["total"]) - reconcile_total) <= Decimal("0.31")
    labels = [s["label"] for s in body["series"]]
    assert "Platform (wrkspc_redacted_a)" in labels and "(default workspace)" in labels
    assert body["other"] is None
    assert body["total"][10] == "0.00"  # 2026-08-11 has no lines in the fixture

    keys = api.get(f"{BASE}/months/2026-08/series", params={"by": "api_key", "top": 1}).json()
    assert len(keys["series"]) == 1 and keys["other"] is not None
    assert Decimal(keys["month_total"]) == reconcile_total
    other_total = sum(Decimal(v) for v in keys["other"])
    assert abs(Decimal(keys["series"][0]["total"]) + other_total - reconcile_total) <= Decimal(
        "0.31"
    )

    single = api.get(f"{BASE}/months/2026-08/series", params={"by": "none"}).json()
    assert [s["label"] for s in single["series"]] == ["total"]

    filtered = api.get(
        f"{BASE}/months/2026-08/series",
        params={"by": "model", "workspace": "wrkspc_redacted_a"},
    ).json()
    assert Decimal(filtered["month_total"]) < reconcile_total

    csv_body = api.get(f"{BASE}/months/2026-08/series", params={"by": "workspace", "format": "csv"})
    assert csv_body.headers["content-type"].startswith("text/csv")
    assert csv_body.text.splitlines()[0].startswith("day,")
    assert len(csv_body.text.strip().splitlines()) == 32

    assert api.get(f"{BASE}/months/2026-08/series", params={"by": "colour"}).status_code == 422
    assert api.get(f"{BASE}/months/2026-08/series", params={"top": 0}).status_code == 422


def test_series_before_allocation_falls_back_to_cost_lines(
    api: TestClient, db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    run_cost_sync(
        db_session,
        target(db_session, ORG_ID, "anthropic"),
        anthropic_client,
        FIXTURE_START,
        FIXTURE_END,
    )

    by_workspace = api.get(f"{BASE}/months/2026-08/series", params={"by": "workspace"}).json()
    assert by_workspace["source"] == "cost"
    assert by_workspace["series"]
    reconcile_total = Decimal(api.get(f"{BASE}/months/2026-08/reconcile").json()["costura_total"])
    assert Decimal(by_workspace["month_total"]) == reconcile_total

    by_key = api.get(f"{BASE}/months/2026-08/series", params={"by": "api_key"}).json()
    assert by_key["series"] == []


def test_summary(api: TestClient, synced: None) -> None:
    body = api.get(f"{BASE}/months/2026-08/summary").json()
    assert body["month"] == "2026-08" and body["currency"] == "USD"
    assert body["total"] == "64.62"
    assert body["previous_month"] == "2026-07"
    assert body["previous_total"] is None and body["change_percent"] is None
    assert body["days_in_month"] == 31
    assert body["days_with_data"] >= 1
    assert body["last_day_with_data"] is not None
    assert body["daily_average"] is not None
    assert body["is_current_month"] is False and body["projected_total"] is None
    assert body["top_key_count"] >= 1
    assert Decimal(body["top_keys_share"]) <= 100
    assert body["cache_read_share"] is not None
    assert body["tokens"]["uncached_input_tokens"] > 0
    assert body["allocation"]["ok"] is True
    assert body["byok_total"] is None

    assert (body["start"], body["end"]) == ("2026-08-01", "2026-08-31")
    # The cost sync covered August 1-4 only, so the month is compared with July 1-4.
    assert (body["complete_through"], body["data_stale"]) == ("2026-08-04", False)
    assert (body["previous_start"], body["previous_end"]) == ("2026-07-01", "2026-07-04")
    assert body["comparison_basis"] == "month_to_date"

    september = api.get(f"{BASE}/months/2026-09/summary").json()
    assert september["total"] == "0.00"
    assert september["previous_total"] == "64.62"
    assert september["change_percent"] == "-100.00"
    assert september["top_keys_share"] is None and september["cache_read_share"] is None


def test_summary_over_a_date_range_compares_with_the_days_before_it(
    api: TestClient, synced: None
) -> None:
    body = api.get(
        f"{BASE}/months/2026-09/summary", params={"start": "2026-08-01", "end": "2026-09-30"}
    ).json()
    assert body["total"] == "64.62"
    assert (body["start"], body["end"]) == ("2026-08-01", "2026-09-30")
    assert (body["previous_start"], body["previous_end"]) == ("2026-06-01", "2026-07-31")
    assert body["previous_total"] is None
    assert body["days_in_month"] == 61
    assert body["projected_total"] is None

    after = api.get(
        f"{BASE}/months/2026-09/summary", params={"start": "2026-09-01", "end": "2026-09-30"}
    ).json()
    assert (after["previous_start"], after["previous_end"]) == ("2026-08-01", "2026-08-31")
    assert after["previous_total"] == "64.62"

    shifted = api.get(
        f"{BASE}/months/2026-09/summary", params={"start": "2026-09-02", "end": "2026-10-01"}
    ).json()
    assert (shifted["previous_start"], shifted["previous_end"]) == ("2026-08-03", "2026-09-01")


def test_dates_outside_2000_to_2099_answer_422(api: TestClient) -> None:
    for month in ("0000-01", "1999-12", "9999-12"):
        assert api.get(f"{BASE}/months/{month}/summary").status_code == 422
    for start, end in (("0001-01-01", "0001-01-31"), ("2099-12-01", "9999-12-31")):
        response = api.get(f"{BASE}/months/2026-09/summary", params={"start": start, "end": end})
        assert response.status_code == 422
    activity = api.get(
        "/api/v1/orgs/default/activity", params={"since": "2026-01-01", "until": "9999-12-31"}
    )
    assert activity.status_code == 422
    reversed_range = api.get(
        "/api/v1/orgs/default/activity", params={"since": "2026-02-01", "until": "2026-01-01"}
    )
    assert reversed_range.status_code == 422


def test_reconcile_with_and_without_reported(api: TestClient, synced: None) -> None:
    without = api.get(f"{BASE}/months/2026-08/reconcile").json()
    assert without["costura_total"] == "64.62"
    assert without["costura_total_exact"] == "64.61500000"
    assert without["reported_total"] is None and without["delta"] is None
    assert without["matches"] is None
    assert without["breakdown_dimension"] == "day" and len(without["breakdown"]) == 31
    # The fixture sync window ([08-01, 08-05)) does not cover the month, so no raw check.
    assert without["raw_check"] is None
    assert without["provider_check"] is None
    assert without["allocation"]["ok"] is True
    # Anthropic publishes no per-key money, so the fourth check is neither pending nor run.
    assert without["key_check"] is None and without["key_check_supported"] is False
    assert without["token_totals"]["uncached_input_tokens"] > 0

    with_reported = api.get(
        f"{BASE}/months/2026-08/reconcile", params={"reported": "64.62", "by": "workspace"}
    ).json()
    assert with_reported["reported_total"] == "64.62"
    assert with_reported["matches"] is True
    assert with_reported["delta"] in ("-0.01", "0.00", "-0.00")
    labels = [row["label"] for row in with_reported["breakdown"]]
    assert "(default workspace)" in labels and "Platform (wrkspc_redacted_a)" in labels

    off = api.get(f"{BASE}/months/2026-08/reconcile", params={"reported": "1000"}).json()
    assert off["matches"] is False and off["delta_percent"] is not None


def test_runs(api: TestClient, synced: None) -> None:
    body = api.get(f"{BASE}/runs").json()
    runs = body["runs"]
    assert len(runs) == 7
    assert [run["id"] for run in runs] == sorted((run["id"] for run in runs), reverse=True)
    assert all(run["status"] == "succeeded" for run in runs)
    assert all(run["duration_seconds"] is not None for run in runs)

    only_cost = api.get(f"{BASE}/runs", params={"endpoint": "cost_report", "limit": 1}).json()
    assert [run["endpoint"] for run in only_cost["runs"]] == ["cost_report"]
    assert api.get(f"{BASE}/runs", params={"limit": 0}).status_code == 422


def test_inventory_routes(api: TestClient, synced: None) -> None:
    keys = api.get(f"{BASE}/inventory/api-keys").json()["items"]
    batch = next(key for key in keys if key["external_id"] == "apikey_redacted_2")
    assert batch["name"] == "batch-ingest"
    assert batch["workspace"] == "Platform (wrkspc_redacted_a)"
    assert batch["created_by"] == "bob@example.com"
    assert batch["missing"] is False and batch["missing_since"] is None

    workspaces = api.get(f"{BASE}/inventory/workspaces").json()["items"]
    platform = next(w for w in workspaces if w["external_id"] == "wrkspc_redacted_a")
    assert platform["admins"] == ["alice@example.com"]
    assert platform["api_keys"] >= 1

    users = api.get(f"{BASE}/inventory/users").json()["items"]
    assert "alice@example.com" in [user["email"] for user in users]

    with_flag = api.get(f"{BASE}/inventory/api-keys", params={"include_missing": "false"})
    assert with_flag.status_code == 200
    assert all(item["missing"] is False for item in with_flag.json()["items"])


def test_inventory_single_item_routes(api: TestClient, synced: None) -> None:
    key = api.get(f"{BASE}/inventory/api-keys/apikey_redacted_2").json()
    assert key["name"] == "batch-ingest" and key["created_by"] == "bob@example.com"

    workspace = api.get(f"{BASE}/inventory/workspaces/wrkspc_redacted_a").json()
    assert workspace["name"] == "Platform" and workspace["api_keys"] >= 1
    assert workspace["admins"] == ["alice@example.com"]

    users = api.get(f"{BASE}/inventory/users").json()["items"]
    alice = next(u for u in users if u["email"] == "alice@example.com")
    assert api.get(f"{BASE}/inventory/users/{alice['external_id']}").json() == alice

    for path in ("api-keys/nope", "workspaces/nope", "users/nope"):
        assert api.get(f"{BASE}/inventory/{path}").status_code == 404


def test_reconcile_provider_check_after_control_total_sync(
    api: TestClient, db_session: Session, anthropic_client: AnthropicAdminClient, synced: None
) -> None:
    run_cost_total_sync(
        db_session,
        target(db_session, ORG_ID, "anthropic"),
        anthropic_client,
        AUGUST.start,
        AUGUST.end,
    )

    body = api.get(f"{BASE}/months/2026-08/reconcile").json()
    check = body["provider_check"]
    assert check["ok"] is True
    assert check["provider_total"] == "64.62" and check["delta"] == "0.00"

    summary = api.get(f"{BASE}/months/2026-08/summary").json()
    assert summary["provider_total"] == "64.62" and summary["provider_matches"] is True
    assert summary["provider_difference"] == "0.00"

    runs = api.get(f"{BASE}/runs", params={"endpoint": "cost_total"}).json()["runs"]
    assert len(runs) == 1 and runs[0]["rows_upserted"] == 0


def test_budget_upsert_validation_and_delete(api: TestClient, synced: None) -> None:
    assert api.get(f"{BASE}/budgets").json() == {"budgets": []}

    created = api.put(f"{BASE}/budgets/org/__org__", json={"amount": "1000"})
    assert created.status_code == 200
    body = created.json()
    assert (body["scope_kind"], body["scope_id"], body["label"]) == (
        "org",
        "__org__",
        "organization total",
    )
    assert (body["amount"], body["currency"]) == ("1000.00", "USD")
    assert body["thresholds"] == [50, 80, 100]

    # PUT replaces amount and thresholds in place (same id) and sorts the thresholds.
    replaced = api.put(
        f"{BASE}/budgets/org/__org__", json={"amount": "1500.5", "thresholds": [90, 60, 60]}
    ).json()
    assert replaced["id"] == body["id"]
    assert (replaced["amount"], replaced["thresholds"]) == ("1500.50", [60, 90])

    workspace = api.put(f"{BASE}/budgets/workspace/wrkspc_redacted_a", json={"amount": "400"})
    assert workspace.status_code == 200
    assert workspace.json()["label"] == "Platform (wrkspc_redacted_a)"
    listed = api.get(f"{BASE}/budgets").json()["budgets"]
    assert [(b["scope_kind"], b["scope_id"]) for b in listed] == [
        ("org", "__org__"),
        ("workspace", "wrkspc_redacted_a"),
    ]

    assert api.put(f"{BASE}/budgets/workspace/wrkspc_nope", json={"amount": "1"}).status_code == 404
    assert api.put(f"{BASE}/budgets/api_key/k", json={"amount": "1"}).status_code == 422
    assert api.put(f"{BASE}/budgets/org/__org__", json={"amount": "0"}).status_code == 422
    assert api.put(f"{BASE}/budgets/org/__org__", json={"amount": "-5"}).status_code == 422
    for thresholds in ([0], [300], []):
        body = {"amount": "5", "thresholds": thresholds}
        assert api.put(f"{BASE}/budgets/org/__org__", json=body).status_code == 422

    assert api.delete(f"{BASE}/budgets/workspace/wrkspc_redacted_a").status_code == 204
    assert api.delete(f"{BASE}/budgets/workspace/wrkspc_redacted_a").status_code == 404
    assert [b["scope_id"] for b in api.get(f"{BASE}/budgets").json()["budgets"]] == ["__org__"]


def test_budget_statuses_for_the_month(
    api: TestClient, db_session: Session, intelligence: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import date, datetime

    from costura.spend import budgets as budgets_module
    from costura.spend.budgets import evaluate_budgets

    class FixedDatetime:
        @staticmethod
        def now(tz: object) -> datetime:
            return datetime(2026, 8, 21, tzinfo=tz)  # type: ignore[arg-type]

    # August is the current month for the read, so the stored projection is part of the status.
    monkeypatch.setattr(budgets_module, "datetime", FixedDatetime)
    api.put(f"{BASE}/budgets/org/__org__", json={"amount": "2000", "thresholds": [50, 80, 100]})
    empty = api.get(f"{BASE}/months/2026-08/budgets").json()
    [before] = empty["statuses"]
    assert (before["spent"], before["percent"]) == ("1960.00", "98.00")
    assert before["highest_crossed"] is None
    assert before["alerts"] == [] and empty["alerts"] == []
    # The stored projection (2,740) is read even before the evaluation stores alerts.
    assert (before["projected"], before["projected_percent"]) == ("2740.00", "137.00")

    evaluate_budgets(db_session, ORG_ID, "anthropic", AUGUST, today=date(2026, 8, 21))
    body = api.get(f"{BASE}/months/2026-08/budgets").json()

    assert body["month"] == "2026-08"
    [status] = body["statuses"]
    assert status["budget"]["label"] == "organization total"
    assert (status["highest_crossed"], status["projection_exceeds"]) == (80, True)
    assert [(t["percent"], t["crossed_at"] is not None) for t in status["thresholds"]] == [
        (50, True),
        (80, True),
        (100, False),
    ]
    assert sorted((a["kind"], a["threshold"]) for a in body["alerts"]) == [
        ("projection", None),
        ("threshold", 50),
        ("threshold", 80),
    ]
    projection = next(a for a in body["alerts"] if a["kind"] == "projection")
    assert (projection["spent"], projection["projected"], projection["amount"]) == (
        "1960.00",
        "2740.00",
        "2000.00",
    )
    assert projection["label"] == "organization total"

    # A month without a stored projection carries no projected figure.
    july = api.get(f"{BASE}/months/2026-07/budgets").json()
    assert july["statuses"][0]["projected"] is None and july["alerts"] == []


def test_all_scope_unions_every_provider(api: TestClient, both_synced: None) -> None:
    """`all` reads the union: totals add up, `by=provider` splits by connector, every row
    names its provider, and `?provider=` narrows to one."""
    assert api.get(f"{ALL_BASE}/months").json() == {"months": ["2026-08"]}

    summary = api.get(f"{ALL_BASE}/months/2026-08/summary").json()
    assert summary["total"] == "79.12" and summary["currency"] == "USD"
    assert summary["allocation"]["ok"] is True
    # Anthropic has cost lines but no control-total run, so the org-wide provider figure is
    # unknown rather than a partial sum of OpenRouter alone (reconcile._sum_over_scope).
    assert summary["provider_total"] is None
    # BYOK inference is billed by the providers, so it is shown next to the total, not in it.
    assert summary["byok_total"] == "17.00"
    openrouter_summary = api.get(f"{OPENROUTER_BASE}/months/2026-08/summary").json()
    assert openrouter_summary["total"] == "14.50" and openrouter_summary["byok_total"] == "17.00"
    assert openrouter_summary["provider_total"] == "14.50"
    assert openrouter_summary["provider_matches"] is True

    by_provider = api.get(f"{ALL_BASE}/months/2026-08/usage", params={"by": "provider"}).json()
    assert by_provider["cost_total"] == "79.12"
    rows = {row["key"]: row for row in by_provider["rows"]}
    assert set(rows) == {"anthropic", "openrouter"}
    assert rows["anthropic"]["label"] == "Anthropic" and rows["anthropic"]["amount"] == "64.62"
    assert rows["anthropic"]["byok_amount"] is None
    assert rows["openrouter"]["label"] == "OpenRouter" and rows["openrouter"]["amount"] == "14.50"
    assert rows["openrouter"]["byok_amount"] == "17.00"
    assert rows["openrouter"]["tokens"]["reasoning_tokens"] > 0
    assert rows["openrouter"]["provider"] == "openrouter"

    by_key = api.get(f"{ALL_BASE}/months/2026-08/usage", params={"by": "api_key"}).json()
    providers = {row["provider"] for row in by_key["rows"] if row["key"] is not None}
    assert providers == {"anthropic", "openrouter"}
    batch = next(row for row in by_key["rows"] if row["key"] == "apikey_redacted_2")
    assert batch["provider"] == "anthropic" and batch["label"].startswith("batch-ingest")
    assert batch["byok_amount"] is None
    prod_backend = next(row for row in by_key["rows"] if row["key"] == "a1" * 32)
    assert prod_backend["amount"] == "9.75" and prod_backend["byok_amount"] == "17.00"
    research = next(row for row in by_key["rows"] if row["key"] == "b2" * 32)
    assert research["amount"] == "3.50" and research["byok_amount"] == "0.00"

    filtered = api.get(
        f"{ALL_BASE}/months/2026-08/usage", params={"by": "api_key", "provider": "openrouter"}
    ).json()
    assert filtered["cost_total"] == "14.50"
    assert {row["provider"] for row in filtered["rows"]} == {"openrouter"}

    csv_body = api.get(
        f"{ALL_BASE}/months/2026-08/usage", params={"by": "provider", "format": "csv"}
    ).text
    assert csv_body.splitlines()[0].startswith("key,label,provider,amount,share,")
    assert csv_body.splitlines()[0].endswith(",web_search_requests,byok_amount")

    series = api.get(f"{ALL_BASE}/months/2026-08/series", params={"by": "provider"}).json()
    assert series["month_total"] == "79.12"
    assert {(s["key"], s["provider"]) for s in series["series"]} == {
        ("anthropic", "anthropic"),
        ("openrouter", "openrouter"),
    }

    runs = api.get(f"{ALL_BASE}/runs").json()["runs"]
    assert {run["provider"] for run in runs} == {"anthropic", "openrouter"}

    keys = api.get(f"{ALL_BASE}/inventory/api-keys").json()["items"]
    assert {key["provider"] for key in keys} == {"anthropic", "openrouter"}
    workspaces = api.get(f"{ALL_BASE}/inventory/workspaces").json()["items"]
    assert {w["provider"] for w in workspaces} == {"anthropic", "openrouter"}
    production = next(w for w in workspaces if w["provider"] == "openrouter")
    assert production["api_keys"] >= 1
    one_key = api.get(f"{ALL_BASE}/inventory/api-keys/apikey_redacted_2").json()
    assert one_key["provider"] == "anthropic"

    assert api.get(f"{ALL_BASE}/months/2026-08/anomalies").json()["anomalies"] == []
    assert api.get(f"{ALL_BASE}/months/2026-08/projection").json()["projections"] == []


def test_allocation_coverage_is_complete_and_filter_aware(
    api: TestClient, db_session: Session, both_synced: None
) -> None:
    db_session.execute(
        delete(SpendAllocatedLine).where(SpendAllocatedLine.provider == "openrouter")
    )
    db_session.commit()

    usage = api.get(f"{ALL_BASE}/months/2026-08/usage", params={"by": "workspace"}).json()
    assert usage["allocated"] is False
    assert all(row["amount"] is None for row in usage["rows"])
    series = api.get(f"{ALL_BASE}/months/2026-08/series", params={"by": "workspace"}).json()
    assert series["source"] == "cost"
    assert series["month_total"] == "79.12"
    assert api.get(f"{ALL_BASE}/months/2026-08/summary").json()["allocation"] is None

    anthropic = api.get(
        f"{ALL_BASE}/months/2026-08/usage",
        params={"by": "workspace", "provider": "anthropic"},
    ).json()
    assert anthropic["allocated"] is True
    empty = api.get(
        f"{ALL_BASE}/months/2026-08/usage",
        params={"by": "workspace", "provider": "anthropic", "model": "does-not-exist"},
    ).json()
    assert empty["allocated"] is True
    assert empty["rows"] == [] and empty["cost_total"] == "0.00"


def test_newer_failed_allocation_hides_stale_rows(
    api: TestClient, db_session: Session, both_synced: None
) -> None:
    db_session.add(
        ProviderSyncRun(
            organization_id=ORG_ID,
            provider="openrouter",
            provider_account_id=account_of(db_session, ORG_ID, "openrouter"),
            endpoint="allocation",
            window_start=AUGUST.start,
            window_end=AUGUST.end,
            status="failed",
            error="residue exceeds storage precision",
        )
    )
    db_session.commit()

    assert db_session.scalar(
        select(func.count())
        .select_from(SpendAllocatedLine)
        .where(SpendAllocatedLine.provider == "openrouter")
    )
    assert api.get(f"{ALL_BASE}/months/2026-08/usage").json()["allocated"] is False
    assert api.get(f"{ALL_BASE}/months/2026-08/series").json()["source"] == "cost"
    assert api.get(f"{OPENROUTER_BASE}/months/2026-08/summary").json()["allocation"] is None


def test_exact_one_cent_tolerance_reaches_summary_and_api(
    api: TestClient, db_session: Session, both_synced: None
) -> None:
    line = db_session.scalar(
        select(SpendCostLine)
        .where(SpendCostLine.provider == "openrouter")
        .order_by(SpendCostLine.id)
        .limit(1)
    )
    assert line is not None
    original = Decimal(line.amount)
    line.amount = original + Decimal("0.01")
    db_session.commit()

    summary = api.get(f"{OPENROUTER_BASE}/months/2026-08/summary").json()
    reconcile = api.get(
        f"{OPENROUTER_BASE}/months/2026-08/reconcile", params={"reported": "14.50"}
    ).json()
    assert summary["provider_matches"] is True
    assert reconcile["provider_check"]["ok"] is True
    assert reconcile["matches"] is True

    line.amount = original + Decimal("0.01000001")
    db_session.commit()
    summary = api.get(f"{OPENROUTER_BASE}/months/2026-08/summary").json()
    reconcile = api.get(
        f"{OPENROUTER_BASE}/months/2026-08/reconcile", params={"reported": "14.50"}
    ).json()
    assert summary["provider_matches"] is False
    assert reconcile["provider_check"]["ok"] is False
    assert reconcile["matches"] is False
    assert reconcile["provider_check"]["delta"] == "0.01"


def test_all_scope_unions_budgets(api: TestClient, both_synced: None) -> None:
    api.put(f"{BASE}/budgets/org/__org__", json={"amount": "100"})
    api.put(f"{OPENROUTER_BASE}/budgets/org/__org__", json={"amount": "50"})

    listed = api.get(f"{ALL_BASE}/budgets").json()["budgets"]
    assert [(b["provider"], b["amount"]) for b in listed] == [
        ("anthropic", "100.00"),
        ("openrouter", "50.00"),
    ]
    statuses = api.get(f"{ALL_BASE}/months/2026-08/budgets").json()["statuses"]
    assert {(s["budget"]["provider"], s["spent"]) for s in statuses} == {
        ("anthropic", "64.62"),
        ("openrouter", "14.50"),
    }


def test_inventory_search_ranks_current_resources_inside_the_scope(
    api: TestClient, db_session: Session, both_synced: None
) -> None:
    run_id = db_session.scalar(
        select(ProviderSyncRun.id).where(ProviderSyncRun.organization_id == ORG_ID)
    )
    assert run_id is not None
    anthropic = account_of(db_session, ORG_ID, "anthropic")
    second = create_account(db_session, ORG_ID, "anthropic", label="Search console").id
    openrouter = account_of(db_session, ORG_ID, "openrouter")
    other = create_org(db_session, "search-other", "Search other")
    other_account = account_of(db_session, other.id, "anthropic")
    other_run = ProviderSyncRun(
        organization_id=other.id,
        provider="anthropic",
        provider_account_id=other_account,
        endpoint="api_keys",
        window_start=datetime(2026, 8, 1, tzinfo=UTC),
        window_end=datetime(2026, 8, 31, tzinfo=UTC),
        status="succeeded",
    )
    db_session.add(other_run)
    db_session.flush()

    def key(org_id: int, account: int, external_id: str, name: str, **extra: object) -> None:
        db_session.add(
            ProviderApiKey(
                organization_id=org_id,
                provider="anthropic",
                provider_account_id=account,
                sync_run_id=run_id if org_id == ORG_ID else other_run.id,
                external_id=external_id,
                name=name,
                status="active",
                **extra,
            )
        )

    key(ORG_ID, anthropic, "zephyr-exact", "Zephyrkey")
    key(ORG_ID, anthropic, "zephyr-prefix", "Zephyrkey extra")
    key(ORG_ID, anthropic, "zephyr-mid", "team zephyrkey")
    key(
        ORG_ID,
        anthropic,
        "zephyr-gone",
        "Zephyrkey gone",
        missing_since=datetime(2026, 8, 2, tzinfo=UTC),
    )
    key(ORG_ID, anthropic, "pct_key", "100%_off", partial_key_hint="sk-ant-...%_")
    key(ORG_ID, anthropic, "shared-key", "Alpha console")
    key(ORG_ID, second, "shared-key", "Beta console")
    key(other.id, other_account, "zephyr-exact", "Zephyrkey")
    db_session.add_all(
        [
            ProviderUser(
                organization_id=ORG_ID,
                provider="anthropic",
                provider_account_id=anthropic,
                sync_run_id=run_id,
                external_id="user_zephyr",
                email="Zephyr.Person@example.com",
                role="admin",
                kind="user",
            ),
            ProviderUser(
                organization_id=ORG_ID,
                provider="openrouter",
                provider_account_id=openrouter,
                sync_run_id=run_id,
                external_id="user_zephyr",
                email="zephyr.person@example.com",
                role="member",
                kind="user",
            ),
            ProviderUser(
                organization_id=ORG_ID,
                provider="anthropic",
                provider_account_id=anthropic,
                sync_run_id=run_id,
                external_id="svc_zephyr",
                email="zephyr-bot",
                role="service",
                kind="service_account",
            ),
            ProviderWorkspace(
                organization_id=ORG_ID,
                provider="anthropic",
                provider_account_id=anthropic,
                sync_run_id=run_id,
                external_id="ws_zephyr",
                name="Zephyrkey lab",
            ),
        ]
    )
    db_session.commit()

    ranked = api.get(f"{BASE}/inventory/search", params={"q": "zephyrkey", "limit": 3}).json()[
        "items"
    ]
    assert [item["id"] for item in ranked if item["kind"] == "api_key"] == [
        "zephyr-exact",
        "zephyr-prefix",
        "zephyr-mid",
    ]
    assert [item["id"] for item in ranked if item["kind"] == "workspace"] == ["ws_zephyr"]
    assert "zephyr-gone" not in {item["id"] for item in ranked}

    limited = api.get(f"{BASE}/inventory/search", params={"q": "Zephyrkey", "limit": 1}).json()
    limited_keys = [item["id"] for item in limited["items"] if item["kind"] == "api_key"]
    assert limited_keys == ["zephyr-exact"]

    literal = api.get(f"{BASE}/inventory/search", params={"q": "100%_"}).json()["items"]
    assert [item["id"] for item in literal] == ["pct_key"]
    assert literal[0]["hint"] == "sk-ant-...%_"

    people = api.get(
        f"{ALL_BASE}/inventory/search", params={"q": "zephyr.person@example.com"}
    ).json()["items"]
    assert len(people) == 1
    assert people[0]["kind"] == "person"
    assert people[0]["id"] == "zephyr.person@example.com"
    assert people[0]["providers"] == ["anthropic", "openrouter"]
    assert people[0]["provider_account_id"] is None
    one_provider = api.get(f"{BASE}/inventory/search", params={"q": "zephyr.person"}).json()[
        "items"
    ]
    assert one_provider[0]["providers"] == ["anthropic"]
    assert one_provider[0]["provider_account_id"] == anthropic

    services = api.get(f"{BASE}/inventory/search", params={"q": "zephyr-bot"}).json()["items"]
    assert [(item["kind"], item["id"]) for item in services] == [("service", "svc_zephyr")]

    shared = api.get(f"{ALL_BASE}/inventory/search", params={"q": "shared-key"}).json()["items"]
    assert {(item["provider_account_id"], item["label"]) for item in shared} == {
        (anthropic, "Alpha console"),
        (second, "Beta console"),
    }
    chosen = api.get(f"{BASE}/inventory/api-keys/shared-key", params={"account": second}).json()
    assert chosen["name"] == "Beta console"
    lookup = api.get(
        "/api/v1/orgs/default/entities/key/shared-key",
        params={"scope": "anthropic", "account": second},
    ).json()
    assert lookup == {"provider": "anthropic", "provider_account_id": second}

    assert api.get(f"{BASE}/inventory/search", params={"q": "a"}).status_code == 422
    assert api.get(f"{BASE}/inventory/search", params={"q": "  a"}).status_code == 422
    assert api.get(f"{BASE}/inventory/search", params={"q": "ze", "limit": 0}).status_code == 422
    assert api.get(f"{BASE}/inventory/search", params={"q": "ze", "limit": 9}).status_code == 422
    assert (
        api.get(
            f"/api/v1/orgs/{other.slug}/providers/anthropic/inventory/search",
            params={"q": "zephyrkey"},
        ).status_code
        == 404
    )
    assert "zephyr-exact" not in {
        item["id"]
        for item in api.get(f"{BASE}/inventory/search", params={"q": "zephyrkey"}).json()["items"]
        if item["provider_account_id"] == other_account
    }


def test_all_scope_refuses_provider_specific_routes(api: TestClient, both_synced: None) -> None:
    """Control totals, connections and budget writes belong to one provider."""
    for method, path, json in (
        ("GET", "/months/2026-08/reconcile", None),
        ("GET", "/connection", None),
        ("PUT", "/connection", {"admin_key": "x"}),
        ("DELETE", "/connection", None),
        ("PUT", "/budgets/workspace/wrkspc_a", {"amount": "1"}),
        ("DELETE", "/budgets/workspace/wrkspc_a", None),
    ):
        response = api.request(method, f"{ALL_BASE}{path}", json=json)
        assert response.status_code == 400, (method, path, response.text)
        assert "choose a provider" in response.json()["detail"]


QUERY_CEILINGS = {"usage": 33, "movers": 52, "reconcile": 24}


@pytest.mark.parametrize("read", sorted(QUERY_CEILINGS))
def test_heavy_reads_stay_under_a_statement_ceiling(
    api: TestClient, both_synced: None, read: str
) -> None:
    """The heavy reads load the inventory a bounded number of times, whatever the data."""
    with counted_statements() as statements:
        base = BASE if read == "reconcile" else ALL_BASE
        response = api.get(f"{base}/months/2026-08/{read}")
    assert response.status_code == 200
    assert len(statements) <= QUERY_CEILINGS[read], f"{len(statements)} statements"
    assert sum("FROM provider_api_keys" in s for s in statements) <= 1
