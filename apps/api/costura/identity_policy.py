"""E-mail normalization and who may create an account with Google.

Lives apart from `costura.auth` and `costura.members` because both of those import it
and it imports neither, which keeps the identity package acyclic.

An existing user always signs in. A new address is accepted when sign-up is open, when
its domain is listed in `COSTURA_ALLOWED_EMAIL_DOMAINS`, or when a pending invitation
names that address. Production defaults to invitation-only.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from costura.config import get_settings
from costura.errors import DomainError, InvalidInput
from costura.models.invitation import OrganizationInvitation
from costura.models.user import User


def _is_pending(invitation: OrganizationInvitation, now: datetime) -> bool:
    """The same rule as `costura.members.is_pending`, restated so this module stays a leaf."""
    return (
        invitation.accepted_at is None
        and invitation.revoked_at is None
        and invitation.expires_at > now
    )


def normalize_email(email: str) -> str:
    return email.strip().lower()


def require_email(email: str, message: str | None = None) -> str:
    """The normalized address, or `InvalidInput` when it has no `@`."""
    normalized = normalize_email(email)
    if not normalized or "@" not in normalized:
        raise InvalidInput(message or f"invalid e-mail {email!r}")
    return normalized


class SignupClosed(PermissionError, DomainError):
    """A new Google account is not allowed to create a user on this instance."""

    status = 403
    code = "signup_closed"


def assert_google_signup(session: Session, email: str) -> None:
    settings = get_settings()
    normalized = normalize_email(email)
    existing = session.scalar(select(User.id).where(User.email == normalized))
    if existing is not None:
        return
    if _pending(session, normalized):
        return
    domain = normalized.partition("@")[2]
    allowed = settings.allowed_email_domains()
    if domain in allowed:
        return
    if settings.effective_sign_up == "open" and not allowed:
        return
    if allowed and domain not in allowed:
        raise SignupClosed("this e-mail domain is not allowed to sign up")
    raise SignupClosed("sign-up is by invitation on this instance")


def _pending(session: Session, email: str) -> bool:
    now = datetime.now(UTC)
    rows = session.scalars(
        select(OrganizationInvitation).where(
            OrganizationInvitation.email == email,
            OrganizationInvitation.accepted_at.is_(None),
            OrganizationInvitation.revoked_at.is_(None),
        )
    )
    return any(_is_pending(row, now) for row in rows)
