from typing import cast

from fastapi import APIRouter, Response

from costura import audit
from costura.api import schemas
from costura.api.deps import (
    ConcreteProviderDep,
    CurrentUserDep,
    OperatorOrgDep,
    OrgDep,
    ProviderDep,
    SessionDep,
)
from costura.api.guard import VerifiedWriteDep
from costura.api.presenters.signals import SignalView, closed_signal_out, signal_out
from costura.api.schemas.signals import SnoozeKind
from costura.models import SignalSnooze
from costura.spend import snoozes
from costura.spend.signal_events import closed_signals
from costura.spend.signals import collect_signals, org_thresholds

router = APIRouter()


@router.get("/orgs/{org}/providers/{provider}/signals", response_model=schemas.SignalsOut)
def signals(session: SessionDep, org: OrgDep, provider: ProviderDep) -> schemas.SignalsOut:
    """What needs a person in the scope, most money first: open anomalies of any date and the
    budget alerts of the current month. The time frame does not narrow it."""
    found = collect_signals(session, org.id, provider, thresholds=org_thresholds(session, org.id))
    view = SignalView(session, org.id, provider)
    snoozed = snoozes.active_snoozes(session, org.id, provider)
    return schemas.SignalsOut(
        items=[signal_out(view, s) for s in found],
        total=len(found),
        snoozed=[_snooze_out(row) for row in snoozed.values()],
    )


@router.get("/orgs/{org}/signals/history", response_model=schemas.SignalHistoryOut)
def signal_history(session: SessionDep, org: OrgDep) -> schemas.SignalHistoryOut:
    """Signals of every provider closed in the last 90 days, newest first, with how long each
    stayed open. The worker records them every 15 minutes."""
    return schemas.SignalHistoryOut(
        items=[closed_signal_out(c) for c in closed_signals(session, org.id)]
    )


def _snooze_out(row: SignalSnooze) -> schemas.SnoozeOut:
    return schemas.SnoozeOut(
        kind=cast(SnoozeKind, row.kind),
        provider=row.provider,
        key_id=row.key_id,
        until=row.until,
        note=row.note,
    )


@router.put("/orgs/{org}/providers/{provider}/signals/snoozes", response_model=schemas.SnoozeOut)
def snooze_signal(
    session: SessionDep,
    org: OperatorOrgDep,
    provider: ConcreteProviderDep,
    user: CurrentUserDep,
    body: schemas.SnoozeIn,
    _guard: VerifiedWriteDep,
) -> schemas.SnoozeOut:
    """Snooze one gap of one key for 7, 30 or 90 days: it leaves the queue, the inbox and the
    webhook until then. Snoozing it again moves the date. Owner or member; 404 for a key the
    inventory does not hold."""
    row = snoozes.snooze(
        session,
        org.id,
        provider,
        kind=body.kind,
        key_id=body.key_id,
        days=body.days,
        note=body.note,
        user_id=user.id,
    )
    audit.record(
        "signal_snoozed",
        session=session,
        org_id=org.id,
        target=f"{provider}:{body.key_id}",
        kind=body.kind,
        until=row.until.isoformat(),
    )
    return _snooze_out(row)


@router.delete("/orgs/{org}/providers/{provider}/signals/snoozes/{kind}/{key_id}", status_code=204)
def lift_snooze(
    session: SessionDep,
    org: OperatorOrgDep,
    provider: ConcreteProviderDep,
    kind: str,
    key_id: str,
    _guard: VerifiedWriteDep,
) -> Response:
    """Bring a snoozed gap back now. Owner or member."""
    if snoozes.lift(session, org.id, provider, kind=kind, key_id=key_id):
        audit.record(
            "signal_snooze_lifted",
            session=session,
            org_id=org.id,
            target=f"{provider}:{key_id}",
            kind=kind,
        )
    return Response(status_code=204)
