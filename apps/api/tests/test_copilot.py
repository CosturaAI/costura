"""GitHub Copilot connector: normalization of the billing usage and AI credit reports, the seat
inventory with the login-to-e-mail table, the sync steps, direct allocation and the mapping
routes."""

from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from costura import accounts
from costura.models import (
    ProviderAccount,
    ProviderLimit,
    ProviderUser,
    SpendCostLine,
    SpendUsageLine,
)
from costura.providers.copilot.client import GitHubBillingClient, days_in, validate_org
from costura.providers.copilot.inventory import run_inventory_sync, users_from_payload
from costura.providers.copilot.normalize import (
    SEAT_MODEL,
    DayWindow,
    cost_lines_from_usage,
    credit_usage_lines,
    model_of,
    page_amount,
    seat_usage_lines,
)
from costura.providers.copilot.sync import run_cost_sync, run_user_sync
from costura.providers.lines import NormalizeError
from costura.spend.allocate import run_allocation
from costura.spend.usage import usage_report
from costura.spend.window import Window
from tests.conftest import ORG_ID, copilot_fixture_handler, load_fixture, sign_in, target

PROVIDER = "copilot"
DAY = DayWindow(date(2026, 8, 1))
START = datetime(2026, 8, 1, tzinfo=UTC)
END = datetime(2026, 8, 2, tzinfo=UTC)


def test_cost_lines_keep_copilot_skus_at_the_billed_amount() -> None:
    lines = cost_lines_from_usage(load_fixture("usage_day.json", "copilot")["usageItems"], DAY)
    by_sku = {line.description: line for line in lines}
    assert set(by_sku) == {"copilot_for_business", "copilot_ai_credit"}
    assert by_sku["copilot_for_business"].model == SEAT_MODEL
    assert all(line.cost_type == "tokens" for line in lines)
    assert by_sku["copilot_ai_credit"].amount == Decimal("2.5")
    assert by_sku["copilot_ai_credit"].list_amount == Decimal("4.0")
    assert all(line.period_start == DAY.start and line.provider == PROVIDER for line in lines)
    assert model_of("Copilot Premium Request") != SEAT_MODEL
    assert model_of("copilot_enterprise") == SEAT_MODEL
    assert page_amount(load_fixture("usage_day.json", "copilot"), START, END) == Decimal("3.7258")
    assert page_amount(load_fixture("usage_day.json", "copilot"), END, END) == Decimal("0")
    with pytest.raises(NormalizeError):
        cost_lines_from_usage([{"product": "Copilot", "sku": "x", "netAmount": -1}], DAY)


def test_credit_and_seat_usage_lines_attribute_to_logins() -> None:
    rows = load_fixture("ai_credit_alice.json", "copilot")["usageItems"]
    [line] = credit_usage_lines(rows, DAY, "alice-gh")
    assert (line.account_id, line.service_tier, line.amount, line.request_count) == (
        "alice-gh",
        "copilot_ai_credit",
        Decimal("2.0"),
        300,
    )
    seats = seat_usage_lines(Decimal("1.2258"), DAY, ["octocat", "alice-gh"])
    assert [s.account_id for s in seats] == ["alice-gh", "octocat"]
    assert sum(s.amount or 0 for s in seats) == Decimal("1.2258")
    assert all(s.model == SEAT_MODEL for s in seats)
    assert seat_usage_lines(Decimal("0"), DAY, []) == []
    [orphan] = seat_usage_lines(Decimal("5"), DAY, [])
    assert orphan.account_id.startswith("__")


def test_client_days_and_org_validation() -> None:
    now = datetime(2026, 8, 10, 12, tzinfo=UTC)
    assert days_in(START, datetime(2026, 8, 4, tzinfo=UTC), now=now) == [
        date(2026, 8, 1),
        date(2026, 8, 2),
        date(2026, 8, 3),
    ]
    assert days_in(datetime(2026, 8, 9, tzinfo=UTC), datetime(2026, 9, 1, tzinfo=UTC), now=now) == [
        date(2026, 8, 9),
        date(2026, 8, 10),
    ]
    assert validate_org(" acme-inc/ ") == "acme-inc"
    for bad in ("acme/inc", "acme?x=1", "acme#top", "..", "a" * 40, "acme inc", ""):
        with pytest.raises(ValueError):
            validate_org(bad)
    seen: list[str] = []

    def spy(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}?{request.url.query.decode()}")
        assert request.headers["x-github-api-version"]
        assert request.headers["authorization"] == "Bearer ghp_test"
        return copilot_fixture_handler(request)

    with GitHubBillingClient(
        token="ghp_test", org="acme-inc", transport=httpx.MockTransport(spy), sleep=lambda _: None
    ) as client:
        pages = list(client.ai_credit_pages(START, END, ["alice-gh", "octocat"]))
    assert len(pages) == 2
    assert all("GET " in call for call in seen)
    assert "user=alice-gh" in seen[0]


