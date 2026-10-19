"""The audit trail: which writes record an event, with whom and which request, that no key
material reaches it, that only owners read it, and that a reset or a deletion keeps it."""

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from costura import auth, delivery
from costura.config import get_settings
from costura.models import AuditEvent, Organization
from costura.orgs import get_org
from tests.conftest import ORG_ID
from tests.support.orgs import add_member
from tests.test_api_setup import fixture_transport, secret_key  # noqa: F401

AUDIT = "/api/v1/orgs/default/audit"
KEY = "sk-ant-admin01-audit-trail-key-0001"


def _events(db_session: Session) -> list[AuditEvent]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(AuditEvent).where(AuditEvent.organization_id == ORG_ID).order_by(AuditEvent.id)
        )
    )


@pytest.mark.usefixtures("secret_key", "fixture_transport")
def test_key_writes_record_the_actor_and_request_but_never_the_key(
    client: TestClient, db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="costura.audit")
    base = "/api/v1/orgs/default/providers/anthropic"
    connected = client.put(
        f"{base}/connection", json={"admin_key": KEY}, headers={"X-Request-ID": "req-audit-1"}
    )
    assert connected.status_code == 200, connected.text
    assert client.delete(f"{base}/connection").status_code == 200

    events = _events(db_session)
    assert [e.event for e in events] == ["provider_key_connected", "provider_key_removed"]
    first = events[0]
    assert first.actor_email == "owner@example.com" and first.actor_user_id is not None
    assert first.request_id == "req-audit-1"
    assert first.target is not None and first.target.startswith("anthropic:")
    stored = " ".join(f"{e.target} {e.details}" for e in events)
    assert KEY not in stored and KEY[-4:] not in stored
    assert KEY not in caplog.text
    trail = client.get(AUDIT).json()
    assert trail["total"] == 2 and trail["events"][0]["event"] == "provider_key_removed"
    assert KEY not in str(trail)


def test_roles_invitations_and_triage_are_recorded(client: TestClient, db_session: Session) -> None:
    other = auth.sign_in_dev(db_session, "member@example.com")
    add_member(db_session, get_org(db_session, "default"), other.user, "member")
    db_session.commit()
    org = "/api/v1/orgs/default"
    assert (
        client.patch(f"{org}/members/{other.user.id}", json={"role": "viewer"}).status_code == 200
    )
    invited = client.post(f"{org}/invitations", json={"email": "new@example.com", "role": "member"})
    assert invited.status_code == 201
    assert client.delete(f"{org}/invitations/{invited.json()['id']}").status_code == 204
    assert client.delete(f"{org}/members/{other.user.id}").status_code == 204
    assert client.patch(org, json={"name": "Renamed"}).status_code == 200

    events = _events(db_session)
    assert [e.event for e in events] == [
        "member_role_changed",
        "invitation_created",
        "invitation_revoked",
        "member_removed",
        "organization_renamed",
    ]
    assert events[0].details == {"role": "viewer"}
    assert events[0].target == f"user:{other.user.id}"
    assert "new@example.com" not in str([e.details for e in events])


def test_only_owners_read_the_trail(client: TestClient, member_auth: str) -> None:
    from costura.main import app

    as_member = TestClient(app, headers={"Authorization": member_auth})
    assert as_member.get(AUDIT).status_code == 403
    assert TestClient(app).get(AUDIT).status_code == 401
    assert client.get(AUDIT, params={"limit": 501}).status_code == 422


@pytest.mark.usefixtures("secret_key")
def test_a_reset_and_a_deletion_keep_the_trail(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "costura_webhook_hosts", "hooks.slack.com")
    delivery.save_destination(db_session, get_settings(), ORG_ID, "https://hooks.slack.com/x")
    db_session.commit()
    assert client.post("/api/v1/orgs/default/setup/reset").status_code == 200
    deleted = client.request("DELETE", "/api/v1/orgs/default", json={"slug": "default"})
    assert deleted.status_code == 204, deleted.text

    db_session.expire_all()
    assert db_session.get(Organization, ORG_ID) is None
    events = [e.event for e in _events(db_session)]
    assert events == ["organization_reset", "organization_deleted"]
