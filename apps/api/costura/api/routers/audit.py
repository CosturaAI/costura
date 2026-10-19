"""Who connected, replaced or removed a key, changed a role or triaged an anomaly."""

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from costura.api import schemas
from costura.api.deps import OwnedOrgDep, SessionDep
from costura.models import AuditEvent

router = APIRouter()

AUDIT_LIMIT_MAX = 500


@router.get("/orgs/{org}/audit", response_model=schemas.AuditOut)
def audit_trail(
    session: SessionDep,
    org: OwnedOrgDep,
    limit: Annotated[int, Query(gt=0, le=AUDIT_LIMIT_MAX)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> schemas.AuditOut:
    """The organization's audit events, newest first. Owners only (403 for other roles and
    on the sample organization). Rows are never updated or deleted, and a reset keeps
    them."""
    scope = AuditEvent.organization_id == org.id
    total = session.scalar(select(func.count()).select_from(AuditEvent).where(scope)) or 0
    rows = session.scalars(
        select(AuditEvent)
        .where(scope)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return schemas.AuditOut(
        events=[
            schemas.AuditEventOut(
                id=row.id,
                event=row.event,
                actor_email=row.actor_email,
                target=row.target,
                request_id=row.request_id,
                details={key: str(value) for key, value in row.details.items()},
                created_at=row.created_at,
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
