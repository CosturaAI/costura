"""Invoice totals typed in per provider account and month: the routes, who may write them, and
how reconciliation compares a calendar month with them."""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from costura import accounts
from costura.api import schemas
from costura.models import ProviderInvoice
from costura.providers.anthropic.client import AnthropicAdminClient
from costura.providers.anthropic.sync import run_cost_sync
from costura.spend.invoices import invoice_total
from costura.spend.ledger import costura_total
from tests.conftest import ORG_ID, account_of, sign_in, target
from tests.support.spend import AUGUST, FIXTURE_END, FIXTURE_START

BASE = "/api/v1/orgs/default/providers/anthropic"


def _owner(db_session: Session) -> TestClient:
    from costura.main import app

    api = TestClient(app)
    api.headers["Authorization"] = sign_in(db_session, "owner@costura.example", owner_of="default")
    return api


def _synced(db_session: Session, client: AnthropicAdminClient) -> tuple[int, Decimal]:
    run_cost_sync(
        db_session, target(db_session, ORG_ID, "anthropic"), client, FIXTURE_START, FIXTURE_END
    )
    total, _ = costura_total(db_session, ORG_ID, "anthropic", AUGUST)
    return account_of(db_session, ORG_ID, "anthropic"), total


def test_reconcile_compares_a_month_with_its_stored_invoice(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    account, total = _synced(db_session, anthropic_client)
    api = _owner(db_session)
    reconcile = f"{BASE}/months/2026-08/reconcile"
    assert api.get(reconcile).json()["reported_source"] is None

    put = api.put(
        f"{BASE}/accounts/{account}/invoices/2026-08",
        json={"amount": str(total + Decimal("12.50")), "note": " includes VAT "},
    )
    assert put.status_code == 200, put.text
    assert put.json()["note"] == "includes VAT"
    assert put.json()["entered_by"] == "owner@costura.example"
    listed = api.get(f"{BASE}/months/2026-08/invoices").json()
    assert [row["account_id"] for row in listed["items"]] == [account]

    body = api.get(reconcile).json()
    assert body["reported_source"] == "invoice"
    assert Decimal(body["reported_total"]) == (total + Decimal("12.50")).quantize(Decimal("0.01"))
    invoiced = (total + Decimal("12.50")).quantize(Decimal("0.01"))
    assert body["delta"] == schemas.money(total - invoiced)
    assert body["matches"] is False

    api.put(f"{BASE}/accounts/{account}/invoices/2026-08", json={"amount": str(total)})
    assert api.get(reconcile).json()["matches"] is True

    typed = api.get(reconcile, params={"reported": "1.00"}).json()
    assert typed["reported_source"] == "query"
    assert typed["reported_total"] == "1.00"
    partial = api.get(reconcile, params={"start": "2026-08-01", "end": "2026-08-15"}).json()
    assert partial["reported_source"] is None

    assert api.delete(f"{BASE}/accounts/{account}/invoices/2026-08").status_code == 204
    assert api.delete(f"{BASE}/accounts/{account}/invoices/2026-08").status_code == 404
    assert api.get(reconcile).json()["reported_source"] is None


def test_invoice_writes_are_owner_only_and_validated(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    from costura.main import app

    account, _ = _synced(db_session, anthropic_client)
    api = _owner(db_session)
    url = f"{BASE}/accounts/{account}/invoices"
    assert api.put(f"{url}/2026-13", json={"amount": "1"}).status_code == 422
    assert api.put(f"{url}/2026-08", json={"amount": "-1"}).status_code == 422
    other = account_of(db_session, ORG_ID, "openai")
    wrong = api.put(f"{BASE}/accounts/{other}/invoices/2026-08", json={"amount": "1"})
    assert wrong.status_code == 404
    everywhere = api.put(
        f"/api/v1/orgs/default/providers/all/accounts/{account}/invoices/2026-08",
        json={"amount": "1"},
    )
    assert everywhere.status_code == 400

    member = TestClient(app)
    member.headers["Authorization"] = sign_in(
        db_session, "member@costura.example", role_in="member"
    )
    assert member.put(f"{url}/2026-08", json={"amount": "1"}).status_code == 403
    assert member.get(f"{BASE}/months/2026-08/invoices").status_code == 200


def test_a_provider_month_needs_an_invoice_for_every_account_that_spent(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    account, total = _synced(db_session, anthropic_client)
    idle = accounts.ensure_default_account(db_session, ORG_ID, "anthropic")
    second = accounts.create_account(db_session, ORG_ID, "anthropic", label="Second console")
    db_session.flush()
    ids = [idle.id, second.id]
    assert invoice_total(db_session, ORG_ID, "anthropic", "2026-08", ids) is None

    db_session.add(
        ProviderInvoice(
            organization_id=ORG_ID,
            provider="anthropic",
            provider_account_id=account,
            month="2026-08",
            amount=Decimal("10.00"),
        )
    )
    db_session.flush()
    # The second account has no cost lines, so it needs no invoice.
    assert invoice_total(db_session, ORG_ID, "anthropic", "2026-08", ids) == Decimal("10.00")
    assert (
        invoice_total(db_session, ORG_ID, "anthropic", "2026-08", ids, account_id=second.id) is None
    )
    assert total > 0
