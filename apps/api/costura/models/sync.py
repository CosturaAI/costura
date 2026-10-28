from datetime import datetime
from typing import Any, Literal, get_args

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from costura.db import Base
from costura.models.checks import one_of

SyncRunStatus = Literal["running", "succeeded", "failed"]
SYNC_RUN_STATUSES: tuple[SyncRunStatus, ...] = get_args(SyncRunStatus)


class ProviderSyncRun(Base):
    """One invocation of a provider endpoint sync over a time window."""

    __tablename__ = "provider_sync_runs"
    __table_args__ = (
        Index(
            "ix_provider_sync_runs_org_provider_started",
            "organization_id",
            "provider",
            "started_at",
        ),
        one_of("status", SYNC_RUN_STATUSES),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    # Null for provider-level runs (budget evaluation adds the provider's accounts up).
    provider_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("provider_accounts.id", ondelete="CASCADE")
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[SyncRunStatus] = mapped_column(Text, nullable=False, default="running")
    pages_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    raw_results: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_upserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class ProviderReportPage(Base):
    """A provider response page stored as received. Append-only."""

    __tablename__ = "provider_report_pages"
    __table_args__ = (UniqueConstraint("sync_run_id", "page_index"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id"), nullable=False
    )
    sync_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("provider_sync_runs.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    request_params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
