"""The organization's audit trail."""

from datetime import datetime

from pydantic import BaseModel


class AuditEventOut(BaseModel):
    id: int
    event: str
    actor_email: str | None
    target: str | None
    request_id: str | None
    details: dict[str, str]
    created_at: datetime


class AuditOut(BaseModel):
    events: list[AuditEventOut]
    # Rows matching before `limit` and `offset`.
    total: int
    limit: int
    offset: int
