"""Reads and triage writes behind the anomaly pages: the paged list, one anomaly, the other
anomalies of its day, status changes, the per-member inbox and the detection settings."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import ColumnElement, case, false, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from costura.errors import InvalidInput, NotFound
from costura.models import AnomalyRead, AnomalySettings, SpendAnomaly
from costura.models.intelligence import (
    ANOMALY_SEVERITIES,
    AnomalySensitivity,
    AnomalySeriesKind,
    AnomalyStatus,
)
from costura.providers.registry import ALL
from costura.spend.inventory import InventoryResolver
from costura.spend.membership import membership
from costura.spend.scope import provider_clause
from costura.spend.window import Window

ANOMALIES_LIMIT_DEFAULT = 500
ANOMALIES_LIMIT_MAX = 1000
ALERT_ITEMS = 50
NOT_A_MEMBER = "not a member of this organization"

AnomalySort = Literal["day", "impact", "severity"]

SEVERITY_RANK = case(
    {name: rank for rank, name in enumerate(ANOMALY_SEVERITIES)},
    value=SpendAnomaly.severity,
    else_=0,
)


@dataclass(frozen=True)
class AnomalyPage:
    rows: list[SpendAnomaly]
    total: int
    open_count: int
    open_total: int


def list_anomalies(
    session: Session,
    org_id: int,
    provider: str,
    window: Window,
    *,
    status: AnomalyStatus | None = None,
    series_kind: AnomalySeriesKind | None = None,
    series_id: str | None = None,
    person: str | None = None,
    sort: AnomalySort = "day",
    limit: int = ANOMALIES_LIMIT_DEFAULT,
    offset: int = 0,
) -> AnomalyPage:
    """Stored anomalies of the window in the chosen order, how many match, and how many are
    open under the same series filter (the status filter does not apply to that count), in
    the window and on any day.
    `person` keeps the account series of that e-mail's identities on every provider."""
    scope: list[ColumnElement[bool]] = [
        SpendAnomaly.organization_id == org_id,
        provider_clause(SpendAnomaly.provider, provider),
    ]
    if series_kind:
        scope.append(SpendAnomaly.series_kind == series_kind)
    if series_id:
        scope.append(SpendAnomaly.series_id == series_id)
    if person:
        identities = InventoryResolver(session, org_id, provider).person_identities(person)
        scope.append(SpendAnomaly.series_kind == "account")
        scope.append(
            or_(
                *[
                    (SpendAnomaly.provider == line_provider)
                    & (SpendAnomaly.series_id == external_id)
                    for line_provider, external_id in identities
                ]
            )
            if identities
            else false()
        )
    any_day = list(scope)
    scope += [SpendAnomaly.day >= window.start.date(), SpendAnomaly.day < window.end.date()]
    statement = select(SpendAnomaly).where(*scope)
    if status:
        statement = statement.where(SpendAnomaly.status == status)
    if sort == "impact":
        order = (SpendAnomaly.impact.desc(), SpendAnomaly.day.desc(), SpendAnomaly.id)
    elif sort == "severity":
        order = (SEVERITY_RANK.desc(), SpendAnomaly.total_impact.desc(), SpendAnomaly.id)
    else:
        order = (SpendAnomaly.day.desc(), SpendAnomaly.impact.desc(), SpendAnomaly.id)
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = list(session.scalars(statement.order_by(*order).limit(limit).offset(offset)))
    open_count = session.scalar(
        select(func.count()).select_from(SpendAnomaly).where(*scope, SpendAnomaly.status == "open")
    )
    open_total = session.scalar(
        select(func.count())
        .select_from(SpendAnomaly)
        .where(*any_day, SpendAnomaly.status == "open")
    )
    return AnomalyPage(
        rows=rows, total=total, open_count=open_count or 0, open_total=open_total or 0
    )


def get_anomaly(session: Session, org_id: int, provider: str, anomaly_id: int) -> SpendAnomaly:
    """404 when the id belongs to another organization or, under a concrete provider, to
    another provider."""
    row = session.get(SpendAnomaly, anomaly_id)
    if row is None or row.organization_id != org_id:
        raise NotFound("anomaly not found")
    if provider != ALL and row.provider != provider:
        raise NotFound("anomaly not found")
    return row


def same_day(session: Session, row: SpendAnomaly) -> list[SpendAnomaly]:
    """The other anomalies of the same provider and day, largest impact first."""
    return list(
        session.scalars(
            select(SpendAnomaly)
            .where(
                SpendAnomaly.organization_id == row.organization_id,
                SpendAnomaly.provider == row.provider,
                SpendAnomaly.day == row.day,
                SpendAnomaly.id != row.id,
            )
            .order_by(SpendAnomaly.impact.desc(), SpendAnomaly.id)
        )
    )


