"""Liveness of the sync worker and the scheduler.

One row per process. A healthcheck reads the newest `last_seen_at` for a role; it does
not need the row of the process that is being checked.
"""

from datetime import datetime

from sqlalchemy import DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from costura.db import Base
from costura.models.checks import one_of

HEARTBEAT_ROLES = ("worker", "scheduler")


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    __table_args__ = (one_of("role", HEARTBEAT_ROLES),)

    owner: Mapped[str] = mapped_column(Text, primary_key=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    version: Mapped[str] = mapped_column(Text, nullable=False)
