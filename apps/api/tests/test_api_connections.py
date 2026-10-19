from collections.abc import Iterator
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura import scheduler, scheduler_lock, secrets
from costura.api.deps import (
    get_session,
)
from costura.config import get_settings
from costura.db import SessionLocal
from costura.models import (
    ProviderAccount,
    ProviderCredential,
    SchedulerRun,
    SpendCostLine,
    User,
)
from costura.orgs import RESET_TABLES, create_org
from costura.providers.anthropic.client import AnthropicAdminClient
from costura.providers.anthropic.inventory import run_inventory_sync
from costura.providers.anthropic.sync import run_cost_sync, run_usage_sync
from costura.providers.openai import inventory as openai_inventory
from costura.providers.openai import sync as openai_sync
from costura.providers.openai.client import OpenAIAdminClient
from costura.providers.openrouter import inventory as openrouter_inventory
from costura.providers.openrouter import sync as openrouter_sync
from costura.providers.openrouter.client import OpenRouterManagementClient
from costura.spend.allocate import run_allocation
from costura.spend.projection import run_projection
from tests.conftest import ORG_ID, OWNER_EMAIL, anthropic_fixture_handler, request_session, target
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


def test_connection_read_write_delete(
    api: TestClient,
    db_session: Session,
    secret_key: None,
    fixture_transport: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "anthropic_admin_key", None)

    body = api.get(f"{BASE}/connection").json()
    assert body["connected"] is False
    assert body["source"] is None and body["key_hint"] is None
    assert body["writes_enabled"] is True
    assert body["schedule"]["status"] is None and body["schedule"]["next_run_at"] is None

    rejected = api.put(f"{BASE}/connection", json={"admin_key": "sk-ant-admin01-bad"})
    assert rejected.status_code == 422
    assert "rejected the key (HTTP 401)" in rejected.json()["detail"]
    assert api.get(f"{BASE}/connection").json()["connected"] is False

    accepted = api.put(f"{BASE}/connection", json={"admin_key": "sk-ant-admin01-good-4321"})
    assert accepted.status_code == 200
    body = accepted.json()
    assert body["connected"] is True and body["source"] == "stored"
    assert body["key_hint"] == "4321"
    assert body["last_validated_at"] is not None and body["last_error"] is None
    assert body["schedule"]["next_run_at"] is not None
    assert body["schedule"]["schedule_at"] == get_settings().costura_schedule_at
    # The request only enqueues. A later read still shows queued until the worker runs.
    assert body["first_sync_run_id"] == body["schedule"]["last_run_id"]
    assert body["schedule"]["status"] == "queued" and body["schedule"]["trigger"] == "connect"
    assert "sk-ant-admin01-good" not in accepted.text
    schedule = api.get(f"{BASE}/connection").json()["schedule"]
    assert schedule["last_run_id"] == body["first_sync_run_id"]
    assert schedule["status"] == "queued" and schedule["failed_steps"] == []

    # Environment fallback shows as such once the stored key is gone.
    removed = api.delete(f"{BASE}/connection")
    assert removed.status_code == 200 and removed.json()["connected"] is False
    monkeypatch.setattr(get_settings(), "anthropic_admin_key", SecretStr("sk-ant-admin01-env9"))
    body = api.get(f"{BASE}/connection").json()
    assert body["connected"] is True and body["source"] == "environment"
    assert body["key_hint"] == "env9"


