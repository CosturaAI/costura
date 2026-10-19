"""Outbound delivery of signals to an organization's webhook.

`webhook_destinations` holds one Fernet-encrypted URL and signing secret per organization
(see costura.secrets); `url_host` is the only part of the URL a response shows. Every signal
becomes one `webhook_deliveries` row, unique per organization and signal, so a signal is
sent at most once and its attempts are recorded on that row.
"""

from datetime import date, datetime
from typing import Literal, get_args

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from costura.db import Base
from costura.models.checks import one_of

DeliveryStatus = Literal["pending", "sent", "failed", "skipped"]
DigestCadence = Literal["off", "weekly", "monthly"]
DIGEST_CADENCES: tuple[str, ...] = get_args(DigestCadence)
DELIVERY_STATUSES: tuple[str, ...] = get_args(DeliveryStatus)
DELIVERY_KINDS = (
    "anomaly",
    "budget",
    "sync_stale",
    "model_retiring",
    "near_limit",
    "idle_seat",
    "seat_no_limit",
    "unit_cost_up",
    "no_owner",
    "no_limit",
    "owner_left",
    "idle_active",
    "new_key",
)


class WebhookDestination(Base):
    __tablename__ = "webhook_destinations"
    __table_args__ = (one_of("digest", DIGEST_CADENCES),)

    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id"), primary_key=True
    )
    url_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    url_host: Mapped[str] = mapped_column(Text, nullable=False)
    secret_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    digest: Mapped[str] = mapped_column(Text, nullable=False, server_default="off")
    last_digest_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class WebhookDelivery(Base):
    """One signal for one organization's webhook. `reference` follows the inbox read mark:
    the anomaly id, the budget alert id, or the key id of a gap."""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "kind", "provider", "reference", name="uq_webhook_deliveries"
        ),
        Index(
            "ix_webhook_deliveries_org_status_next", "organization_id", "status", "next_attempt_at"
        ),
        one_of("kind", DELIVERY_KINDS),
        one_of("status", DELIVERY_STATUSES),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[DeliveryStatus] = mapped_column(Text, nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
