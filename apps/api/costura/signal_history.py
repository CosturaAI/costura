"""Keep a history of signals: when each one opened and when it closed.

Signals are computed on read, so a closed one left no record. The worker calls
`record_all` every `HISTORY_INTERVAL_SECONDS` (`ops/worker.py`); each pass compares an
organization's current signals with its open `signal_events` rows, opens a row for a new
entity and closes the rows whose signal is gone. The key is the entity (kind, provider,
entity kind, entity id), so a budget that crosses 80% and then 100% is one stretch, and a
key that loses its owner again next month is a second one.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from costura.api.presenters.signals import SignalView, detail_of
from costura.models import Organization, SignalEvent
from costura.spend.money import STORAGE_EXPONENT
from costura.spend.scope import ALL
from costura.spend.signal_events import HISTORY_DAYS, EntityKey, entity_key, signal_key
from costura.spend.signals import Signal, collect_signals, org_thresholds

log = logging.getLogger(__name__)


def record_history(session: Session, org_id: int, *, now: datetime | None = None) -> int:
    """Open and close the organization's signal events; returns how many rows changed."""
    now = now or datetime.now(UTC)
    found = collect_signals(
        session, org_id, ALL, today=now.date(), thresholds=org_thresholds(session, org_id)
    )
    current: dict[EntityKey, Signal] = {}
    for signal in found:
        current.setdefault(signal_key(signal), signal)
    open_rows = {
        entity_key(r.kind, r.provider, r.entity_kind, r.entity_id): r
        for r in session.scalars(
            select(SignalEvent).where(
                SignalEvent.organization_id == org_id, SignalEvent.closed_at.is_(None)
            )
        )
    }
    view = SignalView(session, org_id, ALL)
    changed = 0
    for key, row in open_rows.items():
        if key not in current:
            row.closed_at = now
            changed += 1
    for key, signal in current.items():
        label, detail = view.label(signal), detail_of(signal)
        dollars = signal.dollars_at_risk.quantize(STORAGE_EXPONENT)
        row = open_rows.get(key)
        if row is None:
            session.add(
                SignalEvent(
                    organization_id=org_id,
                    kind=signal.kind,
                    provider=signal.provider,
                    entity_kind=signal.entity_kind,
                    entity_id=signal.entity_id,
                    label=label,
                    detail=detail,
                    dollars_at_risk=dollars,
                    opened_at=min(signal.detected_at, now),
                )
            )
            changed += 1
        else:
            row.label, row.detail, row.dollars_at_risk = label, detail, dollars
    session.execute(
        delete(SignalEvent).where(
            SignalEvent.organization_id == org_id,
            SignalEvent.closed_at < now - timedelta(days=HISTORY_DAYS),
        )
    )
    session.flush()
    return changed


def record_all(session_factory: Callable[[], Session]) -> int:
    """One pass over every organization, each in its own transaction."""
    with session_factory() as session:
        org_ids = list(session.scalars(select(Organization.id)))
    changed = 0
    for org_id in org_ids:
        with session_factory() as session:
            try:
                changed += record_history(session, org_id)
                session.commit()
            except Exception:
                session.rollback()
                log.exception("signal history failed org_id=%s", org_id)
    return changed
