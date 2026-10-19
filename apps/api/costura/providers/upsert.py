from typing import Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from costura.db import Base

UPSERT_BATCH_SIZE = 500


def upsert_rows(
    session: Session,
    model: type[Base],
    rows: list[dict[str, Any]],
    *,
    constraint: str,
    replace_columns: tuple[str, ...],
    extra_set: dict[str, Any] | None = None,
) -> int:
    """`INSERT ... ON CONFLICT (constraint) DO UPDATE` with replace semantics.

    `replace_columns` take the incoming value; `sync_run_id` and `last_seen_at` always move;
    `first_seen_at` is left alone. Returns the number of rows written.
    """
    written = 0
    for offset in range(0, len(rows), UPSERT_BATCH_SIZE):
        batch = rows[offset : offset + UPSERT_BATCH_SIZE]
        statement = insert(model).values(batch)
        set_ = {column: getattr(statement.excluded, column) for column in replace_columns}
        set_["sync_run_id"] = statement.excluded.sync_run_id
        set_["last_seen_at"] = func.now()
        if extra_set:
            set_.update(extra_set)
        # rowcount is -1 for multi-row VALUES on psycopg; RETURNING gives an exact count.
        result = session.execute(
            statement.on_conflict_do_update(constraint=constraint, set_=set_).returning(
                model.__table__.c.id
            )
        )
        written += len(result.all())
    return written
