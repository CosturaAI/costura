"""Invitations: an owner names an address, the person who owns that address claims the link
. No e-mail leaves the instance; the link is the whole delivery mechanism."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from costura import members
from costura.api.deps import OWNER_ONLY
from costura.config import get_settings
from costura.models import OrganizationInvitation
from costura.models.invitation import INVITATION_DAYS
from tests.conftest import MEMBER_EMAIL, sign_in

ORG = "/api/v1/orgs/default"
INVITEE = "newcomer@example.com"


def _client(auth: str) -> TestClient:
    from costura.main import app

    return TestClient(app, headers={"Authorization": auth})


def _token(url: str) -> str:
    return url.rsplit("/", 1)[1]


def test_an_owner_invites_and_the_response_carries_the_link_once(
    db_session: Session, client: TestClient
) -> None:
    created = client.post(
        f"{ORG}/invitations", json={"email": "Newcomer@Example.com ", "role": "member"}
    )
    assert created.status_code == 201
    body = created.json()
    # The address is stored lowercased, so one person cannot hold two pending invitations.
    assert body["email"] == INVITEE
    assert body["role"] == "member"
    assert body["status"] == "pending"
    assert body["url"].endswith(f"/join/{_token(body['url'])}")
    assert body["url"].startswith(get_settings().costura_web_origin)
    expires = datetime.fromisoformat(body["expires_at"])
    assert timedelta(days=INVITATION_DAYS) - (expires - datetime.now(UTC)) < timedelta(minutes=1)

    # Only the hash is stored; the token itself is not in the database.
    row = db_session.scalar(select(OrganizationInvitation))
    assert row is not None
    assert row.token_hash == members.hash_token(_token(body["url"]))

    # The list route never repeats the link.
    listed = client.get(f"{ORG}/invitations").json()
    assert [(row["email"], row["role"], row["url"]) for row in listed] == [
        (INVITEE, "member", None)
    ]


def test_inviting_the_same_address_twice_or_an_existing_member_is_refused(
    db_session: Session, client: TestClient, member_auth: str
) -> None:
    assert (
        client.post(f"{ORG}/invitations", json={"email": INVITEE, "role": "viewer"}).status_code
        == 201
    )
    again = client.post(f"{ORG}/invitations", json={"email": INVITEE, "role": "owner"})
    assert again.status_code == 409
    assert "pending invitation" in again.json()["detail"]

    member = client.post(f"{ORG}/invitations", json={"email": MEMBER_EMAIL, "role": "member"})
    assert member.status_code == 409
    assert "already a member" in member.json()["detail"]

    assert (
        client.post(
            f"{ORG}/invitations", json={"email": "not-an-email", "role": "member"}
        ).status_code
        == 422
    )
    assert (
        client.post(f"{ORG}/invitations", json={"email": INVITEE, "role": "auditor"}).status_code
        == 422
    )


def test_members_and_viewers_cannot_see_or_send_invitations(
    db_session: Session, client: TestClient, member_auth: str, viewer_auth: str
) -> None:
    """The list names people outside the organization, so it is owner-only in both
    directions (the Cursor forum thread of Aug 2026 asks for exactly this)."""
    for auth in (member_auth, viewer_auth):
        caller = _client(auth)
        sent = caller.post(f"{ORG}/invitations", json={"email": INVITEE, "role": "member"})
        assert sent.status_code == 403
        assert sent.json()["detail"] == OWNER_ONLY
        assert caller.get(f"{ORG}/invitations").status_code == 403


def test_the_invited_person_sees_the_invitation_on_me_and_accepts_it(
    db_session: Session, client: TestClient
) -> None:
    created = client.post(f"{ORG}/invitations", json={"email": INVITEE, "role": "viewer"}).json()
    invitee = _client(sign_in(db_session, INVITEE))

    me = invitee.get("/api/v1/me").json()
    assert me["organizations"] == []
    assert [(i["organization"]["slug"], i["role"], i["invited_by"]) for i in me["invitations"]] == [
        ("default", "viewer", "owner@example.com")
    ]

    accepted = invitee.post(f"/api/v1/invitations/{created['id']}/accept")
    assert accepted.status_code == 200
    assert accepted.json() == {
        "slug": "default",
        "name": "Default",
        "is_demo": False,
        "role": "viewer",
        "created_at": accepted.json()["created_at"],
    }
    # The invitation is settled: it leaves `/me` and the owner's list, and cannot be reused.
    assert invitee.get("/api/v1/me").json()["invitations"] == []
    assert client.get(f"{ORG}/invitations").json() == []
    assert invitee.post(f"/api/v1/invitations/{created['id']}/accept").status_code == 410
    assert [row["email"] for row in invitee.get(f"{ORG}/members").json()] == [
        "owner@example.com",
        INVITEE,
    ]


def test_the_link_token_claims_the_same_invitation(db_session: Session, client: TestClient) -> None:
    created = client.post(f"{ORG}/invitations", json={"email": INVITEE, "role": "member"}).json()
    invitee = _client(sign_in(db_session, INVITEE))

    claimed = invitee.post("/api/v1/invitations/claim", json={"token": _token(created["url"])})
    assert claimed.status_code == 200
    assert claimed.json()["role"] == "member"
    assert (
        invitee.post(
            "/api/v1/invitations/claim", json={"token": _token(created["url"])}
        ).status_code
        == 410
    )
    assert invitee.post("/api/v1/invitations/claim", json={"token": "made-up"}).status_code == 410


def test_the_link_only_works_for_the_address_it_names(
    db_session: Session, client: TestClient
) -> None:
    """The link is safe to paste into a chat: someone else signed in cannot use it."""
    created = client.post(f"{ORG}/invitations", json={"email": INVITEE, "role": "member"}).json()
    stranger = _client(sign_in(db_session, "stranger@example.com"))

    refused = stranger.post("/api/v1/invitations/claim", json={"token": _token(created["url"])})
    assert refused.status_code == 410
    assert (
        refused.json()["detail"] == "this invitation is no longer valid; ask an owner for a new one"
    )
    assert INVITEE not in refused.text
    assert stranger.post(f"/api/v1/invitations/{created['id']}/accept").status_code == 410
    assert stranger.get("/api/v1/me").json()["organizations"] == []


def test_a_revoked_invitation_stops_working_and_frees_the_address(
    db_session: Session, client: TestClient
) -> None:
    created = client.post(f"{ORG}/invitations", json={"email": INVITEE, "role": "member"}).json()
    assert client.delete(f"{ORG}/invitations/{created['id']}").status_code == 204
    assert client.get(f"{ORG}/invitations").json() == []

    invitee = _client(sign_in(db_session, INVITEE))
    assert invitee.get("/api/v1/me").json()["invitations"] == []
    assert (
        invitee.post(
            "/api/v1/invitations/claim", json={"token": _token(created["url"])}
        ).status_code
        == 410
    )

    # A revoked invitation does not hold the address: the owner can invite again.
    again = client.post(f"{ORG}/invitations", json={"email": INVITEE, "role": "viewer"})
    assert again.status_code == 201
    assert client.delete(f"{ORG}/invitations/{created['id']}").status_code == 204


def test_an_accepted_invitation_cannot_be_revoked(db_session: Session, client: TestClient) -> None:
    """Same boundary as the OpenAI platform: what happened stays; remove the member instead."""
    created = client.post(f"{ORG}/invitations", json={"email": INVITEE, "role": "member"}).json()
    invitee = _client(sign_in(db_session, INVITEE))
    assert invitee.post(f"/api/v1/invitations/{created['id']}/accept").status_code == 200
    assert client.delete(f"{ORG}/invitations/{created['id']}").status_code == 404


def test_an_expired_invitation_is_listed_as_expired_and_refuses_the_claim(
    db_session: Session, client: TestClient
) -> None:
    created = client.post(f"{ORG}/invitations", json={"email": INVITEE, "role": "member"}).json()
    row = db_session.get(OrganizationInvitation, created["id"])
    assert row is not None
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()

    listed = client.get(f"{ORG}/invitations").json()
    assert [row["status"] for row in listed] == ["expired"]
    invitee = _client(sign_in(db_session, INVITEE))
    assert invitee.get("/api/v1/me").json()["invitations"] == []
    assert (
        invitee.post(
            "/api/v1/invitations/claim", json={"token": _token(created["url"])}
        ).status_code
        == 410
    )

    # Re-inviting the same address replaces the expired row rather than colliding with it.
    again = client.post(f"{ORG}/invitations", json={"email": INVITEE, "role": "member"})
    assert again.status_code == 201
    assert [row["status"] for row in client.get(f"{ORG}/invitations").json()] == ["pending"]


def test_accepting_keeps_the_higher_of_the_two_roles(
    db_session: Session, client: TestClient
) -> None:
    """An owner invited as a viewer stays an owner; the invitation only ever adds access."""
    owner_invite = client.post(
        f"{ORG}/invitations", json={"email": INVITEE, "role": "owner"}
    ).json()
    invitee = _client(sign_in(db_session, INVITEE))
    assert (
        invitee.post(f"/api/v1/invitations/{owner_invite['id']}/accept").json()["role"] == "owner"
    )

    viewer_invite = client.post(f"{ORG}/invitations", json={"email": INVITEE, "role": "viewer"})
    assert viewer_invite.status_code == 409
    assert "already a member" in viewer_invite.json()["detail"]


def test_the_join_url_follows_the_public_web_url_when_set(
    db_session: Session, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The browser-facing origin wins over the dev one."""
    monkeypatch.setattr(get_settings(), "costura_web_public_url", "https://costura.example.com/")
    created = client.post(f"{ORG}/invitations", json={"email": INVITEE, "role": "member"}).json()
    assert created["url"].startswith("https://costura.example.com/join/")


def test_a_reset_keeps_the_pending_invitations(db_session: Session, client: TestClient) -> None:
    """A reset returns the organization to the state before its first key; who may open it,
    invitations included, is not provider data."""
    client.post(f"{ORG}/invitations", json={"email": INVITEE, "role": "member"})
    assert client.post(f"{ORG}/setup/reset").status_code == 200
    assert [row["email"] for row in client.get(f"{ORG}/invitations").json()] == [INVITEE]
