"""The member's inbox beyond anomalies: the budget alerts crossed since the opt-in and the
governance gaps of active keys, each with the member's read mark."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from costura.errors import NotFound
from costura.models import SignalRead
from costura.spend.anomaly_queries import NOT_A_MEMBER, set_alerts_opt_in
from costura.spend.membership import membership
from costura.spend.scope import ALL
from costura.spend.signals import (
    Signal,
    budget_signals,
    org_thresholds,
    posture_signals,
    sort_signals,
    sync_signals,
    webhook_signals,
)

ReadKey = tuple[str, str, str]


@dataclass(frozen=True)
class InboxSignal:
    signal: Signal
    read_at: datetime | None

    @property
    def key(self) -> ReadKey:
        return read_key(self.signal)


def read_reference(signal: Signal) -> str:
    """The budget alert id for a budget signal, so the next threshold is unread again; the
    signal's own reference otherwise."""
    return str(signal.alert.id) if signal.alert is not None else signal.reference


def read_key(signal: Signal) -> ReadKey:
    return (signal.kind, signal.provider, read_reference(signal))


def current_signals(
    session: Session, org_id: int, since: datetime, today: date | None = None
) -> list[Signal]:
    today = today or datetime.now(UTC).date()
    month = f"{today.year}-{today.month:02d}"
    budgets = [s for s in budget_signals(session, org_id, ALL, month) if s.detected_at >= since]
    gaps = posture_signals(session, org_id, ALL, today, org_thresholds(session, org_id))
    return sort_signals(
        [
            *budgets,
            *sync_signals(session, org_id, ALL, today),
            *webhook_signals(session, org_id, ALL),
            *gaps,
        ]
    )


def signal_inbox(
    session: Session, org_id: int, user_id: int, since: datetime, today: date | None = None
) -> list[InboxSignal]:
    """Every current budget and gap signal with the member's read mark, most money first."""
    reads = {
        (row.kind, row.provider, row.reference): row.read_at
        for row in session.scalars(
            select(SignalRead).where(
                SignalRead.organization_id == org_id, SignalRead.user_id == user_id
            )
        )
    }
    return [
        InboxSignal(signal=s, read_at=reads.get(read_key(s)))
        for s in current_signals(session, org_id, since, today)
    ]


def mark_signals_read(
    session: Session,
    org_id: int,
    user_id: int,
    *,
    every_unread: bool,
    keys: Iterable[ReadKey] = (),
    today: date | None = None,
) -> None:
    """Mark the listed signals read, or every unread one. Keys that match no current signal
    are ignored; a concurrent mark is a no-op."""
    member = membership(session, org_id, user_id)
    if member is None:
        raise NotFound(NOT_A_MEMBER)
    since = member.anomaly_alerts_since
    if since is None:
        return
    current = {read_key(s) for s in current_signals(session, org_id, since, today)}
    chosen = current if every_unread else current & set(keys)
    _insert_reads(session, org_id, user_id, chosen)


def set_inbox_opt_in(
    session: Session, org_id: int, user_id: int, opted_in: bool, today: date | None = None
) -> None:
    """Opt in or out of the inbox. Opting in marks the gaps that already exist read, so the
    unread count starts at what appears from now on, as it does for anomalies; opting out
    forgets the read marks."""
    member = membership(session, org_id, user_id)
    was_in = member is not None and member.anomaly_alerts_since is not None
    set_alerts_opt_in(session, org_id, user_id, opted_in)
    if not opted_in:
        session.execute(
            delete(SignalRead).where(
                SignalRead.organization_id == org_id, SignalRead.user_id == user_id
            )
        )
        session.flush()
        return
    if was_in:
        return
    today = today or datetime.now(UTC).date()
    gaps = posture_signals(session, org_id, ALL, today, org_thresholds(session, org_id))
    _insert_reads(session, org_id, user_id, {read_key(s) for s in gaps})


def _insert_reads(session: Session, org_id: int, user_id: int, keys: set[ReadKey]) -> None:
    if keys:
        session.execute(
            pg_insert(SignalRead)
            .values(
                [
                    {
                        "user_id": user_id,
                        "organization_id": org_id,
                        "kind": kind,
                        "provider": provider,
                        "reference": reference,
                    }
                    for kind, provider, reference in sorted(keys)
                ]
            )
            .on_conflict_do_nothing()
        )
    session.flush()
