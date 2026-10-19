"""Keys a member marked as one person's own: the `person` dimension, the person filter, the
month's people share, the key's inventory row and the routes that record the mark."""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from costura.models import PersonalKeyAssignment, ProviderApiKey, SpendAllocatedLine
from costura.providers.anthropic.client import AnthropicAdminClient
from costura.providers.anthropic.inventory import run_inventory_sync
from costura.providers.anthropic.sync import run_cost_sync, run_usage_sync
from costura.spend.allocate import run_allocation
from costura.spend.inventory import InventoryResolver
from costura.spend.summary import summary
from costura.spend.usage import UsageRow, usage_report
from tests.conftest import ORG_ID, sign_in, target
from tests.support.spend import AUGUST, FIXTURE_END, FIXTURE_START

SPENDING_KEY = "apikey_redacted_1"
SERVICE_KEY = "apikey_redacted_2"
BOB = "bob@example.com"
ALICE = "alice@example.com"


def _synced(db_session: Session, client: AnthropicAdminClient) -> None:
    run_cost_sync(
        db_session, target(db_session, ORG_ID, "anthropic"), client, FIXTURE_START, FIXTURE_END
    )
    run_usage_sync(
        db_session, target(db_session, ORG_ID, "anthropic"), client, FIXTURE_START, FIXTURE_END
    )
    run_inventory_sync(db_session, target(db_session, ORG_ID, "anthropic"), client)
    run_allocation(db_session, ORG_ID, "anthropic", AUGUST)


def _rows(db_session: Session, dimension: str, **filters: str) -> list[UsageRow]:
    return usage_report(
        db_session,
        org_id=ORG_ID,
        provider="anthropic",
        window=AUGUST,
        dimension=dimension,
        filters=filters or None,
    ).rows


def _amount(rows: list[UsageRow], label: str) -> Decimal:
    return sum((row.amount or Decimal("0") for row in rows if row.label == label), Decimal("0"))


def _mark(db_session: Session, api_key_id: str, email: str) -> None:
    db_session.add(
        PersonalKeyAssignment(
            organization_id=ORG_ID, provider="anthropic", api_key_id=api_key_id, email=email
        )
    )
    db_session.flush()


