"""The restricted database role production processes connect as (`costura.ops.db_roles`)."""

import os
from collections.abc import Iterator

import psycopg
import pytest
from sqlalchemy import make_url, text
from sqlalchemy.orm import Session

from costura.ops import OperationError, db_roles

pytestmark = pytest.mark.integration

ROLE = f"costura_app_test_{os.getpid()}"
PASSWORD = "app-role-password-1"


def _connect(password: str = PASSWORD) -> psycopg.Connection:
    url = make_url(os.environ["DATABASE_URL"]).set(drivername="postgresql", username=ROLE)
    return psycopg.connect(url.set(password=password).render_as_string(hide_password=False))


@pytest.fixture
def role(db_session: Session) -> Iterator[str]:
    yield ROLE
    db_session.rollback()
    owner = db_session.execute(text("SELECT current_user")).scalar_one()
    db_session.execute(text(f'REASSIGN OWNED BY "{ROLE}" TO "{owner}"'))
    db_session.execute(text(f'DROP OWNED BY "{ROLE}"'))
    db_session.execute(text(f'DROP ROLE IF EXISTS "{ROLE}"'))
    db_session.commit()


def test_main_needs_the_role_in_the_environment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("POSTGRES_APP_USER", raising=False)
    monkeypatch.delenv("POSTGRES_APP_PASSWORD", raising=False)
    assert db_roles.main([]) == 1
    assert "POSTGRES_APP_USER" in capsys.readouterr().err


def test_runtime_role_reads_and_writes_rows_but_not_the_schema(
    role: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("POSTGRES_APP_USER", role)
    monkeypatch.setenv("POSTGRES_APP_PASSWORD", "first-password-1")
    assert db_roles.main([]) == 0
    monkeypatch.setenv("POSTGRES_APP_PASSWORD", PASSWORD)
    assert db_roles.main([]) == 0
    assert "cannot change the schema" in capsys.readouterr().out

    with pytest.raises(psycopg.OperationalError):
        _connect("first-password-1").close()

    with _connect() as conn:
        assert conn.execute("SELECT count(*) FROM organizations").fetchone() == (1,)
        conn.execute("INSERT INTO organizations (slug, name) VALUES ('role-check', 'Role')")
        conn.rollback()
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() is not None
        conn.execute("INSERT INTO audit_events (organization_id, event) VALUES (1, 'probe')")
        assert conn.execute("SELECT count(*) FROM audit_events").fetchone() is not None
        conn.rollback()
        for statement in (
            "UPDATE audit_events SET event = 'changed'",
            "DELETE FROM audit_events",
            "TRUNCATE audit_events",
            "CREATE TABLE role_probe (id int)",
            "ALTER TABLE organizations ADD COLUMN probe int",
            "UPDATE alembic_version SET version_num = version_num",
            "DROP TABLE organizations",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(statement)
            conn.rollback()


@pytest.mark.parametrize(
    ("name", "password", "message"),
    [
        ("Bad-Name", PASSWORD, "lowercase"),
        (ROLE, "short", "12 characters"),
        (ROLE, "costura", "12 characters"),
    ],
)
def test_grant_refuses_an_unsafe_role(name: str, password: str, message: str) -> None:
    with pytest.raises(OperationError, match=message):
        db_roles.grant_runtime_role(None, name, password)  # type: ignore[arg-type]


def test_grant_refuses_the_schema_owner(db_session: Session) -> None:
    owner = db_session.execute(text("SELECT current_user")).scalar_one()
    url = make_url(os.environ["DATABASE_URL"]).set(drivername="postgresql")
    with (
        psycopg.connect(url.render_as_string(hide_password=False)) as conn,
        pytest.raises(OperationError, match="differ from the schema owner"),
    ):
        db_roles.grant_runtime_role(conn, owner, PASSWORD)
