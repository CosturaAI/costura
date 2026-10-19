"""API keys a member marked as one person's own.

Provider inventory names who created a key, not who spends through it, so the `person`
dimension treats an API key as a service key unless Anthropic created it for a Claude Code
session. A row here says the key's spend belongs to one e-mail; `costura.spend.inventory`
reads it before that rule.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from costura.db import Base


class PersonalKeyAssignment(Base):
    __tablename__ = "personal_key_assignments"

    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    # The provider's id of the key, as `spend_usage_lines.api_key_id` carries it.
    api_key_id: Mapped[str] = mapped_column(Text, primary_key=True)
    # Lowercased; a `kind = user` address in the organization's provider inventory.
    email: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
