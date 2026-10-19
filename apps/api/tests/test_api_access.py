from collections.abc import Iterator
from datetime import date

import httpx
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura import auth, secrets
from costura.api.deps import (
    OWNER_ONLY,
    get_operating_organization,
    get_owned_organization,
    get_session,
    get_writable_organization,
)
from costura.api.guard import require_verified_write
from costura.api.routes import DOMAIN_ROUTERS
from costura.config import get_settings
from costura.models import (
    User,
)
from costura.orgs import RESET_TABLES, get_org
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
from tests.support.orgs import add_member
from tests.support.spend import AUGUST, FIXTURE_END, FIXTURE_START

BASE = "/api/v1/orgs/default/providers/anthropic"

ALL_BASE = "/api/v1/orgs/default/providers/all"

OPENROUTER_BASE = "/api/v1/orgs/default/providers/openrouter"

OPENAI_BASE = "/api/v1/orgs/default/providers/openai"

PERSON = "alice@example.com"

WRITE_ROUTES = {
    ("DELETE", "/orgs/{org}"),
    ("DELETE", "/orgs/{org}/accounts/{account_id}/credit-prices/{price_id}"),
    ("DELETE", "/orgs/{org}/invitations/{invitation_id}"),
    ("DELETE", "/orgs/{org}/members/{user_id}"),
    ("DELETE", "/orgs/{org}/providers/{provider}/accounts/{account_id}"),
    ("DELETE", "/orgs/{org}/providers/{provider}/accounts/{account_id}/invoices/{month}"),
    ("DELETE", "/orgs/{org}/providers/{provider}/accounts/{account_id}/key"),
    ("DELETE", "/orgs/{org}/providers/{provider}/budgets/{scope_kind}/{scope_id}"),
    ("DELETE", "/orgs/{org}/providers/{provider}/connection"),
    ("DELETE", "/orgs/{org}/providers/{provider}/owners/{kind}/{external_id}"),
    ("DELETE", "/orgs/{org}/providers/{provider}/personal-keys/{api_key_id}"),
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
    ("PUT", "/orgs/{org}/anomaly-settings"),
    ("PUT", "/orgs/{org}/providers/{provider}/accounts/{account_id}/invoices/{month}"),
    ("PUT", "/orgs/{org}/providers/{provider}/accounts/{account_id}/key"),
    ("PUT", "/orgs/{org}/providers/{provider}/accounts/{account_id}/logins"),
    ("PUT", "/orgs/{org}/providers/{provider}/budgets/{scope_kind}/{scope_id}"),
    ("PUT", "/orgs/{org}/providers/{provider}/connection"),
    ("PUT", "/orgs/{org}/providers/{provider}/owners/{kind}/{external_id}"),
    ("PUT", "/orgs/{org}/providers/{provider}/personal-keys/{api_key_id}"),
    ("DELETE", "/orgs/{org}/webhook"),
    ("POST", "/orgs/{org}/webhook/test"),
    ("POST", "/orgs/{org}/webhook/deliveries/{delivery_id}/resend"),
    ("PUT", "/orgs/{org}/webhook"),
    ("PUT", "/orgs/{org}/providers/{provider}/signals/snoozes"),
    ("DELETE", "/orgs/{org}/providers/{provider}/signals/snoozes/{kind}/{key_id}"),
    ("PUT", "/orgs/{org}/webhook/digest"),
    ("PUT", "/orgs/{org}/teams/{slug}"),
    ("DELETE", "/orgs/{org}/teams/{slug}"),
    ("PUT", "/orgs/{org}/teams/{slug}/members/{kind}/{provider}/{external_id}"),
    ("DELETE", "/orgs/{org}/teams/{slug}/members/{kind}/{provider}/{external_id}"),
}