def test_connection_rejects_an_oversized_or_unprintable_key_before_any_request(
    api: TestClient,
    secret_key: None,
    fixture_transport: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from costura import credentials

    def no_request(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the key reached the provider")

    monkeypatch.setattr(credentials, "set_credential", no_request)
    for key in ["sk-ant-" + "a" * 600, "sk-ant-admin01\r\nX-Injected: 1", "sk ant"]:
        response = api.put(f"{BASE}/connection", json={"admin_key": key})
        assert response.status_code == 422, key
        assert key not in response.text


def test_connection_trims_a_pasted_key(
    api: TestClient,
    secret_key: None,
    fixture_transport: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "anthropic_admin_key", None)
    accepted = api.put(f"{BASE}/connection", json={"admin_key": "  sk-ant-admin01-good-4321\n"})
    assert accepted.status_code == 200
    assert accepted.json()["key_hint"] == "4321"


def test_connection_requires_secret_key_to_store(
    api: TestClient, fixture_transport: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "costura_secret_key", None)

    assert api.get(f"{BASE}/connection").json()["secret_key_configured"] is False

    response = api.put(f"{BASE}/connection", json={"admin_key": "sk-ant-admin01-good"})

    assert response.status_code == 503
    assert "COSTURA_SECRET_KEY" in response.json()["detail"]


@pytest.mark.parametrize(
    ("key_suffix", "expected_status"),
    [("rate", 503), ("down", 503), ("timeout", 503), ("protocol", 502)],
)
def test_connection_classifies_upstream_failure_without_storing_or_enqueuing(
    api: TestClient,
    db_session: Session,
    secret_key: None,
    fixture_transport: None,
    key_suffix: str,
    expected_status: int,
) -> None:
    response = api.put(
        f"{BASE}/connection",
        json={"admin_key": f"sk-ant-admin01-{key_suffix}"},
    )

    assert response.status_code == expected_status
    assert db_session.scalar(select(func.count()).select_from(ProviderCredential)) == 0
    assert db_session.scalar(select(func.count()).select_from(SchedulerRun)) == 0


def test_provider_accounts_list_add_rename_replace_disconnect_remove(
    api: TestClient,
    db_session: Session,
    secret_key: None,
    fixture_transport: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Several accounts of one provider: the first key connects through the
    connection route and takes the label the provider reports; a second key adds an account;
    the same key cannot connect twice; labels are unique; the connection route refuses to
    speak for two accounts; removing an account drops its rows and its scheduler runs."""
    monkeypatch.setattr(get_settings(), "anthropic_admin_key", None)
    accounts_url = f"{BASE}/accounts"
    assert api.get(accounts_url).json() == {"accounts": []}

    first = api.put(f"{BASE}/connection", json={"admin_key": "sk-ant-admin01-good-4321"}).json()
    [main] = first["accounts"]
    assert main["label"] == "Example Labs" and main["external_id"] == "org_redacted_main"
    assert main["connected"] is True and main["key_hint"] == "4321"
    assert main["schedule"]["status"] == "queued"

    duplicate = api.post(accounts_url, json={"admin_key": "sk-ant-admin01-good-4321"})
    assert duplicate.status_code == 422 and "already connects" in duplicate.json()["detail"]
    taken = api.post(
        accounts_url, json={"admin_key": "sk-ant-admin01-other-second", "label": "Example Labs"}
    )
    assert taken.status_code == 422 and "already" in taken.json()["detail"]

    added = api.post(accounts_url, json={"admin_key": "sk-ant-admin01-other-second"})
    assert added.status_code == 201
    second = added.json()
    assert second["label"] == "Example Research" and second["key_hint"] == "cond"
    assert second["first_sync_run_id"] is not None
    drain_queued_syncs()
    listed = api.get(accounts_url).json()["accounts"]
    assert [a["label"] for a in listed] == ["Example Labs", "Example Research"]
    providers = api.get("/api/v1/orgs/default/providers").json()
    anthropic = next(p for p in providers if p["provider"] == "anthropic")
    assert [a["label"] for a in anthropic["accounts"]] == ["Example Labs", "Example Research"]

    # The provider-level routes answer 409 while the provider has two accounts.
    assert api.put(f"{BASE}/connection", json={"admin_key": "sk-ant-admin01-x"}).status_code == 409
    assert api.delete(f"{BASE}/connection").status_code == 409

    renamed = api.patch(f"{accounts_url}/{second['id']}", json={"label": "Research team"})
    assert renamed.status_code == 200 and renamed.json()["label"] == "Research team"
    assert api.patch(f"{accounts_url}/{second['id']}", json={"label": " "}).status_code == 422
    assert api.patch(f"{accounts_url}/999999", json={"label": "x"}).status_code == 404

    replaced = api.put(
        f"{accounts_url}/{second['id']}/key", json={"admin_key": "sk-ant-admin01-new-second"}
    )
    assert replaced.status_code == 200 and replaced.json()["key_hint"] == "cond"
    rejected = api.put(f"{accounts_url}/{second['id']}/key", json={"admin_key": "sk-ant-bad"})
    assert rejected.status_code == 422
    assert "HTTP 401" in api.get(accounts_url).json()["accounts"][1]["last_error"]

    disconnected = api.delete(f"{accounts_url}/{second['id']}/key")
    assert disconnected.status_code == 200 and disconnected.json()["connected"] is False
    assert len(api.get(accounts_url).json()["accounts"]) == 2

    # The rows synced under the account go with it.
    second_rows = db_session.scalar(
        select(func.count()).where(SpendCostLine.provider_account_id == second["id"])
    )
    assert second_rows is not None and second_rows > 0
    assert api.delete(f"{accounts_url}/{second['id']}").status_code == 204
    assert [a["label"] for a in api.get(accounts_url).json()["accounts"]] == ["Example Labs"]
    assert (
        db_session.scalar(
            select(func.count()).where(SpendCostLine.provider_account_id == second["id"])
        )
        == 0
    )
    assert api.delete(f"{accounts_url}/{second['id']}").status_code == 404

    # Rows synced under the remaining account name it.
    usage = api.get(f"{BASE}/months/2026-08/usage", params={"by": "provider_account"}).json()
    assert [r["label"] for r in usage["rows"]] == ["Example Labs"]
    assert usage["rows"][0]["provider_account_id"] == main["id"]
    keyed = api.get(f"{BASE}/months/2026-08/usage", params={"by": "api_key"}).json()
    assert all(r["provider_account_label"] == "Example Labs" for r in keyed["rows"])
    filtered = api.get(
        f"{BASE}/months/2026-08/usage",
        params={"by": "api_key", "provider_account": main["id"]},
    ).json()
    assert len(filtered["rows"]) == len(keyed["rows"])
    reconciled = api.get(f"{BASE}/months/2026-08/reconcile", params={"account": main["id"]}).json()
    assert reconciled["account_label"] == "Example Labs"
    assert [a["label"] for a in reconciled["accounts"]] == ["Example Labs"]
    assert api.get(f"{BASE}/months/2026-08/reconcile", params={"account": 999}).status_code == 404


def test_connect_enqueues_the_first_sync_once(
    api: TestClient,
    db_session: Session,
    secret_key: None,
    fixture_transport: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Storing a key queues one sync and does not run it; a later store after success does not."""
    monkeypatch.setattr(get_settings(), "anthropic_admin_key", None)

    first = api.put(f"{BASE}/connection", json={"admin_key": "sk-ant-admin01-good-4321"}).json()

    assert first["first_sync_run_id"] is not None
    db_session.expire_all()
    runs = db_session.scalars(select(SchedulerRun).order_by(SchedulerRun.id)).all()
    assert [(r.id, r.trigger, r.status) for r in runs] == [
        (first["first_sync_run_id"], "connect", "queued")
    ]
    assert runs[0].steps == []
    assert api.get(f"{BASE}/months").json() == {"months": []}

    drain_queued_syncs()
    db_session.expire_all()
    runs = db_session.scalars(select(SchedulerRun).order_by(SchedulerRun.id)).all()
    assert [(r.id, r.trigger, r.status) for r in runs] == [
        (first["first_sync_run_id"], "connect", "succeeded")
    ]
    assert {s["step"] for s in runs[0].steps} >= {"inventory", "cost", "total", "usage"}
    assert api.get(f"{BASE}/months").json() == {"months": ["2026-08"]}

    second = api.put(f"{BASE}/connection", json={"admin_key": "sk-ant-admin01-good-9999"}).json()

    assert second["first_sync_run_id"] is None and second["key_hint"] == "9999"
    assert db_session.scalar(select(func.count()).select_from(SchedulerRun)) == 1


def test_sync_now_answers_202_and_leaves_the_run_queued(
    api: TestClient, db_session: Session, secret_key: None, fixture_transport: None
) -> None:
    api.put(f"{BASE}/connection", json={"admin_key": "sk-ant-admin01-good-4321"})
    drain_queued_syncs()

    response = api.post(f"{BASE}/sync")

    assert response.status_code == 202
    [body] = response.json()["results"]
    assert body == {
        "provider": "anthropic",
        "provider_account_id": body["provider_account_id"],
        "run_id": body["run_id"],
        "status": "queued",
        "error": None,
        "steps": [],
    }
    row = db_session.get(SchedulerRun, body["run_id"])
    db_session.refresh(row)
    assert row.status == "queued" and row.steps == [] and row.trigger == "api"
    drain_queued_syncs()
    db_session.refresh(row)
    assert row.status == "succeeded" and row.trigger == "api"
    assert [s["step"] for s in row.steps].count("cost") == 2
    assert {s["step"] for s in row.steps} == {
        "cost",
        "total",
        "usage",
        "inventory",
        "allocate",
        "detect",
        "project",
        "budgets",
        "person_budgets",
    }
    schedule = api.get(f"{BASE}/connection").json()["schedule"]
    assert schedule["last_run_id"] == body["run_id"]
    assert schedule["status"] == "succeeded" and schedule["trigger"] == "api"
    assert schedule["failed_steps"] == []


def test_sync_now_without_credential_is_skipped(
    api: TestClient, db_session: Session, secret_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "anthropic_admin_key", None)

    response = api.post(f"{BASE}/sync")

    assert response.status_code == 202
    [body] = response.json()["results"]
    assert body["status"] == "queued" and body["steps"] == []
    row = db_session.get(SchedulerRun, body["run_id"])
    db_session.refresh(row)
    assert row.status == "queued"
    drain_queued_syncs()
    db_session.refresh(row)
    assert row.status == "skipped"
    assert "web settings page" in (row.error or "")
    assert row.steps == []


@pytest.mark.parametrize("status", ["queued", "running"])
def test_sync_and_reset_answer_409_while_an_organization_run_is_active(
    api: TestClient, db_session: Session, org_id: int, status: str
) -> None:
    run = SchedulerRun(
        organization_id=org_id,
        provider="anthropic",
        trigger="api",
        status=status,
        steps=[],
    )
    db_session.add(run)
    db_session.commit()

    sync_response = api.post(f"{BASE}/sync")
    if status == "running":
        with SessionLocal() as holder:
            assert scheduler_lock.try_organization_lock(holder, org_id)
            try:
                reset_response = api.post(f"{SETUP}/reset")
            finally:
                scheduler_lock.unlock_organization(holder, org_id)
    else:
        reset_response = api.post(f"{SETUP}/reset")

    assert sync_response.status_code == 409
    assert f"sync already {status}" in sync_response.json()["detail"]
    assert reset_response.status_code == 409
    expected = "sync is queued" if status == "queued" else "sync is active"
    assert expected in reset_response.json()["detail"]
    assert db_session.get(SchedulerRun, run.id) is not None


def test_sync_all_scope_runs_every_connected_provider(
    api: TestClient,
    db_session: Session,
    secret_key: None,
    fixture_transport: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "anthropic_admin_key", None)
    assert api.post(f"{ALL_BASE}/sync").status_code == 400

    api.put(f"{BASE}/connection", json={"admin_key": "sk-ant-admin01-good-4321"})
    drain_queued_syncs()
    response = api.post(f"{ALL_BASE}/sync")
    assert response.status_code == 202
    results = response.json()["results"]
    assert [(r["provider"], r["status"]) for r in results] == [("anthropic", "queued")]
    row = db_session.get(SchedulerRun, results[0]["run_id"])
    db_session.refresh(row)
    assert row.status == "queued" and row.trigger == "api"
    drain_queued_syncs()
    db_session.refresh(row)
    assert row.status == "succeeded" and row.trigger == "api"


def test_providers_route_lists_registry_and_connection_state(
    api: TestClient, db_session: Session, synced: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "anthropic_admin_key", SecretStr("sk-ant-admin01-env9"))

    body = api.get("/api/v1/orgs/default/providers").json()

    assert [p["provider"] for p in body] == [
        "anthropic",
        "claude_ai",
        "codex",
        "openrouter",
        "openai",
        "cursor",
        "copilot",
    ]
    anthropic, claude_ai, codex, openrouter, openai, cursor, copilot = body
    assert openai["label"] == "OpenAI" and openai["key_prefix"] == "sk-admin-"
    assert openai["connected"] is False and openai["attribution"] == "key_attributed"
    assert anthropic["label"] == "Anthropic" and anthropic["key_prefix"] == "sk-ant-admin"
    assert anthropic["connected"] is True and anthropic["source"] == "environment"
    assert (anthropic["vendor"], anthropic["surface"]) == ("Anthropic", "Claude Platform")
    assert (claude_ai["vendor"], claude_ai["surface"]) == ("Anthropic", "claude.ai")
    assert (codex["vendor"], codex["surface"]) == ("OpenAI", "Codex")
    assert codex["connected"] is False and codex["attribution"] == "direct"
    assert (cursor["vendor"], cursor["surface"]) == ("Cursor", "Cursor")
    assert (copilot["vendor"], copilot["key_prefix"]) == ("GitHub", "ghp_")
    assert copilot["connected"] is False and copilot["attribution"] == "direct"
    assert anthropic["key_hint"] == "env9"
    assert anthropic["last_run"]["provider"] == "anthropic"
    assert anthropic["attribution"] == "token_share"
    assert openrouter["label"] == "OpenRouter" and openrouter["key_prefix"] == "sk-or-v1-"
    assert openrouter["connected"] is False and openrouter["source"] is None
    assert openrouter["last_run"] is None and openrouter["attribution"] == "direct"
    assert openrouter["console_url"] == "https://openrouter.ai/settings/management-keys"
    assert "sk-ant-admin01-env9" not in str(body)


def test_providers_route_does_not_share_environment_key_with_second_org(
    api: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_org(db_session, "other", "Other", owner=_owner(db_session))
    monkeypatch.setattr(get_settings(), "costura_org", "default")
    monkeypatch.setattr(get_settings(), "anthropic_admin_key", SecretStr("sk-ant-admin01-env9"))

    default = api.get("/api/v1/orgs/default/providers").json()
    other = api.get("/api/v1/orgs/other/providers").json()

    assert default[0]["connected"] is True and default[0]["source"] == "environment"
    assert other[0]["connected"] is False and other[0]["source"] is None


def test_reading_providers_inserts_no_environment_account(
    api: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A page view reports the process key as connected without creating its account; the
    first enqueue creates it, once."""
    monkeypatch.setattr(get_settings(), "costura_org", "default")
    monkeypatch.setattr(get_settings(), "anthropic_admin_key", SecretStr("sk-ant-admin01-env9"))
    assert accounts_of(db_session) == 0
    for _ in range(2):
        body = api.get("/api/v1/orgs/default/providers").json()
        assert body[0]["connected"] is True and body[0]["source"] == "environment"
    assert accounts_of(db_session) == 0
    scheduler.enqueue_runs(db_session, ORG_ID, ["anthropic"], trigger="api")
    db_session.commit()
    assert accounts_of(db_session) == 1


def accounts_of(session: Session) -> int:
    return session.scalar(
        select(func.count())
        .select_from(ProviderAccount)
        .where(ProviderAccount.organization_id == ORG_ID, ProviderAccount.provider == "anthropic")
    )
