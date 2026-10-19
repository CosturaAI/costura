"""Derived judgments over the daily series: anomalies and month-end projections.

Both tables are recomputed by the scheduler (`detect`, `project` steps) and read by the API;
nothing here is a source of record.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, get_args

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from costura.db import Base
from costura.models.checks import one_of

# Anomaly series: the organization total and the principals, an API key or an OAuth account
# (a Claude Code login), which is who to write to. Workspaces and models are root causes.
AnomalySeriesKind = Literal["org", "api_key", "account"]
ANOMALY_SERIES_KINDS: tuple[AnomalySeriesKind, ...] = get_args(AnomalySeriesKind)
PRINCIPAL_KINDS = ANOMALY_SERIES_KINDS[1:]
# Projection series: the organization total, a workspace, a model, or an API key.
ProjectionSeriesKind = Literal["org", "workspace", "model", "api_key"]
PROJECTION_SERIES_KINDS: tuple[ProjectionSeriesKind, ...] = get_args(ProjectionSeriesKind)
AnomalyStatus = Literal["open", "acknowledged", "ignored"]
ANOMALY_STATUSES: tuple[AnomalyStatus, ...] = get_args(AnomalyStatus)
# What is off about the series: a day above its upper bound, a day below its lower
# bound, or a principal that spends a share of the organization's day in its first days.
AnomalyKind = Literal["spike", "drop", "new_principal"]
ANOMALY_KINDS: tuple[AnomalyKind, ...] = get_args(AnomalyKind)
# How abnormal the episode is: deviation in MAD units combined with the total impact.
AnomalySeverity = Literal["low", "medium", "high"]
ANOMALY_SEVERITIES: tuple[AnomalySeverity, ...] = get_args(AnomalySeverity)
# Bound width and impact floor of the detector; `costura.spend.anomalies.THRESHOLDS`.
AnomalySensitivity = Literal["low", "normal", "high"]
ANOMALY_SENSITIVITIES: tuple[AnomalySensitivity, ...] = get_args(AnomalySensitivity)
ORG_SERIES_ID = "__org__"


class SpendAnomaly(Base):
    """One episode of one series: the day it started, the day it was last off, and the totals
    over that range. A one-day episode has `day == end_day` and `duration_days == 1`."""

    __tablename__ = "spend_anomalies"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "provider",
            "provider_account_id",
            "series_kind",
            "series_id",
            "day",
        ),
        Index("ix_spend_anomalies_org_provider_day", "organization_id", "provider", "day"),
        one_of("kind", ANOMALY_KINDS),
        one_of("severity", ANOMALY_SEVERITIES),
        one_of("series_kind", ANOMALY_SERIES_KINDS),
        one_of("status", ANOMALY_STATUSES),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("provider_accounts.id", ondelete="CASCADE"), nullable=False
    )
    series_kind: Mapped[AnomalySeriesKind] = mapped_column(Text, nullable=False)
    series_id: Mapped[str] = mapped_column(Text, nullable=False)
    # First day of the episode; the unique key uses it, so a continuation after a month
    # boundary is a row of its own.
    day: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[AnomalyKind] = mapped_column(Text, nullable=False, server_default="spike")
    # Last day of the episode found by the pass, and whether that day is the last one with
    # data (the episode may still be running).
    end_day: Mapped[date] = mapped_column(Date, nullable=False)
    ongoing: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # Amounts of the first day of the episode; the bound is the one computed on that day and
    # held for its whole run, so a level shift does not become the new normal.
    actual: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    expected: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    upper_bound: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    # Null for a `new_principal` episode, which has no history to bound.
    lower_bound: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    # "weekday" (same weekday over the trailing weeks), "active_days" (the non-zero days of
    # the trailing 28), "trailing" (the trailing 28 days) or "new_series" (a `new_principal`,
    # which has no history to describe).
    baseline_method: Mapped[str] = mapped_column(Text, nullable=False, server_default="weekday")
    baseline_samples: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    impact: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    impact_percent: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    # Impact over the organization's spend of this provider from the first of the month to the
    # anomaly day, as a ratio (0.1234 = 12.34%). Null when that total is zero.
    impact_share: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    # Summed over every day of the episode; `max_impact` is its worst single day.
    total_actual: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    total_expected: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    total_impact: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    max_impact: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    # Impact in MAD units (`impact / (1.4826 x MAD)`); null when the samples have no spread.
    deviation: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    severity: Mapped[AnomalySeverity] = mapped_column(Text, nullable=False, server_default="low")
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False, server_default="USD")
    root_causes: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    status: Mapped[AnomalyStatus] = mapped_column(Text, nullable=False, default="open")
    status_reason: Mapped[str | None] = mapped_column(Text)
    status_changed_by: Mapped[str | None] = mapped_column(Text)
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AnomalySettings(Base):
    """How one organization wants its spend watched: the width of the bounds and which rule
    families run.

    Detection itself is never silenced: every episode is stored and shown. A missing row means
    the defaults below.
    """

    __tablename__ = "anomaly_settings"
    __table_args__ = (
        one_of("sensitivity", ANOMALY_SENSITIVITIES),
        CheckConstraint("retention_days BETWEEN 30 AND 365", name="retention_days"),
        CheckConstraint("idle_days BETWEEN 7 AND 365", name="idle_days"),
        CheckConstraint("new_key_days BETWEEN 1 AND 90", name="new_key_days"),
    )

    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    sensitivity: Mapped[AnomalySensitivity] = mapped_column(
        Text, nullable=False, server_default="normal"
    )
    detect_drops: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    detect_new_principals: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="90")
    idle_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="30")
    new_key_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="7")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AnomalyRead(Base):
    """One user has seen one anomaly in their in-product inbox. Rows disappear with the user
    or with the anomaly; there is no organization column because the anomaly carries it."""

    __tablename__ = "anomaly_reads"
    # The cascade from `spend_anomalies` and the unread query look rows up by anomaly.
    __table_args__ = (Index("ix_anomaly_reads_anomaly_id", "anomaly_id"),)

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    anomaly_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("spend_anomalies.id", ondelete="CASCADE"), primary_key=True
    )
    read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


SIGNAL_READ_KINDS = (
    "budget",
    "sync_stale",
    "webhook_failing",
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


class SignalRead(Base):
    """One user has seen one budget alert or key governance gap in their inbox. `reference`
    is the budget alert id for a budget signal and the key id for a gap, so a new threshold
    crossing or a new gap on the same key counts as unread again."""

    __tablename__ = "signal_reads"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "organization_id", "kind", "provider", "reference", name="uq_signal_reads"
        ),
        Index("ix_signal_reads_organization_id", "organization_id"),
        one_of("kind", SIGNAL_READ_KINDS),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False)
    read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


SIGNAL_EVENT_KINDS = ("anomaly", *SIGNAL_READ_KINDS)


class SignalEvent(Base):
    """One stretch of time a signal was open: the worker's history pass opens a row when a
    signal of an entity appears and closes it when the signal is gone (resolved, snoozed or
    acknowledged). Rows closed more than `HISTORY_DAYS` ago are deleted by the same pass."""

    __tablename__ = "signal_events"
    __table_args__ = (
        Index(
            "ix_signal_events_org_entity",
            "organization_id",
            "kind",
            "provider",
            "entity_kind",
            "entity_id",
        ),
        Index("ix_signal_events_org_closed_at", "organization_id", "closed_at"),
        one_of("kind", SIGNAL_EVENT_KINDS),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    entity_kind: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    # Label and detail as the signal read when it last was open, for the closed list.
    label: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    dollars_at_risk: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


SNOOZE_KINDS = (
    "no_owner",
    "no_limit",
    "owner_left",
    "idle_active",
    "new_key",
    "idle_seat",
    "seat_no_limit",
)


class SignalSnooze(Base):
    """A member decided to live with one gap of one key until `until`; the gap leaves the
    queue, the inbox and the webhook until then."""

    __tablename__ = "signal_snoozes"
    __table_args__ = (
        UniqueConstraint("organization_id", "kind", "provider", "key_id", name="uq_signal_snoozes"),
        one_of("kind", SNOOZE_KINDS),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    key_id: Mapped[str] = mapped_column(Text, nullable=False)
    until: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SpendProjection(Base):
    __tablename__ = "spend_projections"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "provider",
            "provider_account_id",
            "series_kind",
            "series_id",
            "month",
        ),
        one_of("series_kind", PROJECTION_SERIES_KINDS),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("provider_accounts.id", ondelete="CASCADE"), nullable=False
    )
    series_kind: Mapped[str] = mapped_column(Text, nullable=False)
    series_id: Mapped[str] = mapped_column(Text, nullable=False)
    month: Mapped[str] = mapped_column(Text, nullable=False)
    as_of_day: Mapped[date] = mapped_column(Date, nullable=False)
    mtd: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    projected_total: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    days: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False, default=list)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