OWNER_ROUTES = {
    ("DELETE", "/orgs/{org}"),
    ("DELETE", "/orgs/{org}/invitations/{invitation_id}"),
    ("DELETE", "/orgs/{org}/providers/{provider}/accounts/{account_id}"),
    ("DELETE", "/orgs/{org}/providers/{provider}/accounts/{account_id}/invoices/{month}"),
    ("DELETE", "/orgs/{org}/providers/{provider}/accounts/{account_id}/key"),
    ("DELETE", "/orgs/{org}/providers/{provider}/budgets/{scope_kind}/{scope_id}"),
    ("DELETE", "/orgs/{org}/providers/{provider}/connection"),
    ("PATCH", "/orgs/{org}"),
    ("PATCH", "/orgs/{org}/members/{user_id}"),
    ("PATCH", "/orgs/{org}/providers/{provider}/accounts/{account_id}"),
    ("POST", "/orgs/{org}/invitations"),
    ("POST", "/orgs/{org}/providers/{provider}/accounts"),
    ("POST", "/orgs/{org}/setup/reset"),
    ("PUT", "/orgs/{org}/anomaly-settings"),
    ("PUT", "/orgs/{org}/providers/{provider}/accounts/{account_id}/invoices/{month}"),
    ("PUT", "/orgs/{org}/providers/{provider}/accounts/{account_id}/key"),
    ("PUT", "/orgs/{org}/providers/{provider}/accounts/{account_id}/logins"),
    ("PUT", "/orgs/{org}/providers/{provider}/budgets/{scope_kind}/{scope_id}"),
    ("PUT", "/orgs/{org}/providers/{provider}/connection"),
    ("DELETE", "/orgs/{org}/webhook"),
    ("POST", "/orgs/{org}/webhook/test"),
    ("POST", "/orgs/{org}/webhook/deliveries/{delivery_id}/resend"),
    ("PUT", "/orgs/{org}/webhook"),
    ("PUT", "/orgs/{org}/webhook/digest"),
    ("PUT", "/orgs/{org}/teams/{slug}"),
    ("DELETE", "/orgs/{org}/teams/{slug}"),
    ("PUT", "/orgs/{org}/teams/{slug}/members/{kind}/{provider}/{external_id}"),
    ("DELETE", "/orgs/{org}/teams/{slug}/members/{kind}/{provider}/{external_id}"),
}

