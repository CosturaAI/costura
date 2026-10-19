"""Contacts assigned by hand to a key or a workspace.

The provider inventory names nobody for many keys (OpenRouter returns no member list; an
Anthropic creator id can be gone from the members). A member of the Costura organization then
records who answers for the key or the workspace; `costura.spend.owners` reads these rows
before the inventory.
"""

from datetime import datetime
from typing import Literal, get_args

from sqlalchemy import BigInteger, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from costura.db import Base
from costura.models.checks import one_of

OwnerAssignmentKind = Literal["api_key", "workspace"]
ASSIGNMENT_KINDS: tuple[OwnerAssignmentKind, ...] = get_args(OwnerAssignmentKind)


class OwnerAssignment(Base):
    __tablename__ = "owner_assignments"
    __table_args__ = (one_of("kind", ASSIGNMENT_KINDS),)

    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    provider_account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("provider_accounts.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[OwnerAssignmentKind] = mapped_column(Text, primary_key=True)
    # The provider's id of the key or workspace, as `spend_anomalies.series_id` carries it.
    external_id: Mapped[str] = mapped_column(Text, primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    # Free text for the reader: "on-call for the gateway", "left in June, ask Ana".
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
