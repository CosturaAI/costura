"""Invoice totals an owner typed in for one provider account and one calendar month.

Provider APIs report usage, not the invoice: tax, credits and late restatements live only on
the bill. Reconciliation compares Costura's month total with this figure when one exists.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from costura.db import Base


class ProviderInvoice(Base):
    __tablename__ = "provider_invoices"
    __table_args__ = (
        CheckConstraint("month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'", name="month"),
        CheckConstraint("amount >= 0", name="amount"),
    )

    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    provider_account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("provider_accounts.id", ondelete="CASCADE"), primary_key=True
    )
    # Calendar month the invoice covers, `YYYY-MM`.
    month: Mapped[str] = mapped_column(Text, primary_key=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="USD")
    # Free text for the reader: "includes 8% VAT", "credit of 120 applied".
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    entered_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
