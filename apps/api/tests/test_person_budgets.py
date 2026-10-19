"""A budget for one person across every provider: stored under provider `all`, spent from the
e-mail's `person` row, evaluated into alerts, and written only through the `all` routes."""

from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from costura import accounts
from costura.models.budget import PERSON_BUDGET_PROVIDER
from costura.providers.anthropic.client import AnthropicAdminClient
from costura.providers.anthropic.inventory import run_inventory_sync
from costura.providers.anthropic.sync import run_cost_sync, run_usage_sync
from costura.spend.allocate import run_allocation
from costura.spend.budgets import (
    InvalidBudget,
    budget_statuses,
    evaluate_budgets,
    set_budget,
)
from costura.spend.usage import usage_report
from tests.conftest import ORG_ID, sign_in, target
from tests.support.spend import AUGUST, FIXTURE_END, FIXTURE_START

ALICE = "alice@example.com"


def _synced(db_session: Session, client: AnthropicAdminClient) -> Decimal:
    run_cost_sync(
        db_session, target(db_session, ORG_ID, "anthropic"), client, FIXTURE_START, FIXTURE_END
    )
    run_usage_sync(
        db_session, target(db_session, ORG_ID, "anthropic"), client, FIXTURE_START, FIXTURE_END
    )
    run_inventory_sync(db_session, target(db_session, ORG_ID, "anthropic"), client)
    run_allocation(db_session, ORG_ID, "anthropic", AUGUST)
    people = usage_report(
        db_session, org_id=ORG_ID, provider="all", window=AUGUST, dimension="person"
    )
    return next(row.amount for row in people.rows if row.key == ALICE and row.amount)


def test_a_person_budget_spends_the_persons_row_and_raises_alerts(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    alice_spend = _synced(db_session, anthropic_client)
    budget = set_budget(
        db_session,
        ORG_ID,
        PERSON_BUDGET_PROVIDER,
        "person",
        " Alice@Example.com ",
        alice_spend * 2,
        [25, 50, 100],
    )
    assert budget.scope_id == ALICE

    statuses = budget_statuses(db_session, ORG_ID, "all", AUGUST)
    person = [s for s in statuses if s.budget.scope_kind == "person"]
    assert len(person) == 1
    assert person[0].spent == alice_spend
    assert person[0].projected is None
    assert person[0].percent == Decimal("50.00")
    assert not [
        s
        for s in budget_statuses(db_session, ORG_ID, "anthropic", AUGUST)
        if s.budget.scope_kind == "person"
    ]

    result = evaluate_budgets(db_session, ORG_ID, PERSON_BUDGET_PROVIDER, AUGUST)
    assert result.inserted == 2
    assert sorted(a.threshold for a in result.statuses[0].alerts) == [25, 50]
    assert evaluate_budgets(db_session, ORG_ID, PERSON_BUDGET_PROVIDER, AUGUST).inserted == 0


@pytest.mark.parametrize(
    ("provider", "scope_kind", "scope_id"),
    [
        ("anthropic", "person", ALICE),
        (PERSON_BUDGET_PROVIDER, "workspace", "wrkspc_a"),
        (PERSON_BUDGET_PROVIDER, "person", "not-an-email"),
    ],
)
def test_person_scope_and_provider_all_go_together(
    db_session: Session, provider: str, scope_kind: str, scope_id: str
) -> None:
    with pytest.raises(InvalidBudget):
        set_budget(db_session, ORG_ID, provider, scope_kind, scope_id, Decimal("10"), None)


def test_person_budget_routes(db_session: Session, anthropic_client: AnthropicAdminClient) -> None:
    from costura.main import app

    _synced(db_session, anthropic_client)
    api = TestClient(app)
    api.headers["Authorization"] = sign_in(db_session, "owner@costura.example", owner_of="default")
    base = "/api/v1/orgs/default/providers"

    put = api.put(f"{base}/all/budgets/person/Alice@Example.com", json={"amount": "100"})
    assert put.status_code == 200, put.text
    assert (put.json()["provider"], put.json()["scope_id"]) == ("all", ALICE)
    assert put.json()["label"] == ALICE
    assert (
        api.put(f"{base}/all/budgets/person/nobody@example.com", json={"amount": "1"}).status_code
        == 404
    )
    assert (
        api.put(f"{base}/anthropic/budgets/person/{ALICE}", json={"amount": "1"}).status_code == 422
    )
    assert api.put(f"{base}/all/budgets/workspace/w1", json={"amount": "1"}).status_code == 400

    listed = api.get(f"{base}/all/budgets").json()["budgets"]
    assert [(b["provider"], b["scope_kind"]) for b in listed] == [("all", "person")]
    assert api.get(f"{base}/anthropic/budgets").json()["budgets"] == []
    month = api.get(f"{base}/all/months/2026-08/budgets").json()
    assert [s["budget"]["scope_id"] for s in month["statuses"]] == [ALICE]

    assert api.delete(f"{base}/all/budgets/person/ALICE@example.com").status_code == 204
    assert api.get(f"{base}/all/budgets").json()["budgets"] == []


def test_a_person_budget_sums_two_providers(
    db_session: Session,
    anthropic_client: AnthropicAdminClient,
    copilot_client: object,
) -> None:
    from costura.models import ProviderAccount
    from costura.providers.copilot.inventory import run_inventory_sync as copilot_inventory
    from costura.providers.copilot.sync import run_cost_sync, run_user_sync
    from costura.spend.allocate import run_allocation as allocate

    anthropic_only = _synced(db_session, anthropic_client)
    unit = target(db_session, ORG_ID, "copilot")
    account = db_session.get(ProviderAccount, unit.account_id)
    assert account is not None
    accounts.set_copilot_logins(account, {"alice-gh": ALICE})
    db_session.flush()
    copilot_inventory(db_session, unit, copilot_client)
    start = AUGUST.start
    end = start + timedelta(days=1)
    run_cost_sync(db_session, unit, copilot_client, start, end)
    run_user_sync(db_session, unit, copilot_client, start, end)
    allocate(db_session, ORG_ID, "copilot", AUGUST)
    copilot_alice = usage_report(
        db_session, org_id=ORG_ID, provider="copilot", window=AUGUST, dimension="person"
    )
    extra = next(row.amount for row in copilot_alice.rows if row.label == ALICE and row.amount)
    assert extra > 0

    set_budget(db_session, ORG_ID, PERSON_BUDGET_PROVIDER, "person", ALICE, Decimal("1000"), None)
    [status] = [
        s
        for s in budget_statuses(db_session, ORG_ID, "all", AUGUST)
        if s.budget.scope_kind == "person"
    ]
    assert status.spent == anthropic_only + extra


def test_an_organization_budget_under_all_sums_every_provider(
    db_session: Session, anthropic_client: AnthropicAdminClient
) -> None:
    from costura.spend.budgets import budget_statuses
    from costura.spend.ledger import costura_total

    _synced(db_session, anthropic_client)
    set_budget(db_session, ORG_ID, PERSON_BUDGET_PROVIDER, "org", "__org__", Decimal("10"), [50])
    total, _ = costura_total(db_session, ORG_ID, PERSON_BUDGET_PROVIDER, AUGUST)
    [status] = [
        s
        for s in budget_statuses(db_session, ORG_ID, PERSON_BUDGET_PROVIDER, AUGUST)
        if s.budget.scope_kind == "org"
    ]
    assert status.spent == total and total > 0
    result = evaluate_budgets(db_session, ORG_ID, PERSON_BUDGET_PROVIDER, AUGUST)
    assert any(a.kind == "threshold" for s in result.statuses for a in s.alerts)
