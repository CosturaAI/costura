"""Queries over `signal_events`: the signals closed lately and how often an entity's signal
opened. `costura.signal_history` writes the rows."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from costura.models import SignalEvent
from costura.spend.signals import Signal

HISTORY_DAYS = 90

EntityKey = tuple[str, str, str, str]


def entity_key(kind: str, provider: str, entity_kind: str, entity_id: str) -> EntityKey:
    return (kind, provider, entity_kind, entity_id)


def signal_key(signal: Signal) -> EntityKey:
    return entity_key(signal.kind, signal.provider, signal.entity_kind, signal.entity_id)


@dataclass
class ClosedSignal:
    event: SignalEvent

    @property
    def hours_open(self) -> Decimal:
        closed = self.event.closed_at or self.event.opened_at
        seconds = Decimal((closed - self.event.opened_at).total_seconds())
        return (seconds / 3600).quantize(Decimal("0.1"))


def closed_signals(
    session: Session, org_id: int, *, now: datetime | None = None, limit: int = 50
) -> list[ClosedSignal]:
    """Signals closed in the last `HISTORY_DAYS`, newest first."""
    now = now or datetime.now(UTC)
    rows = session.scalars(
        select(SignalEvent)
        .where(
            SignalEvent.organization_id == org_id,
            SignalEvent.closed_at >= now - timedelta(days=HISTORY_DAYS),
        )
        .order_by(SignalEvent.closed_at.desc(), SignalEvent.id.desc())
        .limit(limit)
    )
    return [ClosedSignal(event=row) for row in rows]


def occurrences(
    session: Session, org_id: int, *, now: datetime | None = None
) -> dict[EntityKey, int]:
    """How many stretches each entity had in the last `HISTORY_DAYS`, the open one included."""
    now = now or datetime.now(UTC)
    rows = session.execute(
        select(
            SignalEvent.kind,
            SignalEvent.provider,
            SignalEvent.entity_kind,
            SignalEvent.entity_id,
            func.count(),
        )
        .where(
            SignalEvent.organization_id == org_id,
            or_(
                SignalEvent.opened_at >= now - timedelta(days=HISTORY_DAYS),
                SignalEvent.closed_at.is_(None),
            ),
        )
        .group_by(
            SignalEvent.kind, SignalEvent.provider, SignalEvent.entity_kind, SignalEvent.entity_id
        )
    ).all()
    return {entity_key(k, p, ek, ei): int(n) for k, p, ek, ei, n in rows}