def test_a_marked_service_key_moves_from_api_key_requests_to_the_person(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    _synced(db_session, anthropic_client)
    key_amount = next(row.amount for row in _rows(db_session, "api_key") if row.key == SPENDING_KEY)
    assert key_amount is not None and key_amount > 0
    before = _rows(db_session, "person")
    share_before = summary(db_session, org_id=ORG_ID, provider="anthropic", month="2026-08")

    _mark(db_session, SPENDING_KEY, BOB)

    after = _rows(db_session, "person")
    assert _amount(after, BOB) == _amount(before, BOB) + key_amount
    assert _amount(after, "(api key request)") == _amount(before, "(api key request)") - key_amount
    bob = next(row for row in after if row.label == BOB)
    assert bob.details["kind"] == "person"
    assert SPENDING_KEY in {row.key for row in _rows(db_session, "api_key", person=BOB)}

    share_after = summary(db_session, org_id=ORG_ID, provider="anthropic", month="2026-08")
    assert share_before.people_total is not None and share_after.people_total is not None
    assert share_after.people_total == share_before.people_total + key_amount
    assert share_after.people_share is not None and share_before.people_share is not None
    assert share_after.people_share > share_before.people_share


def test_a_mark_wins_over_the_claude_code_creator(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    _synced(db_session, anthropic_client)
    template = db_session.scalar(
        select(SpendAllocatedLine).where(
            SpendAllocatedLine.organization_id == ORG_ID,
            SpendAllocatedLine.api_key_id == SPENDING_KEY,
            SpendAllocatedLine.amount > 0,
        )
    )
    key = db_session.scalar(
        select(ProviderApiKey).where(
            ProviderApiKey.organization_id == ORG_ID, ProviderApiKey.external_id == SPENDING_KEY
        )
    )
    assert template is not None and key is not None
    db_session.add(
        ProviderApiKey(
            organization_id=ORG_ID,
            provider="anthropic",
            provider_account_id=key.provider_account_id,
            external_id="alice_session_key",
            name="claude_code_key_alice_session",
            workspace_external_id=key.workspace_external_id,
            created_by_external_id="user_redacted_alice",
            status="active",
            sync_run_id=key.sync_run_id,
        )
    )
    template.api_key_id = "alice_session_key"
    db_session.flush()
    resolver = InventoryResolver(db_session, ORG_ID, "anthropic")
    assert resolver.key_person("anthropic", "alice_session_key") == ALICE
    alice_before = _amount(_rows(db_session, "person"), ALICE)

    _mark(db_session, "alice_session_key", BOB)

    resolver = InventoryResolver(db_session, ORG_ID, "anthropic")
    assert resolver.key_person("anthropic", "alice_session_key") == BOB
    assert ("anthropic", "alice_session_key") not in resolver.personal_key_identities_of(
        "user_redacted_alice"
    )
    after = _rows(db_session, "person")
    assert _amount(after, ALICE) == alice_before - template.amount
    assert "alice_session_key" not in {
        row.key for row in _rows(db_session, "api_key", person=ALICE)
    }
    assert "alice_session_key" in {row.key for row in _rows(db_session, "api_key", person=BOB)}


def test_personal_key_routes_are_member_writes_for_known_people(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    from costura import auth
    from costura.main import app
    from costura.orgs import get_org
    from tests.support.orgs import add_member

    _synced(db_session, anthropic_client)
    sign_in(db_session, "owner@costura.example", owner_of="default")
    member = auth.sign_in_dev(db_session, "member@costura.example")
    add_member(db_session, get_org(db_session, "default"), member.user, "member")
    db_session.commit()
    api = TestClient(app)
    api.headers["Authorization"] = f"Bearer {member.token}"
    base = "/api/v1/orgs/default/providers/anthropic/personal-keys"
    key_url = f"/api/v1/orgs/default/providers/anthropic/inventory/api-keys/{SERVICE_KEY}"

    assert api.get(base).json() == []
    assert api.get(key_url).json()["person"] is None
    assert api.put(f"{base}/{SERVICE_KEY}", json={"email": "nope"}).status_code == 422
    unknown = api.put(f"{base}/{SERVICE_KEY}", json={"email": "stranger@example.com"})
    assert unknown.status_code == 422
    everywhere = api.put("/api/v1/orgs/default/providers/all/personal-keys/x", json={"email": BOB})
    assert everywhere.status_code == 400
    put = api.put(f"{base}/{SERVICE_KEY}", json={"email": " Bob@Example.com "})
    assert put.status_code == 200, put.text
    assert put.json()["email"] == BOB
    assert put.json()["label"] == "batch-ingest (apikey_redacted_2)"
    assert put.json()["assigned_by"] == "member@costura.example"
    assert [row["api_key_id"] for row in api.get(base).json()] == [SERVICE_KEY]
    listed = api.get("/api/v1/orgs/default/providers/all/personal-keys").json()
    assert [row["api_key_id"] for row in listed] == [SERVICE_KEY]
    key = api.get(key_url).json()
    assert (key["person"], key["person_source"]) == (BOB, "marked")

    viewer = TestClient(app)
    viewer.headers["Authorization"] = sign_in(
        db_session, "viewer@costura.example", role_in="viewer"
    )
    assert viewer.put(f"{base}/{SERVICE_KEY}", json={"email": BOB}).status_code == 403
    assert viewer.delete(f"{base}/{SERVICE_KEY}").status_code == 403

    assert api.delete(f"{base}/{SERVICE_KEY}").status_code == 204
    assert api.delete(f"{base}/{SERVICE_KEY}").status_code == 404
    assert api.get(base).json() == []
    assert api.get(key_url).json()["person"] is None