def set_status(
    session: Session,
    org_id: int,
    provider: str,
    anomaly_id: int,
    status: AnomalyStatus,
    *,
    reason: str | None = None,
    actor: str | None = None,
) -> SpendAnomaly:
    """Triage one anomaly. The reason ("expected: the batch backfill") and who set it stay
    on the row; reopening clears the reason."""
    row = get_anomaly(session, org_id, provider, anomaly_id)
    row.status = status
    row.status_reason = None if status == "open" else ((reason or "").strip() or None)
    row.status_changed_by = actor
    row.status_changed_at = datetime.now(UTC)
    session.flush()
    session.refresh(row)
    return row


@dataclass(frozen=True)
class Inbox:
    opted_in: bool
    unread_count: int
    items: list[tuple[SpendAnomaly, datetime | None]]
    since: datetime | None = None


def inbox(session: Session, org_id: int, user_id: int) -> Inbox:
    """The member's anomaly inbox: whether they opted in, how many open anomalies detected
    since then they have not read, and the newest `ALERT_ITEMS` with their read mark."""
    member = membership(session, org_id, user_id)
    since = None if member is None else member.anomaly_alerts_since
    if since is None:
        return Inbox(opted_in=False, unread_count=0, items=[])
    read_at = (
        select(AnomalyRead.read_at)
        .where(AnomalyRead.user_id == user_id, AnomalyRead.anomaly_id == SpendAnomaly.id)
        .scalar_subquery()
    )
    scope = [SpendAnomaly.organization_id == org_id, SpendAnomaly.detected_at >= since]
    rows = session.execute(
        select(SpendAnomaly, read_at)
        .where(*scope)
        .order_by(SpendAnomaly.detected_at.desc(), SpendAnomaly.impact.desc(), SpendAnomaly.id)
        .limit(ALERT_ITEMS)
    ).all()
    unread = session.scalar(
        select(func.count())
        .select_from(SpendAnomaly)
        .where(*scope, SpendAnomaly.status == "open", read_at.is_(None))
    )
    return Inbox(
        opted_in=True,
        unread_count=unread or 0,
        items=[(row, seen) for row, seen in rows],
        since=since,
    )


def set_alerts_opt_in(session: Session, org_id: int, user_id: int, opted_in: bool) -> None:
    """Opting in starts the unread count at the anomalies detected from now on; opting out
    clears it. 404 for a caller who is not a member."""
    member = membership(session, org_id, user_id)
    if member is None:
        raise NotFound(NOT_A_MEMBER)
    if opted_in and member.anomaly_alerts_since is None:
        member.anomaly_alerts_since = datetime.now(UTC)
    elif not opted_in:
        member.anomaly_alerts_since = None
    session.flush()


def mark_read(
    session: Session,
    org_id: int,
    user_id: int,
    *,
    every_unread: bool,
    anomaly_ids: Sequence[int],
) -> None:
    """Mark the listed anomalies of this organization read, or every unread one since the
    opt-in. Ids of other organizations are ignored; a concurrent mark is a no-op."""
    member = membership(session, org_id, user_id)
    if member is None:
        raise NotFound(NOT_A_MEMBER)
    scope = [SpendAnomaly.organization_id == org_id]
    if every_unread:
        if member.anomaly_alerts_since is None:
            return
        scope.append(SpendAnomaly.detected_at >= member.anomaly_alerts_since)
        scope.append(SpendAnomaly.status == "open")
    else:
        if not anomaly_ids:
            raise InvalidInput("send anomaly_ids or all: true")
        scope.append(SpendAnomaly.id.in_(anomaly_ids))
    ids = list(session.scalars(select(SpendAnomaly.id).where(*scope)))
    if ids:
        session.execute(
            pg_insert(AnomalyRead)
            .values([{"user_id": user_id, "anomaly_id": anomaly_id} for anomaly_id in ids])
            .on_conflict_do_nothing()
        )
    session.flush()


def anomaly_settings(session: Session, org_id: int) -> AnomalySettings | None:
    """The saved settings row; None means the defaults."""
    return session.get(AnomalySettings, org_id)


def save_anomaly_settings(
    session: Session,
    org_id: int,
    *,
    sensitivity: AnomalySensitivity,
    detect_drops: bool,
    detect_new_principals: bool,
    retention_days: int,
    idle_days: int = 30,
    new_key_days: int = 7,
) -> AnomalySettings:
    row = session.get(AnomalySettings, org_id)
    if row is None:
        row = AnomalySettings(organization_id=org_id)
        session.add(row)
    row.sensitivity = sensitivity
    row.detect_drops = detect_drops
    row.detect_new_principals = detect_new_principals
    row.retention_days = retention_days
    row.idle_days = idle_days
    row.new_key_days = new_key_days
    session.flush()
    return row