def test_inventory_maps_logins_to_emails(
    db_session: Session, copilot_client: GitHubBillingClient
) -> None:
    unit = target(db_session, ORG_ID, PROVIDER)
    account = db_session.get(ProviderAccount, unit.account_id)
    assert account is not None
    payload = load_fixture("seats_page1.json", "copilot")
    plain = {u.external_id: u.email for u in users_from_payload(payload)}
    assert plain == {"alice-gh": "alice-gh", "octocat": "octocat"}

    summary, budgets = run_inventory_sync(db_session, unit, copilot_client)
    assert summary.items == 2
    assert budgets.items == 2 and budgets.skipped_workspaces == []
    limits = {
        row.external_id: (row.scope_kind, row.scope_name, row.amount, row.consumed, row.enforcement)
        for row in db_session.scalars(select(ProviderLimit))
    }
    assert limits == {
        "budget_org": ("organization", "acme", Decimal("500"), Decimal("120.5"), "hard"),
        "budget_alice": ("user", "alice-gh", Decimal("50"), Decimal("10"), "soft"),
    }
    emails = dict(
        db_session.execute(
            select(ProviderUser.external_id, ProviderUser.email).where(
                ProviderUser.provider == PROVIDER
            )
        ).all()
    )
    # octocat has a public e-mail; alice has none and keeps the login until mapped.
    assert emails == {"alice-gh": "alice-gh", "octocat": "octocat@example.com"}

    accounts.set_copilot_logins(account, {"Alice-GH": " Alice@Example.com "})
    db_session.flush()
    run_inventory_sync(db_session, unit, copilot_client)
    emails = dict(
        db_session.execute(
            select(ProviderUser.external_id, ProviderUser.email).where(
                ProviderUser.provider == PROVIDER
            )
        ).all()
    )
    assert emails["alice-gh"] == "alice@example.com"
    with pytest.raises(ValueError):
        accounts.set_copilot_logins(account, {"x": "not-an-email"})


def test_sync_attributes_credits_and_seats_directly(
    db_session: Session, copilot_client: GitHubBillingClient
) -> None:
    unit = target(db_session, ORG_ID, PROVIDER)
    account = db_session.get(ProviderAccount, unit.account_id)
    assert account is not None
    accounts.set_copilot_logins(account, {"alice-gh": "alice@example.com"})
    db_session.flush()
    run_inventory_sync(db_session, unit, copilot_client)
    run_cost_sync(db_session, unit, copilot_client, START, END)
    users = run_user_sync(db_session, unit, copilot_client, START, END)
    assert users.pages_fetched == 2
    usage_total = db_session.scalar(
        select(SpendUsageLine.amount).where(SpendUsageLine.provider == PROVIDER).limit(0)
    )
    assert usage_total is None
    stored = db_session.scalars(
        select(SpendUsageLine).where(SpendUsageLine.provider == PROVIDER)
    ).all()
    by_account: dict[str, Decimal] = {}
    for line in stored:
        by_account[line.account_id or ""] = by_account.get(line.account_id or "", Decimal("0")) + (
            line.amount or Decimal("0")
        )
    assert by_account["alice-gh"] == Decimal("2.0") + Decimal("1.2258") / 2
    assert by_account["octocat"] == Decimal("0.5") + Decimal("1.2258") / 2

    run_allocation(db_session, ORG_ID, PROVIDER, Window.for_month("2026-08"))
    people = usage_report(
        db_session,
        org_id=ORG_ID,
        provider=PROVIDER,
        window=Window.for_month("2026-08"),
        dimension="person",
    )
    alice = next(row for row in people.rows if row.label == "alice@example.com")
    assert alice.amount == (Decimal("2.0") + Decimal("1.2258") / 2).quantize(Decimal("0.00000001"))
    cost_total = sum(
        db_session.scalars(select(SpendCostLine.amount).where(SpendCostLine.provider == PROVIDER)),
        Decimal("0"),
    )
    assert cost_total == Decimal("3.7258")

    # A second run of both steps replaces the window instead of appending to it.
    run_cost_sync(db_session, unit, copilot_client, START, END)
    run_user_sync(db_session, unit, copilot_client, START, END)
    assert len(
        db_session.scalars(select(SpendUsageLine).where(SpendUsageLine.provider == PROVIDER)).all()
    ) == len(stored)


def test_login_routes_are_owner_writes(db_session: Session) -> None:
    from costura.main import app

    unit = target(db_session, ORG_ID, PROVIDER)
    db_session.commit()
    owner = TestClient(app)
    owner.headers["Authorization"] = sign_in(
        db_session, "owner@costura.example", owner_of="default"
    )
    url = f"/api/v1/orgs/default/providers/copilot/accounts/{unit.account_id}/logins"
    assert owner.get(url).json() == {"account_id": unit.account_id, "logins": {}}
    put = owner.put(url, json={"logins": {"Octocat": "octo@example.com", "gone": ""}})
    assert put.status_code == 200, put.text
    assert put.json()["logins"] == {"octocat": "octo@example.com"}
    assert owner.put(url, json={"logins": {"x": "nope"}}).status_code == 422
    other = target(db_session, ORG_ID, "cursor")
    db_session.commit()
    wrong = owner.get(f"/api/v1/orgs/default/providers/cursor/accounts/{other.account_id}/logins")
    assert wrong.status_code == 404

    member = TestClient(app)
    member.headers["Authorization"] = sign_in(
        db_session, "member@costura.example", role_in="member"
    )
    assert member.get(url).status_code == 200
    assert member.put(url, json={"logins": {}}).status_code == 403


def test_budgets_the_token_cannot_read_are_skipped_not_failed(db_session: Session) -> None:
    import httpx

    from tests.conftest import copilot_fixture_handler

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/settings/billing/budgets"):
            return httpx.Response(403, json={"message": "Must have admin rights"})
        return copilot_fixture_handler(request)

    unit = target(db_session, ORG_ID, PROVIDER)
    with GitHubBillingClient(
        token="t", org="acme", transport=httpx.MockTransport(handler), max_retries=0
    ) as client:
        _seats, budgets = run_inventory_sync(db_session, unit, client)
    assert budgets.skipped_workspaces == ["acme"]
    assert db_session.scalars(select(ProviderLimit)).all() == []
