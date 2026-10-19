from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from costura import credit_prices
from costura.main import app
from costura.models import ProviderAccount
from tests.conftest import ORG_ID, target


def test_codex_connection_requires_workspace_id(client: TestClient) -> None:
    response = client.put(
        "/api/v1/orgs/default/providers/codex/connection",
        json={"admin_key": "sk-admin-redacted"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "workspace_id is required for Codex"


def test_credit_price_routes_allow_viewers_to_read_and_operators_to_write(
    db_session: Session,
    client: TestClient,
    member_auth: str,
    viewer_auth: str,
) -> None:
    unit = target(db_session, ORG_ID, "codex")
    account = db_session.get(ProviderAccount, unit.account_id)
    assert account is not None
    account.external_id = "11111111-2222-4333-8444-555555555555"
    db_session.commit()
    path = f"/api/v1/orgs/default/accounts/{unit.account_id}/credit-prices"
    today = datetime.now(UTC).date()

    with TestClient(app, headers={"Authorization": viewer_auth}) as viewer:
        assert viewer.get(path).status_code == 200
        assert (
            viewer.post(
                path,
                json={"effective_from": today.isoformat(), "price_per_credit": "0.08"},
            ).status_code
            == 403
        )

    with TestClient(app, headers={"Authorization": member_auth}) as member:
        created = member.post(
            path,
            json={"effective_from": today.isoformat(), "price_per_credit": "0.08"},
        )
    assert created.status_code == 201
    body = created.json()
    assert body["price_per_credit"] == "0.08000000"
    assert body["created_by"] is not None

    listed = client.get(path)
    assert listed.status_code == 200
    assert listed.json() == [body]
    assert (
        client.post(
            path,
            json={"effective_from": today.isoformat(), "price_per_credit": "0.09"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            path,
            json={
                "effective_from": (today + timedelta(days=400)).isoformat(),
                "price_per_credit": "0.09",
            },
        ).status_code
        == 422
    )

    deleted = client.delete(f"{path}/{body['id']}")
    assert deleted.status_code == 204
    assert client.get(path).json() == []


def test_credit_prices_reject_non_codex_accounts(db_session: Session, client: TestClient) -> None:
    account = target(db_session, ORG_ID, "openai")
    response = client.get(f"/api/v1/orgs/default/accounts/{account.account_id}/credit-prices")
    assert response.status_code == 422


def test_credit_price_horizon_is_thirteen_calendar_months(db_session: Session) -> None:
    unit = target(db_session, ORG_ID, "codex")
    account = db_session.get(ProviderAccount, unit.account_id)
    assert account is not None
    account.external_id = "11111111-2222-4333-8444-555555555555"
    today = date(2026, 1, 31)

    earliest, latest = credit_prices.date_horizon(today)
    assert earliest == date(2024, 12, 31)
    assert latest == date(2027, 2, 28)
    credit_prices.create_price(
        db_session,
        ORG_ID,
        unit.account_id,
        effective_from=latest,
        price_per_credit=Decimal("0.08"),
        created_by=None,
        today=today,
    )
