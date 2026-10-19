"""Users and sessions: verified identity provenance and bearer-token lookup.

The token is `secrets.token_urlsafe(32)`; only its sha256 hex digest is stored, so a database
read cannot impersonate anyone. Session provenance is immutable: production writes accept a
session opened from a verified Google ID token, or a development session for the configured
operator e-mail.
"""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from costura.errors import InvalidInput
from costura.identity_policy import assert_google_signup, require_email
from costura.models import User, UserSession
from costura.models.user import IDENTITY_PROVIDERS
from costura.secrets import hash_token

SESSION_DAYS = 30
# A session unused for this long stops resolving before its absolute expiry.
IDLE_DAYS = 7
# `last_seen_at` is written at most this often, so reads do not turn into a write each.
SEEN_GRANULARITY = timedelta(hours=1)


@dataclass(frozen=True)
class SignIn:
    user: User
    token: str
    expires_at: datetime


def get_or_create_user(session: Session, email: str, name: str | None = None) -> User:
    """The user with this e-mail (lowercased), created on first sight. A given name replaces an
    absent one; it never overwrites a stored name."""
    normalized = require_email(email)
    user = session.scalar(select(User).where(User.email == normalized))
    if user is None:
        user = User(email=normalized, name=name)
        session.add(user)
        session.flush()
    elif name and not user.name:
        user.name = name
    return user


def create_session(
    session: Session,
    user: User,
    *,
    identity_provider: str,
    now: datetime | None = None,
) -> SignIn:
    if identity_provider not in IDENTITY_PROVIDERS:
        raise InvalidInput(f"unknown identity provider {identity_provider!r}")
    now = now or datetime.now(UTC)
    token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(days=SESSION_DAYS)
    session.add(
        UserSession(
            token_hash=hash_token(token),
            user_id=user.id,
            expires_at=expires_at,
            last_seen_at=now,
            identity_provider=identity_provider,
        )
    )
    user.last_sign_in_at = now
    session.flush()
    return SignIn(user=user, token=token, expires_at=expires_at)


def sign_in_dev(
    session: Session, email: str, name: str | None = None, *, now: datetime | None = None
) -> SignIn:
    """Sign in by e-mail alone: create the user when absent and open a session."""
    user = get_or_create_user(session, email, name)
    return create_session(session, user, identity_provider="dev", now=now)


def sign_in_google(
    session: Session, email: str, name: str | None = None, *, now: datetime | None = None
) -> SignIn:
    """Open a session from claims already verified by the Google OIDC verifier."""

    assert_google_signup(session, email)
    user = get_or_create_user(session, email, name)
    return create_session(session, user, identity_provider="google", now=now)


def resolve_session(session: Session, token: str, *, now: datetime | None = None) -> User | None:
    """The user behind a bearer token, or None when the token is unknown, past its absolute
    expiry or unused for `IDLE_DAYS`. A resolved token refreshes `last_seen_at` once per
    `SEEN_GRANULARITY`."""
    now = now or datetime.now(UTC)
    row = session.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if row is None or row.expires_at <= now:
        return None
    if row.last_seen_at + timedelta(days=IDLE_DAYS) <= now:
        return None
    if now - row.last_seen_at >= SEEN_GRANULARITY:
        row.last_seen_at = now
        session.flush()
    return session.get(User, row.user_id)


def resolve_session_provider(
    session: Session, token: str, *, now: datetime | None = None
) -> str | None:
    """Identity provider of a live session, or None under the normal expiry rules."""
    now = now or datetime.now(UTC)
    row = session.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if row is None or row.expires_at <= now:
        return None
    if row.last_seen_at + timedelta(days=IDLE_DAYS) <= now:
        return None
    return row.identity_provider


def sign_out(session: Session, token: str) -> bool:
    """Delete the session of `token`; False when it did not exist."""
    result = session.execute(delete(UserSession).where(UserSession.token_hash == hash_token(token)))
    session.flush()
    return result.rowcount > 0  # ty: ignore[unresolved-attribute]


def sign_out_everywhere(session: Session, user: User) -> int:
    """Delete every session of `user`, the one making the request included; the count."""
    result = session.execute(delete(UserSession).where(UserSession.user_id == user.id))
    session.flush()
    return result.rowcount  # ty: ignore[unresolved-attribute]
