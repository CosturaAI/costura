"""People who sign in, their sessions, OIDC transactions, and organization memberships.

A user is identified by a lowercase e-mail. A session is an opaque bearer token whose sha256
hash is the only thing stored; the token itself travels once, in the sign-in response.
Membership carries a role (`owner`, `member` or `viewer`) per organization.
"""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from costura.db import Base

ROLES = ("owner", "member", "viewer")
IDENTITY_PROVIDERS = ("dev", "google")
# The roles that may change organization data (sync, anomaly status, owner assignments); a
# `viewer` reads and keeps only personal settings.
OPERATOR_ROLES = ("owner", "member")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_sign_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("identity_provider IN ('dev', 'google')", name="identity_provider"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # sha256 hex digest of the bearer token; the token is never stored.
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # Indexed: sign-out-everywhere deletes by user.
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Refreshed at most once per `auth.SEEN_GRANULARITY`; the idle expiry reads it.
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Immutable provenance of the identity proof that opened this session.
    identity_provider: Mapped[str] = mapped_column(Text, nullable=False, server_default="dev")


class OidcAuthorization(Base):
    """One short-lived Google authorization request, consumed before code exchange."""

    __tablename__ = "oidc_authorizations"

    state_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    nonce_hash: Mapped[str] = mapped_column(Text, nullable=False)
    code_verifier_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class OrganizationMember(Base):
    __tablename__ = "organization_members"
    __table_args__ = (CheckConstraint("role IN ('owner', 'member', 'viewer')", name="role"),)

    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Set when the member opts in to the in-product anomaly inbox for this organization;
    # anomalies detected from then on count as unread until an `anomaly_reads` row exists.
    anomaly_alerts_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
