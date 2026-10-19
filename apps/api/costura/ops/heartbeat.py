"""Write and check process liveness in `worker_heartbeats`.

`python -m costura.ops.heartbeat --role worker` exits 0 when some process of that role
has written within `--max-age` seconds. The worker and the scheduler call `beat` on each
poll. A healthcheck is a different process, so it looks at the role, not its own owner.
"""

import argparse
import os
import socket
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from costura import __version__
from costura.db import SessionLocal
from costura.models.heartbeat import WorkerHeartbeat

ROLES = ("worker", "scheduler")
DEFAULT_MAX_AGE = 45.0


def process_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def beat(role: str, *, owner: str | None = None) -> None:
    """Upsert this process's row. A database error is the caller's to log."""
    if role not in ROLES:
        raise ValueError(f"unknown heartbeat role {role!r}")
    now = datetime.now(UTC)
    statement = insert(WorkerHeartbeat).values(
        owner=owner or process_owner(),
        role=role,
        last_seen_at=now,
        version=__version__,
    )
    statement = statement.on_conflict_do_update(
        index_elements=[WorkerHeartbeat.owner],
        set_={"role": role, "last_seen_at": now, "version": __version__},
    )
    with SessionLocal() as session:
        session.execute(statement)
        session.commit()


def last_seen(role: str) -> datetime | None:
    """Newest heartbeat of `role`, or None when that role has never written."""
    with SessionLocal() as session:
        return session.scalar(
            select(func.max(WorkerHeartbeat.last_seen_at)).where(WorkerHeartbeat.role == role)
        )


def fresh(role: str, *, max_age: float = DEFAULT_MAX_AGE, now: datetime | None = None) -> bool:
    seen = last_seen(role)
    if seen is None:
        return False
    moment = now or datetime.now(UTC)
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=UTC)
    return moment - seen <= timedelta(seconds=max_age)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="costura.ops.heartbeat", description=__doc__)
    parser.add_argument("--role", choices=ROLES, required=True)
    parser.add_argument("--max-age", type=float, default=DEFAULT_MAX_AGE)
    args = parser.parse_args(argv)
    if fresh(args.role, max_age=args.max_age):
        return 0
    print(f"no fresh {args.role} heartbeat", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
