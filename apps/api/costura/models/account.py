"""One provider account of an organization: the console the admin key opens.

An organization can hold several accounts of one provider (three OpenAI organizations, two
Anthropic ones). Every synced row carries `provider_account_id`; the provider stays the scope
readers filter by and the account is a label and a filter on top of it. Removing an account
removes its rows through the foreign keys.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from costura.db import Base

LABEL_MAX_LENGTH = 120


class ProviderAccount(Base):
    __tablename__ = "provider_accounts"
    __table_args__ = (
        UniqueConstraint("organization_id", "provider", "label", name="uq_provider_accounts_label"),
        CheckConstraint(
            """
            provider <> 'cursor' OR (
              jsonb_typeof(settings) = 'object'
              AND (
                NOT settings ? 'seat_price_usd'
                OR (
                  jsonb_typeof(settings->'seat_price_usd') = 'number'
                  AND (settings->>'seat_price_usd')::numeric >= 0
                )
              )
              AND (
                NOT settings ? 'include_included_in_business'
                OR jsonb_typeof(settings->'include_included_in_business') = 'boolean'
              )
            )
            """,
            name="cursor_settings",
        ),
        Index(
            "uq_provider_accounts_external_id",
            "organization_id",
            "provider",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    # What the reader sees next to the provider: "OpenAI - Acme".
    label: Mapped[str] = mapped_column(Text, nullable=False)
    # The provider's own id of the account (Anthropic organization id), when it reports one.
    external_id: Mapped[str | None] = mapped_column(Text)
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    settings_effective_from: Mapped[date] = mapped_column(
        Date, nullable=False, server_default=func.current_date()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
