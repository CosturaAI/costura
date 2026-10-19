"""Anomaly list, detail and triage, plus the per-user alert inbox."""

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy.orm import Session

from costura import audit
from costura.api import schemas
from costura.api.deps import (
    CurrentUserDep,
    OperatorOrgDep,
    OrgDep,
    OwnedOrgDep,
    ProviderDep,
    RangeWindowDep,
    SessionDep,
    WritableOrgDep,
)
from costura.api.guard import VerifiedWriteDep
from costura.api.presenters.anomalies import (
    _anomaly,
    _anomaly_settings_out,
    _evidence_out,
    anomaly_view,
    explanation_of,
    inbox_out,
    same_day_out,
    series_points_out,
)
from costura.api.presenters.signals import SignalView, inbox_signal_out
from costura.errors import InvalidInput
from costura.models.intelligence import AnomalySeriesKind, AnomalyStatus
from costura.providers.registry import ALL
from costura.spend import anomaly_queries
from costura.spend.anomaly_queries import (
    ANOMALIES_LIMIT_DEFAULT,
    ANOMALIES_LIMIT_MAX,
    AnomalySort,
)
from costura.spend.evidence import anomaly_evidence
from costura.spend.inbox import mark_signals_read, set_inbox_opt_in, signal_inbox
from costura.spend.ledger import costura_total

router = APIRouter()


