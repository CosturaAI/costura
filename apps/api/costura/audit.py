"""Security events. The logger is `costura.audit`, so production JSON logging picks it up.

Never pass a secret, a provider key, or a session token. Prefer ids over e-mail addresses.
An event about an organization written with a `session` is also stored in `audit_events`
with the signed-in actor and the request id, in the request's own transaction.
"""

import logging
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy.orm import Session

from costura.telemetry import request_id_var

log = logging.getLogger("costura.audit")


@dataclass
class Actor:
    user_id: int | None = None
    email: str | None = None


actor_var: ContextVar[Actor | None] = ContextVar("costura_actor", default=None)


def remember_actor(user_id: int, email: str) -> None:
    """Called once the request's session resolves. The middleware put a holder in the
    context; dependencies run in worker threads with a copy of it, so the holder is filled
    in place rather than replaced."""
    holder = actor_var.get()
    if holder is not None:
        holder.user_id = user_id
        holder.email = email


def record(
    event: str,
    *,
    session: Session | None = None,
    org_id: int | None = None,
    target: str | None = None,
    **fields: object,
) -> None:
    """One info line. Values are stringified; None fields are omitted. With a `session` and
    an `org_id` the event is also stored."""
    actor = actor_var.get()
    shown = {
        "org_id": org_id,
        "actor_id": actor.user_id if actor else None,
        "target": target,
        **fields,
    }
    rendered = " ".join(f"{key}={value}" for key, value in shown.items() if value is not None)
    log.info("%s %s", event, rendered)
    if session is None or org_id is None:
        return
    from costura.models.audit import AuditEvent

    session.add(
        AuditEvent(
            organization_id=org_id,
            event=event,
            actor_user_id=actor.user_id if actor else None,
            actor_email=actor.email if actor else None,
            target=target,
            request_id=request_id_var.get(),
            details={key: str(value) for key, value in fields.items() if value is not None},
        )
    )
    session.flush()
