"""Snapshot of a provider's directory: workspaces, users, API keys, workspace members.

One row per external id. A full listing that no longer returns an id sets `missing_since`;
the row is never deleted. Cross references are provider ids, not foreign keys, because spend
rows can cite ids that predate the first inventory run.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from costura.db import Base
from costura.models.checks import one_of

USER_KINDS = ("user", "service_account")


class _SnapshotColumns:
    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, sort_order=-10
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id"), nullable=False, sort_order=-9
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False, sort_order=-8)
    provider_account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("provider_accounts.id", ondelete="CASCADE"),
        nullable=False,
        sort_order=-7,
    )
    sync_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("provider_sync_runs.id"), nullable=False, index=True, sort_order=10
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), sort_order=11
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), sort_order=12
    )
    missing_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), sort_order=13)


class ProviderWorkspace(_SnapshotColumns, Base):
    __tablename__ = "provider_workspaces"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "provider",
            "provider_account_id",
            "external_id",
            name="uq_provider_workspaces_external_id",
        ),
    )

    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tags: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class ProviderUser(_SnapshotColumns, Base):
    __tablename__ = "provider_users"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "provider",
            "provider_account_id",
            "external_id",
            name="uq_provider_users_external_id",
        ),
        one_of("kind", USER_KINDS),
    )

    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    # A service account has no address; `email` holds its name, the id the console shows.
    email: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    added_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'user'"))
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pending_removal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    limit_reported: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    spend_limit: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))


class ProviderApiKey(_SnapshotColumns, Base):
    __tablename__ = "provider_api_keys"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "provider",
            "provider_account_id",
            "external_id",
            name="uq_provider_api_keys_external_id",
        ),
        Index(
            "ix_provider_api_keys_org_provider_workspace",
            "organization_id",
            "provider",
            "workspace_external_id",
        ),
    )

    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # Display fragment (sk-ant-api03-...abcd) returned by the provider; never a usable key.
    partial_key_hint: Mapped[str | None] = mapped_column(Text)
    workspace_external_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_external_id: Mapped[str | None] = mapped_column(Text)
    principal_external_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    principal_type: Mapped[str | None] = mapped_column(Text)
    scope_type: Mapped[str | None] = mapped_column(Text)
    limit_reported: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    spend_limit: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    limit_remaining: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    limit_reset: Mapped[str | None] = mapped_column(Text)


class ProviderWorkspaceMember(_SnapshotColumns, Base):
    __tablename__ = "provider_workspace_members"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "provider",
            "provider_account_id",
            "workspace_external_id",
            "user_external_id",
            name="uq_provider_workspace_members_workspace_user",
        ),
    )

    workspace_external_id: Mapped[str] = mapped_column(Text, nullable=False)
    user_external_id: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)


LIMIT_ENFORCEMENTS = ("hard", "soft")


class ProviderLimit(_SnapshotColumns, Base):
    __tablename__ = "provider_limits"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "provider",
            "provider_account_id",
            "external_id",
            name="uq_provider_limits_external_id",
        ),
        one_of("enforcement", LIMIT_ENFORCEMENTS),
    )

    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    scope_kind: Mapped[str] = mapped_column(Text, nullable=False)
    scope_name: Mapped[str | None] = mapped_column(Text)
    product: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    consumed: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    enforcement: Mapped[str] = mapped_column(Text, nullable=False)


INVENTORY_EVENT_KINDS = ("created", "status_changed", "missing", "returned")
INVENTORY_ENTITY_KINDS = ("api_key", "user")


class ProviderInventoryEvent(Base):
    __tablename__ = "provider_inventory_events"
    __table_args__ = (
        Index(
            "ix_provider_inventory_events_entity",
            "organization_id",
            "provider",
            "entity_kind",
            "external_id",
        ),
        one_of("event", INVENTORY_EVENT_KINDS),
        one_of("entity_kind", INVENTORY_ENTITY_KINDS),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id"), nullable=False
    )
    provider_account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("provider_accounts.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    entity_kind: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    event: Mapped[str] = mapped_column(Text, nullable=False)
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str | None] = mapped_column(Text)
    sync_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("provider_sync_runs.id", ondelete="SET NULL"), index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
