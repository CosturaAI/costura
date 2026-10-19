"""The sync queue: one `scheduler_runs` row per queued, running or finished cycle.

The scheduler enqueues, a worker claims with `FOR UPDATE SKIP LOCKED` and holds a lease; the
API only reads the rows.
"""

from datetime import datetime
from typing import Literal, get_args

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from costura.db import Base
from costura.models.checks import one_of

SchedulerTrigger = Literal["scheduler", "manual", "api", "connect"]
SCHEDULER_TRIGGERS: tuple[SchedulerTrigger, ...] = get_args(SchedulerTrigger)
SchedulerRunStatus = Literal["queued", "running", "succeeded", "failed", "skipped"]
SCHEDULER_RUN_STATUSES: tuple[SchedulerRunStatus, ...] = get_args(SchedulerRunStatus)


class SchedulerRun(Base):
    """One queued, running or terminal sync cycle for one provider account.

    The row is the durable queue. `idempotency_key`, when set, is one daily run for an
    organization, provider, account, trigger and UTC day; interactive runs leave it null.
    A worker claims the row (`lease_owner`, `lease_expires_at`, `heartbeat_at`) and may
    retry until `attempt_count` reaches `max_attempts`. Lower `priority` is claimed first
    (interactive syncs before the daily pass). `error` is a short sanitized sentence.
    `provider_account_id` is NULL only when the provider has no connected account.
    """

    __tablename__ = "scheduler_runs"
    __table_args__ = (
        Index(
            "uq_scheduler_runs_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index(
            "ix_scheduler_runs_claim",
            "priority",
            "id",
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
        one_of("status", SCHEDULER_RUN_STATUSES),
        one_of("trigger", SCHEDULER_TRIGGERS),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("organizations.id"))
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("provider_accounts.id", ondelete="CASCADE")
    )
    trigger: Mapped[SchedulerTrigger] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[SchedulerRunStatus] = mapped_column(Text, nullable=False, default="queued")
    steps: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100"
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
