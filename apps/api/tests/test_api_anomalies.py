from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura import secrets
from costura.api.deps import (
    get_session,
)
from costura.config import get_settings
from costura.models import (
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
from costura.providers.runs import refresh_observed_models
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


def test_anomalies_person_filter(api: TestClient, intelligence: None, people_synced: None) -> None:
    # The synthetic anomalies are org and api_key series; a person filter selects account
    # series only, so the list is empty but well-formed, and an unknown address matches nothing.
    body = api.get(f"{ALL_BASE}/months/2026-08/anomalies", params={"person": PERSON}).json()
    assert (body["month"], body["open_count"], body["anomalies"]) == ("2026-08", 0, [])
    nobody = api.get(f"{ALL_BASE}/months/2026-08/anomalies", params={"person": "x@y.z"}).json()
    assert nobody["anomalies"] == []


def test_anomalies_list_pages_with_total(api: TestClient, intelligence: None) -> None:
    whole = api.get(f"{BASE}/months/2026-08/anomalies").json()
    first = api.get(f"{BASE}/months/2026-08/anomalies", params={"limit": 1}).json()
    second = api.get(f"{BASE}/months/2026-08/anomalies", params={"limit": 1, "offset": 1}).json()

    assert (whole["total"], whole["limit"], whole["offset"]) == (2, 500, 0)
    assert first["total"] == 2 and len(first["anomalies"]) == 1
    assert [first["anomalies"][0]["id"], second["anomalies"][0]["id"]] == [
        a["id"] for a in whole["anomalies"]
    ]
    assert api.get(f"{BASE}/months/2026-08/anomalies", params={"limit": 1001}).status_code == 422


def test_anomalies_list_labels_and_open_count(api: TestClient, intelligence: None) -> None:
    body = api.get(f"{BASE}/months/2026-08/anomalies").json()

    # The organization total and the key that spent it; the workspace and the model are
    # root causes, not rows.
    assert body["month"] == "2026-08" and body["open_count"] == 2
    assert {a["series_kind"] for a in body["anomalies"]} == {"org", "api_key"}
    org = next(a for a in body["anomalies"] if a["series_kind"] == "org")
    assert org["label"] == "organization total"
    assert org["day"] == "2026-08-11"
    assert (org["actual"], org["expected"], org["upper_bound"]) == ("540.00", "100.00", "120.00")
    assert (org["baseline_method"], org["baseline_samples"]) == ("weekday", 8)
    assert org["impact"] == "440.00" and org["impact_percent"] == "440.00"
    # Aug 1-11: two weekends (4 x 20), five weekdays (5 x 100), Monday 100, the spike 540.
    assert org["impact_share"] == "36.07"
    assert org["status"] == "open"
    assert {c["kind"] for c in org["root_causes"]} == {"api_key", "model"}
    # Ids absent from the inventory keep their marker in the label.
    key = next(a for a in body["anomalies"] if a["series_kind"] == "api_key")
    assert key["label"] == "apikey_a (not in inventory)"
    assert {c["label"] for c in key["root_causes"]} == {"claude-opus-4-1"}

    assert api.get(f"{BASE}/months/2026-08/anomalies?status=acknowledged").json()["anomalies"] == []
    assert api.get(f"{BASE}/months/2026-07/anomalies").json() == {
        "month": "2026-07",
        "start": "2026-07-01",
        "end": "2026-07-31",
        "window_total": "2460.00",
        "open_count": 0,
        "open_total": 2,
        "anomalies": [],
        "total": 0,
        "limit": 500,
        "offset": 0,
    }
    assert api.get(f"{BASE}/months/2026-08/anomalies?status=bogus").status_code == 422


def test_anomalies_follow_a_date_range(api: TestClient, intelligence: None) -> None:
    month = api.get(f"{BASE}/months/2026-08/anomalies").json()
    through_spike = api.get(
        f"{BASE}/months/2026-08/anomalies", params={"start": "2026-08-01", "end": "2026-08-11"}
    ).json()
    assert (through_spike["start"], through_spike["end"]) == ("2026-08-01", "2026-08-11")
    assert [a["id"] for a in through_spike["anomalies"]] == [a["id"] for a in month["anomalies"]]
    assert through_spike["window_total"] == "1220.00"

    before = api.get(
        f"{BASE}/months/2026-08/anomalies", params={"start": "2026-07-01", "end": "2026-08-10"}
    ).json()
    assert (before["open_count"], before["anomalies"]) == (0, [])
    assert before["open_total"] == month["open_total"] == 2


def test_a_date_range_needs_both_ends_in_order(api: TestClient, intelligence: None) -> None:
    url = f"{BASE}/months/2026-08/anomalies"
    assert api.get(url, params={"start": "2026-08-01"}).status_code == 422
    assert api.get(url, params={"start": "2026-08-02", "end": "2026-08-01"}).status_code == 422
    assert api.get(url, params={"start": "2010-01-01", "end": "2026-08-01"}).status_code == 422
    assert api.get(url, params={"start": "2026-02-30", "end": "2026-03-01"}).status_code == 422


def test_anomalies_filter_by_series(api: TestClient, intelligence: None) -> None:
    by_kind = api.get(f"{BASE}/months/2026-08/anomalies", params={"series_kind": "api_key"})
    assert by_kind.json()["open_count"] == by_kind.json()["open_total"] == 1
    assert [a["series_id"] for a in by_kind.json()["anomalies"]] == ["apikey_a"]

    by_id = api.get(f"{BASE}/months/2026-08/anomalies", params={"series_id": "apikey_a"})
    assert [a["series_kind"] for a in by_id.json()["anomalies"]] == ["api_key"]

    none = api.get(
        f"{BASE}/months/2026-08/anomalies",
        params={"series_kind": "account", "series_id": "apikey_a"},
    ).json()
    assert (none["month"], none["open_count"], none["anomalies"]) == ("2026-08", 0, [])
    assert (
        api.get(f"{BASE}/months/2026-08/anomalies", params={"series_kind": "colour"}).status_code
        == 422
    )


def test_anomaly_status_patch(api: TestClient, intelligence: None) -> None:
    listed = api.get(f"{BASE}/months/2026-08/anomalies").json()["anomalies"]
    org_id = next(a["id"] for a in listed if a["series_kind"] == "org")

    patched = api.patch(
        f"{BASE}/anomalies/{org_id}",
        json={"status": "acknowledged", "reason": "expected: the monthly batch backfill"},
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "acknowledged"
    assert patched.json()["status_reason"] == "expected: the monthly batch backfill"
    assert patched.json()["status_changed_by"] == "owner@example.com"
    assert patched.json()["status_changed_at"] is not None
    assert api.get(f"{BASE}/months/2026-08/anomalies").json()["open_count"] == 1
    acknowledged = api.get(f"{BASE}/months/2026-08/anomalies?status=acknowledged").json()
    assert acknowledged["anomalies"][0]["id"] == org_id

    assert api.patch(f"{BASE}/anomalies/{org_id}", json={"status": "later"}).status_code == 422
    assert api.patch(f"{BASE}/anomalies/999999", json={"status": "ignored"}).status_code == 404


def test_entity_lookup_names_the_provider_of_an_id(
    api: TestClient, db_session: Session, both_synced: None, intelligence: None
) -> None:
    """The web's entity pages carry no provider in their address; this route says
    which provider a key, workspace, account, model or anomaly id belongs to."""
    lookup = "/api/v1/orgs/default/entities"
    assert api.get(f"{lookup}/key/apikey_redacted_2").json() == {
        "provider": "anthropic",
        "provider_account_id": account_of(db_session, ORG_ID, "anthropic"),
    }
    assert api.get(f"{lookup}/workspace/wrkspc_redacted_a").json()["provider"] == "anthropic"
    assert api.get(f"{lookup}/account/user_redacted_alice").json()["provider"] == "anthropic"
    assert api.get(f"{lookup}/model/claude-opus-5").json()["provider"] == "anthropic"
    # Slashes in a model name are part of the id.
    assert api.get(f"{lookup}/model/openai/gpt-5.2").json()["provider"] == "openrouter"

    listed = api.get(f"{BASE}/months/2026-08/anomalies").json()["anomalies"]
    assert api.get(f"{lookup}/anomaly/{listed[0]['id']}").json()["provider"] == "anthropic"

    # A model name used under two providers: the session scope wins, else the newest line.
    line = db_session.scalars(
        select(SpendCostLine).where(SpendCostLine.model == "claude-opus-5")
    ).first()
    assert line is not None
    db_session.add(
        SpendCostLine(
            organization_id=ORG_ID,
            provider="openrouter",
            provider_account_id=account_of(db_session, ORG_ID, "openrouter"),
            period_start=line.period_start + timedelta(days=60),
            period_end=line.period_end + timedelta(days=60),
            workspace_id=None,
            description="shared name",
            cost_type="tokens",
            model="claude-opus-5",
            amount=Decimal("1"),
            currency="USD",
            raw_amount_minor="100",
            sync_run_id=line.sync_run_id,
        )
    )
    refresh_observed_models(
        db_session, ORG_ID, "openrouter", line.period_start + timedelta(days=61)
    )
    db_session.commit()
    assert api.get(f"{lookup}/model/claude-opus-5").json()["provider"] == "openrouter"
    assert (
        api.get(f"{lookup}/model/claude-opus-5", params={"scope": "anthropic"}).json()["provider"]
        == "anthropic"
    )

    for path in ("key/apikey_ghost", "anomaly/999999", "anomaly/abc", "model/nope", "thing/x"):
        assert api.get(f"{lookup}/{path}").status_code == 404, path
    # Another tenant's ids are not visible.
    create_org(db_session, "acme", "Acme", owner=_owner(db_session))
    assert api.get("/api/v1/orgs/acme/entities/key/apikey_redacted_2").status_code == 404


def test_anomalies_sort_by_impact_across_days(api: TestClient, intelligence: None) -> None:
    by_day = api.get(f"{BASE}/months/2026-08/anomalies").json()["anomalies"]
    by_impact = api.get(f"{BASE}/months/2026-08/anomalies", params={"sort": "impact"}).json()
    impacts = [float(a["impact"]) for a in by_impact["anomalies"]]
    assert impacts == sorted(impacts, reverse=True)
    assert {a["id"] for a in by_impact["anomalies"]} == {a["id"] for a in by_day}
    by_severity = api.get(f"{BASE}/months/2026-08/anomalies", params={"sort": "severity"}).json()
    rank = {"high": 2, "medium": 1, "low": 0}
    ranked = [rank[a["severity"]] for a in by_severity["anomalies"]]
    assert ranked == sorted(ranked, reverse=True)
    assert {a["id"] for a in by_severity["anomalies"]} == {a["id"] for a in by_day}
    assert api.get(f"{BASE}/months/2026-08/anomalies", params={"sort": "size"}).status_code == 422


def test_anomaly_detail_series_same_day_and_owners(api: TestClient, intelligence: None) -> None:
    listed = api.get(f"{BASE}/months/2026-08/anomalies").json()["anomalies"]
    org = next(a for a in listed if a["series_kind"] == "org")
    assert org["investigate"] == {
        "by": "workspace",
        "filters": {
            "provider": "anthropic",
            "provider_account": str(org["provider_account_id"]),
        },
        "measure": "billed_usd",
    }

    body = api.get(f"{BASE}/anomalies/{org['id']}").json()

    assert {k: body[k] for k in ("id", "impact", "impact_share", "status")} == {
        "id": org["id"],
        "impact": "440.00",
        "impact_share": "36.07",
        "status": "open",
    }
    # Eight weeks ending on the anomaly day, the same Tuesdays marked as baseline samples.
    assert len(body["series"]) == 57
    assert body["series"][-1] == {"day": "2026-08-11", "amount": "540.00", "baseline_sample": False}
    samples = [p["day"] for p in body["series"] if p["baseline_sample"]]
    tuesdays = ((6, 16), (6, 23), (6, 30), (7, 7), (7, 14), (7, 21), (7, 28), (8, 4))
    assert samples == [f"2026-0{m}-{d:02d}" for m, d in tuesdays]
    assert all(p["amount"] == "100.00" for p in body["series"] if p["baseline_sample"])
    # The chart marks and the evidence card list the same days.
    assert samples == sorted(s["day"] for s in body["evidence"]["baseline"]["samples"])
    # The key anomaly of the same day.
    assert [s["series_kind"] for s in body["same_day"]] == ["api_key"]
    assert [s["kind"] for s in body["same_day"]] == ["spike"]
    assert body["same_day"][0]["label"] == "apikey_a (not in inventory)"
    # No inventory in this fixture: the Costura organization owner closes the list.
    assert body["owners"] == [
        {
            "email": OWNER_EMAIL,
            "role": "organization owner",
            "source": "Costura organization",
            "note": None,
        }
    ]
    # The evidence block recomputes the detector's figures from the data.
    evidence = body["evidence"]
    baseline = evidence["baseline"]
    assert (baseline["method"], baseline["margin_rule"], baseline["matches_stored"]) == (
        "weekday",
        "relative",
        True,
    )
    assert baseline["samples"][0] == {
        "day": "2026-08-04",
        "amount": "100.00",
        "value": "100.00",
        "adjusted": False,
    }
    assert (baseline["sensitivity"], baseline["trend_per_week"]) == ("normal", "0.00")
    assert baseline["lower_bound"] == "80.00"
    assert (baseline["median"], baseline["mad"], baseline["upper_bound"]) == (
        "100.00",
        "0.00",
        "120.00",
    )
    assert (baseline["margin_mad"], baseline["margin_relative"], baseline["margin_absolute"]) == (
        "0.00",
        "20.00",
        "5.00",
    )
    assert (baseline["stored_actual"], baseline["actual_now"]) == ("540.00", "540.00")
    assert len(evidence["checks"]) == 8 and all(c["passed"] for c in evidence["checks"])
    assert evidence["checks"][0] == {
        "name": "above_upper_bound",
        "passed": True,
        "observed": "540.00",
        "threshold": "120.00",
        "reason": "within upper bound",
    }
    assert [b["dimension"] for b in evidence["breakdowns"]] == [
        "api_key",
        "account",
        "model",
        "workspace",
    ]
    keys = evidence["breakdowns"][0]["rows"]
    assert keys[0]["label"] == "apikey_a (not in inventory)"
    assert (keys[0]["amount"], keys[0]["new"]) == ("500.00", False)
    assert keys[0]["tokens"]["uncached_input_tokens"] > 0
    workspaces = evidence["breakdowns"][3]["rows"]
    assert workspaces[0]["label"] == "ws_a (not in inventory)"
    economics = evidence["unit_economics"]
    assert economics["sample_days"] == 8 and economics["day"]["amount"] == "540.00"
    assert economics["baseline"]["amount"] == "100.00"
    # The seed derives the tokens from the money, so the day prices out per million.
    assert int(economics["day"]["total_tokens"]) > 0
    assert economics["day"]["cost_per_million"] is not None
    assert body["explanation"].startswith(
        "organization total spent 440.00 USD more than expected (440% over); "
    )
    assert "accounts for 100% of the increase, on claude-opus-4-1" in body["explanation"]
    # Opus jumps while Sonnet holds: more tokens (volume) and a dearer mix, at unchanged prices.
    split = evidence["decomposition"]
    assert (split["change"], split["price"], split["top_model"]) == (
        "440.00",
        "0.00",
        "claude-opus-4-1",
    )
    assert Decimal(split["mix"]) > 0 and Decimal(split["volume"]) > 0
    parts = Decimal(split["volume"]) + Decimal(split["mix"]) + Decimal(split["price"])
    assert abs(parts - Decimal(split["change"])) <= Decimal("0.02")
    quality = evidence["data_quality"]
    assert quality["changed_since_detection"] is False and quality["unallocated_amount"] == "0.00"
    assert (quality["cost_lines"], quality["allocated_lines"], quality["usage_lines"]) == (2, 2, 2)
    assert {r["endpoint"] for r in quality["runs"]} == {
        "cost_report",
        "usage_report_messages",
        "allocation",
        "anomaly_detection",
        "projection",
    }
    assert evidence["history"] == []

    # Under `all` the same id resolves; under another provider it does not.
    assert api.get(f"/api/v1/orgs/default/providers/all/anomalies/{org['id']}").status_code == 200
    assert (
        api.get(f"/api/v1/orgs/default/providers/openrouter/anomalies/{org['id']}").status_code
        == 404
    )
    assert api.get(f"{BASE}/anomalies/999999").status_code == 404


def test_projection_by_kind(api: TestClient, intelligence: None) -> None:
    body = api.get(f"{BASE}/months/2026-08/projection").json()

    assert body["by"] == "org" and len(body["projections"]) == 1
    org = body["projections"][0]
    assert org["label"] == "organization total"
    assert org["as_of_day"] == "2026-08-20"
    # mtd 1,960 (spike included); 7 weekdays and 4 weekend days remain.
    assert (org["mtd"], org["projected_total"]) == ("1960.00", "2740.00")
    # The Aug 11 spike is one of 8 Tuesday samples for Aug 25: p90 lifts the high by
    # 440 x 0.3 = 132, not by the full 440.
    assert (org["low"], org["high"]) == ("2740.00", "2872.00")
    assert len(org["days"]) == 11
    assert org["days"][0] == {
        "day": "2026-08-21",
        "expected": "100.00",
        "low": "100.00",
        "high": "100.00",
        "samples": 8,
    }

    workspaces = api.get(f"{BASE}/months/2026-08/projection?by=workspace").json()["projections"]
    assert [p["series_id"] for p in workspaces] == ["ws_a", "ws_b"]
    assert api.get(f"{BASE}/months/2026-07/projection").json()["projections"] == []
    assert api.get(f"{BASE}/months/2026-08/projection?by=day").status_code == 422


def test_posture_thresholds_are_saved_and_move_the_signals(
    api: TestClient, db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    from costura.providers.anthropic.inventory import run_inventory_sync

    run_inventory_sync(db_session, target(db_session, ORG_ID, "anthropic"), anthropic_client)
    settings = "/api/v1/orgs/default/anomaly-settings"
    defaults = api.get(settings).json()
    assert (defaults["idle_days"], defaults["new_key_days"]) == (30, 7)

    idle = {
        s["entity_id"]
        for s in api.get(f"{BASE}/signals").json()["items"]
        if s["kind"] == "idle_active"
    }
    assert idle

    body = {**defaults, "idle_days": 365, "new_key_days": 1}
    saved = api.put(settings, json=body)
    assert saved.status_code == 200 and saved.json()["idle_days"] == 365
    after = api.get(f"{BASE}/signals").json()["items"]
    assert not any(s["kind"] == "idle_active" for s in after)

    assert api.put(settings, json={**defaults, "idle_days": 3}).status_code == 422
    assert api.put(settings, json={**defaults, "new_key_days": 91}).status_code == 422
