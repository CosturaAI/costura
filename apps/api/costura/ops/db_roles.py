"""Create or update the restricted database role the API, worker and scheduler use.

`python -m costura.ops.db_roles` runs right after `alembic upgrade head` in the production
migration job, connected as the schema owner (`DATABASE_URL`). It reads the role from
`POSTGRES_APP_USER` and `POSTGRES_APP_PASSWORD`. The role can log in, read and write rows,
and use sequences; it cannot create, alter or drop anything, and it cannot move the Alembic
revision or update or delete an audit event. Running it again re-applies the grants, so new
tables from a later migration and a restored dump are covered.
"""

import argparse
import os
import re
import sys
from collections.abc import Sequence

from psycopg import Connection, sql

from costura.ops import OperationError, run

ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
EXAMPLE_PASSWORD = "costura"


def _check(role: str, password: str) -> None:
    if not ROLE_NAME.fullmatch(role):
        raise OperationError("POSTGRES_APP_USER must be lowercase letters, digits and _")
    if len(password) < 12 or password == EXAMPLE_PASSWORD:
        raise OperationError("POSTGRES_APP_PASSWORD must be at least 12 characters")


def grant_runtime_role(connection: Connection, role: str, password: str) -> None:
    """Make `role` a login role with row access to every table in `public`. Commits."""
    _check(role, password)
    owner = connection.execute(sql.SQL("SELECT current_user")).fetchone()
    if owner is None or owner[0] == role:
        raise OperationError("POSTGRES_APP_USER must differ from the schema owner")
    ident = sql.Identifier(role)
    exists = connection.execute(
        sql.SQL("SELECT 1 FROM pg_roles WHERE rolname = %s"), (role,)
    ).fetchone()
    verb = sql.SQL("ALTER ROLE") if exists else sql.SQL("CREATE ROLE")
    connection.execute(
        sql.SQL(
            "{} {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS "
            "PASSWORD {}"
        ).format(verb, ident, sql.Literal(password))
    )
    database = connection.execute(sql.SQL("SELECT current_database()")).fetchone()
    assert database is not None
    statements = (
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database[0]), ident),
        sql.SQL("REVOKE ALL ON SCHEMA public FROM {}").format(ident),
        sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(ident),
        sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(
            ident
        ),
        sql.SQL("GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {}").format(
            ident
        ),
    )
    for statement in statements:
        connection.execute(statement)
    if connection.execute(sql.SQL("SELECT to_regclass('public.alembic_version')")).fetchone() != (
        None,
    ):
        connection.execute(
            sql.SQL("REVOKE INSERT, UPDATE, DELETE ON public.alembic_version FROM {}").format(ident)
        )
    if connection.execute(sql.SQL("SELECT to_regclass('public.audit_events')")).fetchone() != (
        None,
    ):
        connection.execute(
            sql.SQL("REVOKE UPDATE, DELETE, TRUNCATE ON public.audit_events FROM {}").format(ident)
        )
    connection.commit()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="costura.ops.db_roles", description=__doc__)
    parser.parse_args(argv)

    def operation() -> int:
        from costura.db import get_engine

        role = os.environ.get("POSTGRES_APP_USER", "").strip()
        password = os.environ.get("POSTGRES_APP_PASSWORD", "")
        if not role or not password:
            raise OperationError("set POSTGRES_APP_USER and POSTGRES_APP_PASSWORD")
        raw = get_engine().raw_connection()
        try:
            grant_runtime_role(raw.driver_connection, role, password)  # ty: ignore[invalid-argument-type]
        finally:
            raw.close()
        print(f"database role {role} can read and write rows; it cannot change the schema")
        return 0

    return run(operation)


if __name__ == "__main__":
    sys.exit(main())
