"""Sign-up policy at the Google identity boundary."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from costura.config import get_settings
from costura.identity_policy import SignupClosed, assert_google_signup, normalize_email
from costura.models.invitation import OrganizationInvitation
from costura.models.user import User


def invitation(org_id: int, email: str, *, expires_at: datetime) -> OrganizationInvitation:
    return OrganizationInvitation(
        organization_id=org_id,
        email=email,
        role="member",
        token_hash=f"token-{email}-{expires_at.timestamp()}",
        expires_at=expires_at,
    )


def test_normalize_email_strips_and_lowercases() -> None:
    assert normalize_email("  Person@Example.COM ") == "person@example.com"


def test_existing_user_always_signs_in(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "costura_sign_up", "invite_only")
    monkeypatch.setattr(settings, "costura_allowed_email_domains", "")
    db_session.add(User(email="existing@example.com"))
    db_session.commit()

    assert_google_signup(db_session, " EXISTING@example.com ")


def test_open_signup_accepts_when_there_is_no_allowlist(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "costura_sign_up", "open")
    monkeypatch.setattr(settings, "costura_allowed_email_domains", "")

    assert_google_signup(db_session, "new@anywhere.example")


def test_allowlist_accepts_only_the_named_domain(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "costura_sign_up", "open")
    monkeypatch.setattr(settings, "costura_allowed_email_domains", " Example.COM, other.test ")

    assert_google_signup(db_session, "person@example.com")
    with pytest.raises(SignupClosed, match="domain is not allowed"):
        assert_google_signup(db_session, "person@outside.test")


def test_invitation_allows_signup_on_closed_instance(
    db_session: Session, org_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "costura_sign_up", "invite_only")
    monkeypatch.setattr(settings, "costura_allowed_email_domains", "")
    row = invitation(
        org_id,
        "invited@example.com",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(row)
    db_session.commit()

    assert_google_signup(db_session, "invited@example.com")


@pytest.mark.parametrize("state", ["expired", "revoked", "accepted"])
def test_settled_invitation_does_not_allow_signup(
    db_session: Session,
    org_id: int,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "costura_sign_up", "invite_only")
    monkeypatch.setattr(settings, "costura_allowed_email_domains", "")
    now = datetime.now(UTC)
    row = invitation(org_id, f"{state}@example.com", expires_at=now + timedelta(hours=1))
    if state == "expired":
        row.expires_at = now - timedelta(seconds=1)
    elif state == "revoked":
        row.revoked_at = now
    else:
        row.accepted_at = now
    db_session.add(row)
    db_session.commit()

    with pytest.raises(SignupClosed, match="by invitation"):
        assert_google_signup(db_session, row.email)
