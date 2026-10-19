"""Effective-dated USD prices for Codex workspace credits."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from costura.db import Base


class CreditPrice(Base):
    __tablename__ = "credit_prices"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "provider_account_id",
            "effective_from",
            name="uq_credit_prices_account_effective_from",
        ),
        CheckConstraint("price_per_credit > 0", name="price_per_credit_positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    provider_account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("provider_accounts.id", ondelete="CASCADE"), nullable=False
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    price_per_credit: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["CreditPrice"]
