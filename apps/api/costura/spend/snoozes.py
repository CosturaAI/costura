"""Key gaps a member chose to live with for a while: snoozed gaps leave the signals queue,
the inbox and the webhook until their date passes."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from costura.errors import InvalidInput, NotFound
from costura.models import ProviderApiKey, ProviderUser, SignalSnooze
from costura.models.intelligence import SNOOZE_KINDS
from costura.spend.scope import provider_clause

SNOOZE_DAYS = (7, 30, 90)
SEAT_KINDS = frozenset({"idle_seat", "seat_no_limit"})

SnoozeKey = tuple[str, str, str]


def active_snoozes(
    session: Session, org_id: int, provider: str, today: date | None = None
) -> dict[SnoozeKey, SignalSnooze]:
    today = today or datetime.now(UTC).date()
    rows = session.scalars(
        select(SignalSnooze).where(
            SignalSnooze.organization_id == org_id,
            provider_clause(SignalSnooze.provider, provider),
            SignalSnooze.until > today,
        )
    )
    return {(row.kind, row.provider, row.key_id): row for row in rows}


def snooze(
    session: Session,
    org_id: int,
    provider: str,
    *,
    kind: str,
    key_id: str,
    days: int,
    note: str | None,
    user_id: int | None,
    today: date | None = None,
) -> SignalSnooze:
    """Snooze one gap of one key for `days`; snoozing it again moves the date."""
    if kind not in SNOOZE_KINDS:
        raise InvalidInput(f"only key gaps can be snoozed: {', '.join(SNOOZE_KINDS)}")
    if days not in SNOOZE_DAYS:
        raise InvalidInput(f"snooze for {', '.join(str(d) for d in SNOOZE_DAYS)} days")
    model = ProviderUser if kind in SEAT_KINDS else ProviderApiKey
    found = session.scalar(
        select(model.id).where(
            model.organization_id == org_id,
            model.provider == provider,
            model.external_id == key_id,
        )
    )
    if found is None:
        raise NotFound("unknown seat" if kind in SEAT_KINDS else "unknown key")
    until = (today or datetime.now(UTC).date()) + timedelta(days=days)
    values = {
        "organization_id": org_id,
        "kind": kind,
        "provider": provider,
        "key_id": key_id,
        "until": until,
        "note": (note or "").strip() or None,
        "created_by": user_id,
    }
    session.execute(
        pg_insert(SignalSnooze)
        .values(values)
        .on_conflict_do_update(
            constraint="uq_signal_snoozes",
            set_={"until": until, "note": values["note"], "created_by": user_id},
        )
    )
    session.flush()
    row = session.scalar(
        select(SignalSnooze).where(
            SignalSnooze.organization_id == org_id,
            SignalSnooze.kind == kind,
            SignalSnooze.provider == provider,
            SignalSnooze.key_id == key_id,
        )
    )
    assert row is not None
    session.refresh(row)
    return row


def lift(session: Session, org_id: int, provider: str, *, kind: str, key_id: str) -> bool:
    removed = session.execute(
        delete(SignalSnooze).where(
            SignalSnooze.organization_id == org_id,
            SignalSnooze.provider == provider,
            SignalSnooze.kind == kind,
            SignalSnooze.key_id == key_id,
        )
    )
    session.flush()
    return bool(getattr(removed, "rowcount", 0))
