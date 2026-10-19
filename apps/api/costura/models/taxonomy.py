"""Observed provider model ids."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from costura.db import Base


class ProviderModelSeen(Base):
    __tablename__ = "provider_models_seen"
    __table_args__ = (
        CheckConstraint("char_length(provider) BETWEEN 1 AND 64", name="provider_length"),
        CheckConstraint("char_length(model) BETWEEN 1 AND 255", name="model_length"),
        CheckConstraint("last_amount_30d >= 0", name="amount_non_negative"),
        CheckConstraint("first_seen <= last_seen", name="seen_range"),
        Index("ix_provider_models_seen_org_last", "organization_id", "last_seen"),
    )

    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    model: Mapped[str] = mapped_column(Text, primary_key=True)
    first_seen: Mapped[date] = mapped_column(Date, nullable=False)
    last_seen: Mapped[date] = mapped_column(Date, nullable=False)
    last_amount_30d: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False, server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


__all__ = ["ProviderModelSeen"]
