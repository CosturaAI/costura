"""Count the SQL statements a block sends, for ceilings on the heavy reads."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event


@contextmanager
def counted_statements() -> Iterator[list[str]]:
    from costura.db import get_engine

    statements: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement)

    event.listen(get_engine(), "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(get_engine(), "before_cursor_execute", record)
