"""Invitation of one e-mail address to one organization.

An invitation is bound to the address an owner typed: the person who claims it must be signed
in with that e-mail, so the link is not a bearer credential for anyone who receives it. Only
the sha256 hash of the token is stored, like a session; the token travels once, in the
response that created the invitation. A pending invitation is one with neither `accepted_at`
nor `revoked_at` and an `expires_at` in the future; the partial unique index allows one
pending invitation per address and any number of settled ones.
"""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from costura.db import Base

# Days a pending invitation stays claimable. Anthropic's console expires invitations after 21
# days; two weeks is enough for a workday cycle and keeps a forgotten address short-lived.
INVITATION_DAYS = 14


class OrganizationInvitation(Base):
    __tablename__ = "organization_invitations"
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'member', 'viewer')", name="role"),
        Index(
            "uq_organization_invitations_pending",
            "organization_id",
            "email",
            unique=True,
            postgresql_where="accepted_at IS NULL AND revoked_at IS NULL",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # Lowercased at write time; the claim compares it with the signed-in user's e-mail.
    email: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    # sha256 hex digest of the link token; the token is never stored.
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    invited_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
