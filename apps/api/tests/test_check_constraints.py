"""CHECK constraints in the migrated schema match the models. `alembic check` does not compare
CHECK constraints, so a model edited without a revision (or the reverse) would pass it."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

import costura.models  # noqa: F401
from costura.db import Base, get_engine

PARITY_SCHEMA = "check_parity"

CONSTRAINTS = text(
    """
    SELECT rel.relname, con.conname, pg_get_constraintdef(con.oid)
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    JOIN pg_namespace ns ON ns.oid = rel.relnamespace
    WHERE con.contype = 'c' AND ns.nspname = :schema
    """
)


@pytest.fixture
def parity(migrated_database: None) -> Iterator[Connection]:
    with get_engine().connect() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{PARITY_SCHEMA}" CASCADE'))
        conn.execute(text(f'CREATE SCHEMA "{PARITY_SCHEMA}"'))
        conn.commit()
        try:
            Base.metadata.create_all(
                conn.execution_options(schema_translate_map={None: PARITY_SCHEMA})
            )
            conn.commit()
            yield conn
        finally:
            conn.rollback()
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{PARITY_SCHEMA}" CASCADE'))
            conn.commit()


def _checks(conn: Connection, schema: str) -> set[tuple[str, str, str]]:
    return {tuple(row) for row in conn.execute(CONSTRAINTS, {"schema": schema})}


def test_migrated_check_constraints_match_the_models(parity: Connection) -> None:
    migrated = _checks(parity, "public")
    declared = _checks(parity, PARITY_SCHEMA)
    assert declared, "the models declare no CHECK constraint"
    assert migrated - declared == set(), "in the migrations, not in the models"
    assert declared - migrated == set(), "in the models, not in the migrations"
