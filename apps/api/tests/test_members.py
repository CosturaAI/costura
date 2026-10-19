"""Roles and membership changes: who may do what, and the rule that an organization never
runs out of owners."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from costura import members
from costura.api.deps import MEMBER_ONLY, OWNER_ONLY
from costura.models import User
from costura.orgs import InvalidRole, create_org, get_org
from costura.spend.membership import list_members
from tests.conftest import MEMBER_EMAIL, OWNER_EMAIL, VIEWER_EMAIL, sign_in
from tests.support.orgs import add_member

ORG = "/api/v1/orgs/default"


def _client(auth: str) -> TestClient:
    from costura.main import app

    return TestClient(app, headers={"Authorization": auth})


def _user_id(session: Session, email: str) -> int:
    user = session.scalar(select(User).where(User.email == email))
    assert user is not None
    return user.id


def test_members_are_listed_owners_first_then_members_then_viewers(
    db_session: Session, client: TestClient, member_auth: str, viewer_auth: str
) -> None:
    """The list follows the permission ladder, not the alphabet: sorting `role` as text would
    read member, owner, viewer."""
    rows = client.get(f"{ORG}/members").json()
    assert [(row["email"], row["role"]) for row in rows] == [
        (OWNER_EMAIL, "owner"),
        (MEMBER_EMAIL, "member"),
        (VIEWER_EMAIL, "viewer"),
    ]
    assert [row["is_you"] for row in rows] == [True, False, False]
    assert all(row["id"] > 0 for row in rows)
    # The service behind it orders the same way.
    assert [member.role for _, member in list_members(db_session, 1)] == [
        "owner",
        "member",
        "viewer",
    ]


def test_a_viewer_reads_everything_and_changes_nothing(
    db_session: Session, client: TestClient, viewer_auth: str
) -> None:
    """A viewer opens every page and keeps their own settings; every write that changes what
    the organization holds answers 403 with the same sentence."""
    viewer = _client(viewer_auth)
    assert viewer.get(f"{ORG}/providers/all/months/2026-09/summary").status_code == 200
    assert viewer.get(f"{ORG}/members").status_code == 200

    denied = [
        viewer.post(f"{ORG}/providers/anthropic/sync"),
        viewer.post(f"{ORG}/setup/dismiss"),
        viewer.put(
            f"{ORG}/providers/anthropic/owners/api_key/key_1",
            json={"email": "oncall@example.com"},
        ),
        viewer.delete(f"{ORG}/providers/anthropic/owners/api_key/key_1"),
    ]
    assert [r.status_code for r in denied] == [403] * 4
    assert {r.json()["detail"] for r in denied} == {MEMBER_ONLY}

    # The personal writes stay open: the alerts opt-in is the viewer's own setting.
    assert viewer.put(f"{ORG}/alerts/settings", json={"opted_in": True}).status_code == 200


def test_only_an_owner_changes_a_role(
    db_session: Session, client: TestClient, member_auth: str, viewer_auth: str
) -> None:
    viewer_id = _user_id(db_session, VIEWER_EMAIL)
    promoted = client.patch(f"{ORG}/members/{viewer_id}", json={"role": "member"})
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "member"

    refused = _client(member_auth).patch(f"{ORG}/members/{viewer_id}", json={"role": "owner"})
    assert refused.status_code == 403
    assert refused.json()["detail"] == OWNER_ONLY

    unknown = client.patch(f"{ORG}/members/999999", json={"role": "member"})
    assert unknown.status_code == 404
    assert client.patch(f"{ORG}/members/{viewer_id}", json={"role": "auditor"}).status_code == 422


def test_the_last_owner_cannot_be_demoted_removed_or_leave(
    db_session: Session, client: TestClient, member_auth: str
) -> None:
    """Without this rule an organization reaches a state where nobody can manage its keys."""
    owner_id = _user_id(db_session, OWNER_EMAIL)
    demoted = client.patch(f"{ORG}/members/{owner_id}", json={"role": "member"})
    assert demoted.status_code == 409
    assert "last owner" in demoted.json()["detail"]
    assert client.delete(f"{ORG}/members/{owner_id}").status_code == 409

    # With a second owner in place both go through.
    member_id = _user_id(db_session, MEMBER_EMAIL)
    assert client.patch(f"{ORG}/members/{member_id}", json={"role": "owner"}).status_code == 200
    assert client.patch(f"{ORG}/members/{owner_id}", json={"role": "member"}).status_code == 200
    db_session.expire_all()
    assert members.owner_count(db_session, 1) == 1


def test_an_owner_removes_a_member_and_anyone_leaves_on_their_own(
    db_session: Session, client: TestClient, member_auth: str, viewer_auth: str
) -> None:
    viewer_id = _user_id(db_session, VIEWER_EMAIL)
    member_id = _user_id(db_session, MEMBER_EMAIL)
    member = _client(member_auth)

    # A member cannot remove someone else.
    refused = member.delete(f"{ORG}/members/{viewer_id}")
    assert refused.status_code == 403
    assert refused.json()["detail"] == OWNER_ONLY

    # ... but leaves on their own, and the session still works elsewhere.
    assert member.delete(f"{ORG}/members/{member_id}").status_code == 204
    assert member.get("/api/v1/me").status_code == 200
    assert member.get(f"{ORG}/members").status_code == 404

    assert client.delete(f"{ORG}/members/{viewer_id}").status_code == 204
    assert [row["email"] for row in client.get(f"{ORG}/members").json()] == [OWNER_EMAIL]
    # Removing twice is a 404, not a silent success.
    assert client.delete(f"{ORG}/members/{viewer_id}").status_code == 404


def test_removing_a_member_keeps_the_account_and_its_other_organizations(
    db_session: Session, client: TestClient, member_auth: str
) -> None:
    member_id = _user_id(db_session, MEMBER_EMAIL)
    other = create_org(db_session, "other", "Other", owner=db_session.get(User, member_id))
    db_session.commit()
    assert client.delete(f"{ORG}/members/{member_id}").status_code == 204

    me = _client(member_auth).get("/api/v1/me").json()
    assert [org["slug"] for org in me["organizations"]] == [other.slug]
    assert me["user"]["email"] == MEMBER_EMAIL


def test_the_service_refuses_an_unknown_role_and_an_unknown_member(db_session: Session) -> None:
    org = get_org(db_session, "default")
    sign_in(db_session, "someone@example.com")
    user_id = _user_id(db_session, "someone@example.com")
    with pytest.raises(InvalidRole):
        members.set_role(db_session, org, user_id, "auditor")
    with pytest.raises(members.UnknownMember):
        members.set_role(db_session, org, user_id, "member")

    add_member(db_session, org, db_session.get(User, user_id), "viewer")
    assert members.set_role(db_session, org, user_id, "viewer").role == "viewer"
