"""Development sign-in, bearer sessions, sign-out and `/me`."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura import auth
from costura.config import get_settings
from costura.models import User, UserSession
from tests.conftest import OWNER_EMAIL, seed_sample, sign_in

SIGN_IN = "/api/v1/auth/dev-sign-in"
SIGN_OUT = "/api/v1/auth/sign-out"
ME = "/api/v1/me"


@pytest.fixture
def anonymous(db_session: Session) -> TestClient:
    from costura.main import app

    return TestClient(app)


def test_dev_sign_in_creates_the_user_once_and_lowercases_the_email(
    anonymous: TestClient, db_session: Session
) -> None:
    first = anonymous.post(SIGN_IN, json={"email": "Ana@Example.COM", "name": "Ana"})
    assert first.status_code == 201
    body = first.json()
    assert body["user"] == {"email": "ana@example.com", "name": "Ana"}
    assert len(body["token"]) >= 43
    expires = datetime.fromisoformat(body["expires_at"])
    assert timedelta(days=29) < expires - datetime.now(UTC) <= timedelta(days=30)

    second = anonymous.post(SIGN_IN, json={"email": "  ana@example.com "})
    assert second.status_code == 201
    assert second.json()["token"] != body["token"]
    assert second.json()["user"]["name"] == "Ana"

    users = db_session.scalars(select(User)).all()
    assert [u.email for u in users] == ["ana@example.com"]
    assert users[0].last_sign_in_at is not None
    # Only the hash is stored; the token itself is in neither row.
    hashes = db_session.scalars(select(UserSession.token_hash)).all()
    assert len(hashes) == 2 and body["token"] not in hashes
    assert auth.hash_token(body["token"]) in hashes
    assert auth.resolve_session_provider(db_session, body["token"]) == "dev"

    assert anonymous.post(SIGN_IN, json={"email": "not-an-email"}).status_code == 422


def test_requests_without_a_valid_session_answer_401(
    anonymous: TestClient, db_session: Session
) -> None:
    assert anonymous.get(ME).status_code == 401
    assert anonymous.get("/api/v1/orgs").status_code == 401
    assert anonymous.get("/api/v1/orgs/default/setup").status_code == 401
    assert anonymous.get(ME, headers={"Authorization": "Bearer nope"}).status_code == 401
    assert anonymous.get(ME, headers={"Authorization": "Basic abc"}).status_code == 401
    rejected = anonymous.get(ME, headers={"Authorization": "Bearer nope"})
    assert rejected.headers["www-authenticate"] == "Bearer"

    signed = auth.sign_in_dev(
        db_session, "old@example.com", now=datetime.now(UTC) - timedelta(days=31)
    )
    expired = anonymous.get(ME, headers={"Authorization": f"Bearer {signed.token}"})
    assert expired.status_code == 401
    assert auth.resolve_session(db_session, signed.token) is None

    # Health stays public.
    assert anonymous.get("/health").status_code == 200


def test_sign_out_invalidates_the_session(anonymous: TestClient, db_session: Session) -> None:
    token = anonymous.post(SIGN_IN, json={"email": "ana@example.com"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert anonymous.get(ME, headers=headers).status_code == 200

    assert anonymous.post(SIGN_OUT, headers=headers).status_code == 204
    assert anonymous.get(ME, headers=headers).status_code == 401
    assert anonymous.post(SIGN_OUT, headers=headers).status_code == 401
    assert db_session.scalar(select(func.count()).select_from(UserSession)) == 0


def test_an_idle_session_expires_and_a_used_one_is_refreshed_hourly(
    db_session: Session,
) -> None:
    start = datetime.now(UTC) - timedelta(days=10)
    signed = auth.sign_in_dev(db_session, "idle@example.com", now=start)
    row = db_session.scalar(select(UserSession).where(UserSession.user_id == signed.user.id))
    assert row is not None and row.last_seen_at == start

    # A read within the hour does not write; one past the hour moves the mark.
    assert auth.resolve_session(db_session, signed.token, now=start + timedelta(minutes=30))
    assert row.last_seen_at == start
    used = start + timedelta(days=3)
    assert auth.resolve_session(db_session, signed.token, now=used)
    assert row.last_seen_at == used
    # Seven days without a request end the session, well before the 30-day absolute expiry.
    assert auth.resolve_session(db_session, signed.token, now=used + timedelta(days=6))
    assert auth.resolve_session(db_session, signed.token, now=used + timedelta(days=13)) is None


def test_sign_out_everywhere_deletes_every_session_of_the_user(
    anonymous: TestClient, db_session: Session
) -> None:
    first = anonymous.post(SIGN_IN, json={"email": "ana@example.com"}).json()["token"]
    second = anonymous.post(SIGN_IN, json={"email": "ana@example.com"}).json()["token"]
    other = anonymous.post(SIGN_IN, json={"email": "bruno@example.com"}).json()["token"]
    headers = {"Authorization": f"Bearer {first}"}

    assert anonymous.delete("/api/v1/auth/sessions", headers=headers).status_code == 204
    assert anonymous.get(ME, headers=headers).status_code == 401
    assert anonymous.get(ME, headers={"Authorization": f"Bearer {second}"}).status_code == 401
    assert anonymous.get(ME, headers={"Authorization": f"Bearer {other}"}).status_code == 200
    assert anonymous.delete("/api/v1/auth/sessions").status_code == 401


def test_me_lists_memberships_and_the_demo_org(client: TestClient, db_session: Session) -> None:
    body = client.get(ME).json()
    body["organizations"] = [o | {"created_at": None} for o in body["organizations"]]
    assert body == {
        "user": {"email": OWNER_EMAIL, "name": None},
        "organizations": [
            {
                "slug": "default",
                "name": "Default",
                "is_demo": False,
                "role": "owner",
                "created_at": None,
            }
        ],
        "demo_org": None,
        "invitations": [],
    }

    # The public sample organization is named by slug only; it belongs to nobody's list.
    seed_sample(db_session)
    body = client.get(ME).json()
    assert body["demo_org"] == "demo"
    assert [(o["slug"], o["role"], o["is_demo"]) for o in body["organizations"]] == [
        ("default", "owner", False),
    ]


def test_dev_sign_in_refused_in_production_and_from_a_proxy(
    anonymous: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    forwarded = anonymous.post(
        SIGN_IN, json={"email": "ana@example.com"}, headers={"X-Forwarded-For": "10.0.0.7"}
    )
    assert forwarded.status_code == 403

    monkeypatch.setattr(get_settings(), "costura_env", "production")
    refused = anonymous.post(SIGN_IN, json={"email": "ana@example.com"})
    assert refused.status_code == 403
    monkeypatch.setattr(get_settings(), "costura_env", "staging")
    unsupported = anonymous.post(SIGN_IN, json={"email": "ana@example.com"})
    assert unsupported.status_code == 403


def _enable_operator(monkeypatch: pytest.MonkeyPatch) -> str:
    secret = "s" * 24
    monkeypatch.setattr(get_settings(), "costura_env", "production")
    monkeypatch.setattr(get_settings(), "costura_operator_email", "ops@example.com")
    monkeypatch.setattr(get_settings(), "costura_operator_secret", SecretStr(secret))
    return secret


def test_operator_sign_in_opens_a_production_session_off_loopback(
    anonymous: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from costura import main
    from costura.main import app

    secret = _enable_operator(monkeypatch)
    monkeypatch.setattr(main, "require_production_config", lambda _settings: None)
    status = anonymous.get("/api/v1/auth/google")
    assert status.json()["operator_sign_in_enabled"] is True
    assert status.json()["dev_sign_in_enabled"] is False

    with TestClient(app, client=("192.0.2.10", 50000)) as remote:
        refused = remote.post(
            SIGN_IN,
            json={"email": "ops@example.com", "secret": "wrong-secret-value"},
            headers={"X-Forwarded-For": "203.0.113.8"},
        )
        assert refused.status_code == 403
        other = remote.post(
            SIGN_IN,
            json={"email": "other@example.com", "secret": secret},
        )
        assert other.status_code == 403

        signed = remote.post(
            SIGN_IN,
            json={"email": "Ops@Example.com", "secret": secret},
            headers={"X-Forwarded-For": "203.0.113.8"},
        )
        assert signed.status_code == 201
        token = signed.json()["token"]
        assert auth.resolve_session_provider(db_session, token) == "dev"
        created = remote.post(
            "/api/v1/orgs",
            json={"name": "Operator", "slug": "operator-org"},
            headers={"Authorization": f"Bearer {token}", "X-Forwarded-For": "203.0.113.8"},
        )
        assert created.status_code == 201

        stranger = auth.sign_in_dev(db_session, "stranger@example.com")
        db_session.commit()
        denied = remote.post(
            "/api/v1/orgs",
            json={"name": "Stranger", "slug": "stranger-org"},
            headers={"Authorization": f"Bearer {stranger.token}"},
        )
        assert denied.status_code == 403


@pytest.mark.parametrize("environment", ["development", "test"])
def test_dev_sign_in_is_explicitly_allowed_on_loopback(
    anonymous: TestClient, monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    monkeypatch.setattr(get_settings(), "costura_env", environment)

    response = anonymous.post(SIGN_IN, json={"email": f"{environment}@example.com"})

    assert response.status_code == 201


@pytest.mark.parametrize("forwarded", ["127.0.0.1", "::1", "::ffff:127.0.0.1", "127.0.0.1, ::1"])
def test_dev_sign_in_accepts_the_local_web_server_forwarding_loopback(
    anonymous: TestClient, forwarded: str
) -> None:
    response = anonymous.post(
        SIGN_IN, json={"email": "web@example.com"}, headers={"X-Forwarded-For": forwarded}
    )

    assert response.status_code == 201


def test_dev_sign_in_refuses_a_loopback_peer_forwarding_a_remote_client(
    anonymous: TestClient,
) -> None:
    response = anonymous.post(
        SIGN_IN,
        json={"email": "web@example.com"},
        headers={"X-Forwarded-For": "127.0.0.1, 192.168.1.20"},
    )

    assert response.status_code == 403


def test_sign_in_helper_grants_ownership(db_session: Session) -> None:
    from costura.orgs import get_org
    from costura.spend.membership import membership

    header = sign_in(db_session, "Second@Example.com", owner_of="default")
    user = db_session.scalar(select(User).where(User.email == "second@example.com"))
    assert header.startswith("Bearer ") and user is not None
    assert membership(db_session, get_org(db_session, "default").id, user.id).role == "owner"