OPERATOR_ROUTES = {
    ("DELETE", "/orgs/{org}/accounts/{account_id}/credit-prices/{price_id}"),
    ("DELETE", "/orgs/{org}/providers/{provider}/owners/{kind}/{external_id}"),
    ("DELETE", "/orgs/{org}/providers/{provider}/personal-keys/{api_key_id}"),
    ("PATCH", "/orgs/{org}/providers/{provider}/anomalies/{anomaly_id}"),
    ("POST", "/orgs/{org}/accounts/{account_id}/credit-prices"),
    ("POST", "/orgs/{org}/providers/{provider}/sync"),
    ("POST", "/orgs/{org}/setup/dismiss"),
    ("PUT", "/orgs/{org}/providers/{provider}/owners/{kind}/{external_id}"),
    ("PUT", "/orgs/{org}/providers/{provider}/personal-keys/{api_key_id}"),
    ("PUT", "/orgs/{org}/providers/{provider}/signals/snoozes"),
    ("DELETE", "/orgs/{org}/providers/{provider}/signals/snoozes/{kind}/{key_id}"),
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


def test_read_routes_are_get_and_writes_are_guarded() -> None:
    """Provider sync clients are read-only; under `/orgs/{org}` every write goes through
    `require_verified_write` and the writable-organization dependency (403 on the demo
    organization), and then through exactly one role tier: owner (keys, budgets, reset,
    members and invitations), operator (imports, anomaly triage, owner assignments, personal
    keys, the getting-started card) or personal (the alerts opt-in, the read markers,
    leaving). The sign-in, sign-out, organization creation and
    invitation claim POSTs sit outside the organization scope."""
    routes = [
        route
        for domain_router in DOMAIN_ROUTERS
        for route in domain_router.routes
        if isinstance(route, APIRoute)
    ]
    assert len(routes) == 96
    assert OWNER_ROUTES | OPERATOR_ROUTES | PERSONAL_ROUTES == WRITE_ROUTES
    writes = set()
    for route in routes:
        for method in route.methods:
            if method == "GET":
                continue
            if (method, route.path) in SEMANTIC_POST_ROUTES:
                guards = _dependency_calls(route.dependant)
                assert require_verified_write not in guards
                continue
            if not route.path.startswith("/orgs/{org}"):
                assert (method, route.path) in UNSCOPED_WRITE_ROUTES
                continue
            writes.add((method, route.path))
            guards = _dependency_calls(route.dependant)
            assert require_verified_write in guards, f"{method} {route.path} lacks the write guard"
            assert get_writable_organization in guards, f"{method} {route.path} writes on demo"
            owned = get_owned_organization in guards
            assert owned == ((method, route.path) in OWNER_ROUTES), f"{method} {route.path}"
            operates = get_operating_organization in guards
            assert operates == ((method, route.path) in OPERATOR_ROUTES), f"{method} {route.path}"
    assert writes == WRITE_ROUTES


def test_a_member_cannot_replace_the_key_wipe_the_organization_or_set_budgets(
    db_session: Session, client: TestClient
) -> None:
    from costura.main import app

    signed = auth.sign_in_dev(db_session, "member@example.com")
    add_member(db_session, get_org(db_session, "default"), signed.user, "member")
    db_session.commit()
    member = TestClient(app, headers={"Authorization": f"Bearer {signed.token}"})

    denied = [
        member.put(f"{BASE}/connection", json={"key": "sk-ant-admin-x"}),
        member.delete(f"{BASE}/connection"),
        member.put(f"{BASE}/budgets/org/__org__", json={"amount": "10", "thresholds": [50]}),
        member.delete(f"{BASE}/budgets/org/__org__"),
        member.post("/api/v1/orgs/default/setup/reset"),
    ]
    assert [r.status_code for r in denied] == [403] * 5
    assert {r.json()["detail"] for r in denied} == {OWNER_ONLY}
    # The member still reads the organization and dismisses the onboarding card.
    assert member.get("/api/v1/orgs/default").status_code == 200
    assert member.post("/api/v1/orgs/default/setup/dismiss").status_code == 200


@pytest.mark.parametrize(
    ("method", "path", "json"),
    [
        ("PUT", "/connection", {"admin_key": "x"}),
        ("DELETE", "/connection", None),
        ("POST", "/sync", None),
        ("PATCH", "/anomalies/1", {"status": "acknowledged"}),
        ("PUT", "/budgets/org/__org__", {"amount": "100"}),
        ("DELETE", "/budgets/org/__org__", None),
    ],
)
def test_writes_refused_in_production_or_from_outside_loopback(
    api: TestClient,
    secret_key: None,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    json: dict | None,
) -> None:
    forwarded = api.request(method, BASE + path, json=json, headers={"X-Forwarded-For": "10.0.0.7"})
    assert forwarded.status_code == 403
    assert "authentication" in forwarded.json()["detail"]

    monkeypatch.setattr(get_settings(), "costura_env", "production")
    refused = api.request(method, BASE + path, json=json)
    assert refused.status_code == 403
    # Reads keep working and report that writes are off.
    body = api.get(f"{BASE}/connection").json()
    assert body["writes_enabled"] is False


def test_writes_refused_from_a_non_loopback_client(
    db_session: Session, secret_key: None, owner_auth: str
) -> None:
    from costura.main import app

    app.dependency_overrides[get_session] = request_session(db_session)
    headers = {"Authorization": owner_auth}
    try:
        with TestClient(app, client=("192.168.1.20", 50000), headers=headers) as remote:
            assert remote.post(f"{BASE}/sync").status_code == 403
            assert remote.get(f"{BASE}/connection").json()["writes_enabled"] is False
        with TestClient(app, client=("127.0.0.1", 50000), headers=headers) as local:
            assert local.get(f"{BASE}/connection").json()["writes_enabled"] is True
        with TestClient(app, client=("::1", 50000), headers=headers) as local6:
            assert local6.get(f"{BASE}/connection").json()["writes_enabled"] is True
    finally:
        app.dependency_overrides.clear()


def test_cors_allows_the_web_origin(api: TestClient, db_session: Session) -> None:
    origin = get_settings().costura_web_origin
    response = api.get("/api/v1/orgs", headers={"Origin": origin})
    assert response.headers.get("access-control-allow-origin") == origin
