from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura import credentials, secrets
from costura.api.deps import (
    get_session,
)
from costura.config import get_settings
from costura.models import (
    Organization,
    SchedulerRun,
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
    from costura.spend.projection import run_projection
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


def test_setup_poll_requeues_an_expired_lease_and_fails_spent_attempts(
    api: TestClient,
    db_session: Session,
    org_id: int,
) -> None:
    past = datetime.now(UTC) - timedelta(minutes=5)
    waiting = SchedulerRun(
        organization_id=org_id,
        provider="anthropic",
        trigger="api",
        status="queued",
        started_at=past,
        steps=[],
    )
    expired = SchedulerRun(
        organization_id=org_id,
        provider="openrouter",
        trigger="api",
        status="running",
        attempt_count=1,
        max_attempts=3,
        lease_owner="dead",
        lease_expires_at=past,
        steps=[],
    )
    spent = SchedulerRun(
        organization_id=org_id,
        provider="openai",
        trigger="api",
        status="running",
        attempt_count=3,
        max_attempts=3,
        lease_owner="dead",
        lease_expires_at=past,
        steps=[],
    )
    db_session.add_all([waiting, expired, spent])
    db_session.commit()

    body = api.get(SETUP).json()

    by_provider = {run["provider"]: run for run in body["runs"]}
    assert by_provider["anthropic"]["status"] == "queued"
    assert by_provider["openrouter"]["status"] == "queued"
    assert by_provider["openai"]["status"] == "failed"
    assert (
        by_provider["openai"]["error"]
        == "sync stopped after the worker lease expired too many times"
    )
    db_session.refresh(expired)
    assert expired.lease_owner is None and expired.attempt_count == 1


def test_setup_state_connect_syncing_ready(
    api: TestClient,
    db_session: Session,
    anthropic_client: AnthropicAdminClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "anthropic_admin_key", None)

    body = api.get(SETUP).json()
    assert body["state"] == "connect"
    assert [p["provider"] for p in body["providers"]] == [
        "anthropic",
        "claude_ai",
        "codex",
        "openrouter",
        "openai",
        "cursor",
        "copilot",
    ]
    assert all(p["connected"] is False for p in body["providers"])
    assert body["runs"] == [] and body["first_month"] is None
    assert body["dismissed_at"] is None and body["writes_enabled"] is True

    # Connected (environment key) with a failed first run and no cost lines yet: syncing, and
    # the run's steps travel with the state so the browser can show what failed.
    monkeypatch.setattr(get_settings(), "anthropic_admin_key", SecretStr("sk-ant-admin01-env9"))
    failed = SchedulerRun(
        organization_id=ORG_ID,
        provider="anthropic",
        trigger="connect",
        status="failed",
        steps=[
            {
                "step": "inventory",
                "month": None,
                "status": "ok",
                "attempts": 1,
                "detail": None,
                "duration_seconds": 0.2,
            },
            {
                "step": "cost",
                "month": "2026-09",
                "status": "failed",
                "attempts": 3,
                "detail": "RuntimeError: boom",
                "duration_seconds": 1.5,
            },
        ],
    )
    db_session.add(failed)
    db_session.commit()
    body = api.get(SETUP).json()
    assert body["state"] == "syncing" and body["first_month"] is None
    [run] = body["runs"]
    assert (run["id"], run["provider"], run["trigger"], run["status"]) == (
        failed.id,
        "anthropic",
        "connect",
        "failed",
    )
    assert run["started_at"] is not None and run["finished_at"] is None
    assert [(s["step"], s["status"]) for s in run["steps"]] == [
        ("inventory", "ok"),
        ("cost", "failed"),
    ]
    assert run["steps"][1]["detail"] == "RuntimeError: boom"

    run_cost_sync(
        db_session,
        target(db_session, ORG_ID, "anthropic"),
        anthropic_client,
        FIXTURE_START,
        FIXTURE_END,
    )
    body = api.get(SETUP).json()
    assert body["state"] == "ready" and body["first_month"] == "2026-08"


def test_setup_ready_under_every_provider_and_latest_run_per_provider(
    api: TestClient, db_session: Session, both_synced: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "anthropic_admin_key", SecretStr("sk-ant-admin01-env9"))
    for provider, status in (
        ("anthropic", "failed"),
        ("openrouter", "succeeded"),
        ("anthropic", "succeeded"),
    ):
        db_session.add(
            SchedulerRun(organization_id=ORG_ID, provider=provider, trigger="api", status=status)
        )
    db_session.commit()

    body = api.get(SETUP).json()

    assert body["state"] == "ready" and body["first_month"] == "2026-08"
    assert [(r["provider"], r["status"]) for r in body["runs"]] == [
        ("anthropic", "succeeded"),
        ("openrouter", "succeeded"),
    ]


def test_setup_dismiss_persists_and_is_idempotent(
    api: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "anthropic_admin_key", None)
    assert api.get(SETUP).json()["dismissed_at"] is None

    first = api.post(f"{SETUP}/dismiss")
    assert first.status_code == 200
    dismissed_at = first.json()["dismissed_at"]
    assert dismissed_at is not None and first.json()["state"] == "connect"

    second = api.post(f"{SETUP}/dismiss").json()
    assert second["dismissed_at"] == dismissed_at
    assert api.get(SETUP).json()["dismissed_at"] == dismissed_at
    db_session.expire_all()
    org = db_session.scalar(select(Organization).where(Organization.slug == "default"))
    assert org.onboarding_dismissed_at is not None

    forwarded = api.post(f"{SETUP}/dismiss", headers={"X-Forwarded-For": "10.0.0.7"})
    assert forwarded.status_code == 403
    assert api.get("/api/v1/orgs/ghost/setup").status_code == 404


def test_setup_reset_returns_to_connect_and_spares_other_organizations(
    api: TestClient,
    db_session: Session,
    both_synced: None,
    intelligence: None,
    anthropic_client: AnthropicAdminClient,
    secret_key: None,
    fixture_transport: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "anthropic_admin_key", None)
    # Everything the organization can accumulate: a budget, an assigned contact, then a stored
    # key whose first sync raises the budget alerts, anomalies and projections from the seed,
    # a dismissed card.
    api.put(f"{BASE}/budgets/org/__org__", json={"amount": "100"})
    api.put(f"{BASE}/owners/api_key/apikey_x", json={"email": "ops@example.com"})
    api.put(f"{BASE}/connection", json={"admin_key": "sk-ant-admin01-good-4321"})
    drain_queued_syncs()
    api.post(f"{SETUP}/dismiss")
    # The first sync's `project` step clears August (a closed month); store one again.
    run_projection(db_session, ORG_ID, "anthropic", AUGUST, today=date(2026, 8, 21))
    db_session.commit()
    other = create_org(db_session, "acme", "Acme", owner=_owner(db_session))
    run_cost_sync(
        db_session,
        target(db_session, other.id, "anthropic"),
        anthropic_client,
        FIXTURE_START,
        FIXTURE_END,
    )
    credentials.set_credential(
        db_session, get_settings(), other.id, "anthropic", "sk-ant-admin01-acme-0001"
    )
    before = _org_rows(db_session, ORG_ID)
    assert any(count > 0 for count in before.values()), before
    other_before = _org_rows(db_session, other.id)
    assert other_before["spend_cost_lines"] > 0 and other_before["provider_credentials"] == 1
    assert api.get(SETUP).json()["state"] == "ready"

    response = api.post(f"{SETUP}/reset")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "connect" and body["first_month"] is None
    assert body["runs"] == [] and body["dismissed_at"] is None
    assert all(p["connected"] is False and p["last_run"] is None for p in body["providers"])
    assert _org_rows(db_session, ORG_ID) == dict.fromkeys(before, 0)
    assert _org_rows(db_session, other.id) == other_before
    assert api.get(f"{ALL_BASE}/months").json() == {"months": []}
    assert api.get("/api/v1/orgs/acme/providers/anthropic/months").json() == {"months": ["2026-08"]}
    assert [o["slug"] for o in api.get("/api/v1/orgs").json()] == ["acme", "default"]

    # Idempotent: a second reset on an empty organization answers the same state.
    again = api.post(f"{SETUP}/reset")
    assert again.status_code == 200 and again.json()["state"] == "connect"

    # A key from the environment is not a stored row, so the state is `syncing` after a reset.
    monkeypatch.setattr(get_settings(), "anthropic_admin_key", SecretStr("sk-ant-admin01-env9"))
    with_env = api.post(f"{SETUP}/reset").json()
    assert with_env["state"] == "syncing"
    anthropic = next(p for p in with_env["providers"] if p["provider"] == "anthropic")
    assert anthropic["connected"] is True and anthropic["source"] == "environment"

    forwarded = api.post(f"{SETUP}/reset", headers={"X-Forwarded-For": "10.0.0.7"})
    assert forwarded.status_code == 403
    assert api.post("/api/v1/orgs/ghost/setup/reset").status_code == 404


def _accounts(session: Session, count: int) -> None:
    from costura.accounts import create_account
    from costura.providers.registry import provider_names

    for name in provider_names():
        for _ in range(count):
            create_account(session, ORG_ID, name)
    session.commit()


@pytest.mark.parametrize(
    "path", [SETUP, "/api/v1/orgs/default/providers"], ids=["setup", "providers"]
)
def test_setup_reads_do_not_grow_with_accounts(
    api: TestClient, db_session: Session, path: str
) -> None:
    """The setup and provider pages poll during a sync; their statement count is the same
    for one account per provider as for three."""
    _accounts(db_session, 1)
    with counted_statements() as one:
        assert api.get(path).status_code == 200
    _accounts(db_session, 2)
    with counted_statements() as three:
        assert api.get(path).status_code == 200
    assert len(three) == len(one)
    assert len(one) <= SETUP_CEILINGS[path]


SETUP_CEILINGS = {SETUP: 15, "/api/v1/orgs/default/providers": 9}