@router.get(
    "/orgs/{org}/providers/{provider}/months/{month}/anomalies",
    response_model=schemas.AnomaliesOut,
)
def anomalies(
    session: SessionDep,
    org: OrgDep,
    provider: ProviderDep,
    window: RangeWindowDep,
    month: str,
    status: Annotated[AnomalyStatus | None, Query()] = None,
    series_kind: Annotated[AnomalySeriesKind | None, Query()] = None,
    series_id: Annotated[str | None, Query()] = None,
    person: Annotated[str | None, Query()] = None,
    sort: Annotated[AnomalySort, Query()] = "day",
    limit: Annotated[int, Query(gt=0, le=ANOMALIES_LIMIT_MAX)] = ANOMALIES_LIMIT_DEFAULT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> schemas.AnomaliesOut:
    """Stored anomalies of the month or of the `start..end` days, newest day first and largest
    impact inside a day (`sort=impact` orders by impact across days, `sort=severity` by how
    abnormal the episode is and then by the money it moved); `open_count` ignores the status
    filter but follows the series one, so an entity page counts its own open anomalies.
    `open_total` is the same count on any day, for a badge that keeps it across time frames.
    `person=<e-mail>` keeps the account series of that person's identities on every provider
    in scope. `window_total` is the scope's spend over the same days, so a reader can size an
    impact against the period. `total` counts every matching row; `limit` (at most
    1000) and `offset` page through them in the chosen order."""
    page = anomaly_queries.list_anomalies(
        session,
        org.id,
        provider,
        window,
        status=status,
        series_kind=series_kind,
        series_id=series_id,
        person=person,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    view = anomaly_view(session, org.id, provider)
    window_total, _ = costura_total(session, org.id, provider, window)
    return schemas.AnomaliesOut(
        month=month,
        start=window.start.date().isoformat(),
        end=window.last_day.isoformat(),
        window_total=schemas.money(window_total) or "0.00",
        open_count=page.open_count,
        open_total=page.open_total,
        anomalies=[_anomaly(view, r) for r in page.rows],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/orgs/{org}/providers/{provider}/anomalies/{anomaly_id}",
    response_model=schemas.AnomalyDetailOut,
)
def anomaly_detail(
    session: SessionDep, org: OrgDep, provider: ProviderDep, anomaly_id: int
) -> schemas.AnomalyDetailOut:
    """One anomaly with who to contact, the eight weeks of its series ending on the anomaly
    day (baseline samples marked) and the other anomalies of the same day. 404 when the id
    belongs to another organization or, under a concrete provider, to another provider."""
    row = anomaly_queries.get_anomaly(session, org.id, provider, anomaly_id)
    view = anomaly_view(session, org.id, provider)
    evidence = anomaly_evidence(session, row, view.resolver)
    base = _anomaly(view, row).model_copy(
        update={"explanation": explanation_of(view, row, evidence.decomposition)}
    )
    return schemas.AnomalyDetailOut(
        **base.model_dump(),
        series=series_points_out(evidence, row),
        same_day=same_day_out(view.resolver, anomaly_queries.same_day(session, row)),
        evidence=_evidence_out(evidence, row),
    )


@router.patch(
    "/orgs/{org}/providers/{provider}/anomalies/{anomaly_id}", response_model=schemas.AnomalyOut
)
def set_anomaly_status(
    session: SessionDep,
    org: OperatorOrgDep,
    user: CurrentUserDep,
    provider: ProviderDep,
    anomaly_id: int,
    body: schemas.AnomalyStatusIn,
    _guard: VerifiedWriteDep,
) -> schemas.AnomalyOut:
    row = anomaly_queries.set_status(
        session,
        org.id,
        provider,
        anomaly_id,
        body.status,
        reason=body.reason,
        actor=user.email,
    )
    audit.record(
        "anomaly_status_changed",
        session=session,
        org_id=org.id,
        target=f"anomaly:{anomaly_id}",
        status=body.status,
    )
    return _anomaly(anomaly_view(session, org.id, provider), row)


@router.get("/orgs/{org}/alerts", response_model=schemas.AlertsOut)
def alerts(session: SessionDep, org: OrgDep, user: CurrentUserDep) -> schemas.AlertsOut:
    """The caller's in-product inbox for one organization: whether they opted in, the newest
    50 anomalies since the opt-in with their read mark, and the budget alerts crossed since
    the opt-in plus the governance gaps of active keys (`signals`, most money first, 50
    listed) with theirs. `unread_count` adds the unread open anomalies and the unread signals;
    `unread_by_kind` splits it. Empty and `opted_in: false` on the sample organization and
    for a member who has not opted in."""
    return _inbox(session, org.id, user.id)


def _inbox(session: Session, org_id: int, user_id: int) -> schemas.AlertsOut:
    box = anomaly_queries.inbox(session, org_id, user_id)
    since = box.since
    if since is None:
        return schemas.AlertsOut(opted_in=False, unread_count=0, items=[])
    view = SignalView(session, org_id, ALL)
    found = [inbox_signal_out(view, item) for item in signal_inbox(session, org_id, user_id, since)]
    return inbox_out(anomaly_view(session, org_id, ALL), box, found)


@router.put("/orgs/{org}/alerts/settings", response_model=schemas.AlertsOut)
def set_alert_settings(
    session: SessionDep,
    org: WritableOrgDep,
    user: CurrentUserDep,
    body: schemas.AlertSettingsIn,
    _guard: VerifiedWriteDep,
) -> schemas.AlertsOut:
    """Opt the caller in to (or out of) the inbox of this organization. Opting in starts the
    unread count at the anomalies, budget alerts and key gaps that appear from now on; opting
    out clears it."""
    set_inbox_opt_in(session, org.id, user.id, body.opted_in)
    return _inbox(session, org.id, user.id)


@router.post("/orgs/{org}/alerts/read", response_model=schemas.AlertsOut)
def mark_alerts_read(
    session: SessionDep,
    org: WritableOrgDep,
    user: CurrentUserDep,
    body: schemas.AlertReadIn,
    _guard: VerifiedWriteDep,
) -> schemas.AlertsOut:
    """Mark inbox items of this organization as read for the caller: the listed anomaly ids
    and signals, or every unread item with `all`. Ids of other organizations and signals that
    are no longer current are ignored."""
    if not body.all and not body.anomaly_ids and not body.signals:
        raise InvalidInput("send anomaly_ids, signals or all: true")
    if body.all or body.anomaly_ids:
        anomaly_queries.mark_read(
            session, org.id, user.id, every_unread=body.all, anomaly_ids=body.anomaly_ids
        )
    if body.all or body.signals:
        mark_signals_read(
            session,
            org.id,
            user.id,
            every_unread=body.all,
            keys=[(s.kind, s.provider, s.read_reference) for s in body.signals],
        )
    return _inbox(session, org.id, user.id)


@router.get("/orgs/{org}/anomaly-settings", response_model=schemas.AnomalySettingsOut)
def get_anomaly_settings(session: SessionDep, org: OrgDep) -> schemas.AnomalySettingsOut:
    """How this organization wants spend watched. Defaults when nobody has saved a row."""
    return _anomaly_settings_out(anomaly_queries.anomaly_settings(session, org.id))


@router.put("/orgs/{org}/anomaly-settings", response_model=schemas.AnomalySettingsOut)
def put_anomaly_settings(
    session: SessionDep,
    org: OwnedOrgDep,
    body: schemas.AnomalySettingsIn,
    _guard: VerifiedWriteDep,
) -> schemas.AnomalySettingsOut:
    """Replace the detection settings. Owner only."""
    row = anomaly_queries.save_anomaly_settings(
        session,
        org.id,
        sensitivity=body.sensitivity,
        detect_drops=body.detect_drops,
        detect_new_principals=body.detect_new_principals,
        retention_days=body.retention_days,
        idle_days=body.idle_days,
        new_key_days=body.new_key_days,
    )
    audit.record("anomaly_settings_updated", session=session, org_id=org.id)
    return _anomaly_settings_out(row)
