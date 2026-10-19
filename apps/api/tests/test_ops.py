"""Operational runners under `costura.ops`: exit codes, the scheduler process and the
encryption key."""

import io
import signal

import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from costura import ops, secrets
from costura.config import get_settings
from costura.ops import scheduler as scheduler_runner
from costura.ops import secret
from costura.providers.anthropic.client import AnthropicAdminClient
from tests.conftest import ORG_ID, anthropic_fixture_handler


def _stdin(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(text))


def _client(key: str) -> AnthropicAdminClient:
    return AnthropicAdminClient(
        admin_key=key,
        transport=httpx.MockTransport(anthropic_fixture_handler),
        sleep=lambda _: None,
    )


@pytest.mark.parametrize(
    ("interruption", "code", "message"),
    [
        (KeyboardInterrupt(), 130, "interrupted"),
        (ops.TerminationSignal(signal.SIGTERM), 143, "terminated by signal 15"),
        (ops.OperationError("bad input"), 1, "error: bad input"),
    ],
)
def test_run_uses_conventional_exit_codes(
    capsys: pytest.CaptureFixture[str], interruption: BaseException, code: int, message: str
) -> None:
    def interrupted() -> int:
        raise interruption

    assert ops.run(interrupted) == code
    assert message in capsys.readouterr().err


def test_secret_generate_prints_a_fernet_key(capsys: pytest.CaptureFixture[str]) -> None:
    assert secret.main(["generate"]) == 0
    key = capsys.readouterr().out.strip()
    assert len(key) == 44
    Fernet(key.encode())


def test_scheduler_once_requires_secret_key(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(get_settings(), "costura_secret_key", None)
    assert scheduler_runner.main(["--once"]) == 1
    assert "COSTURA_SECRET_KEY is not set" in capsys.readouterr().err


def test_scheduler_once_exits_one_when_a_cycle_failed(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from costura import scheduler
    from costura.sync_cycle import CycleResult

    monkeypatch.setattr(get_settings(), "costura_secret_key", SecretStr(secrets.generate_key()))
    failed = CycleResult(
        run_id=7,
        organization_id=ORG_ID,
        provider="anthropic",
        status="failed",
        error="cost failed",
    )
    monkeypatch.setattr(scheduler, "run_forever", lambda *_args, **_kwargs: iter([[failed]]))

    assert scheduler_runner.main(["--once"]) == 1
    out = capsys.readouterr().out
    assert "organization default: failed (scheduler run 7)" in out
    assert "cost failed" in out


def test_secret_rotate_reencrypts_every_credential_or_nothing(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from costura.credentials import set_credential
    from costura.models.credential import ProviderCredential

    old_key = secrets.generate_key()
    monkeypatch.setattr(get_settings(), "costura_secret_key", SecretStr(old_key))
    set_credential(
        db_session,
        get_settings(),
        ORG_ID,
        "anthropic",
        "sk-ant-admin01-rotate-me-0001",
        factory=_client,
    )
    before = db_session.scalar(select(ProviderCredential.ciphertext))
    db_session.commit()

    new_key = secrets.generate_key()
    monkeypatch.setattr(get_settings(), "costura_secret_key", SecretStr(new_key))
    _stdin(monkeypatch, "")
    assert secret.main(["rotate"]) == 1
    assert "rotation aborted" in capsys.readouterr().err

    _stdin(monkeypatch, "not-a-fernet-key")
    assert secret.main(["rotate"]) == 1
    assert "rotation aborted" in capsys.readouterr().err
    db_session.expire_all()
    assert db_session.scalar(select(ProviderCredential.ciphertext)) == before

    _stdin(monkeypatch, old_key)
    assert secret.main(["rotate"]) == 0
    assert (
        "re-encrypted 1 credential(s) and 0 webhook destination(s) with the current "
        "COSTURA_SECRET_KEY"
    ) in capsys.readouterr().out
    db_session.expire_all()
    row = db_session.scalar(select(ProviderCredential))
    assert row.ciphertext != before
    context = secrets.credential_context(row.organization_id, row.provider, row.account_id)
    assert secrets.decrypt_bound(get_settings(), context, row.ciphertext) == (
        "sk-ant-admin01-rotate-me-0001"
    )
    assert secret.main(["check"]) == 0
    assert "decrypted 1 stored secret(s): 1 with COSTURA_SECRET_KEY, 0 with" in (
        capsys.readouterr().out
    )
    assert "sk-ant" not in capsys.readouterr().out


def test_rotation_through_the_previous_key_keeps_reads_working_and_is_idempotent(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from costura.credentials import set_credential
    from costura.models.credential import ProviderCredential

    old_key, new_key = secrets.generate_key(), secrets.generate_key()
    monkeypatch.setattr(get_settings(), "costura_secret_key", SecretStr(old_key))
    set_credential(
        db_session,
        get_settings(),
        ORG_ID,
        "anthropic",
        "sk-ant-admin01-rotate-me-0002",
        factory=_client,
    )
    db_session.commit()

    monkeypatch.setattr(get_settings(), "costura_secret_key", SecretStr(new_key))
    monkeypatch.setattr(get_settings(), "costura_secret_key_previous", SecretStr(old_key))
    row = db_session.scalar(select(ProviderCredential))
    assert row is not None
    context = secrets.credential_context(row.organization_id, row.provider, row.account_id)
    assert secrets.decrypt_bound(get_settings(), context, row.ciphertext) == (
        "sk-ant-admin01-rotate-me-0002"
    )
    assert secrets.key_of(get_settings(), row.ciphertext) == "previous"
    assert secret.main(["check"]) == 0
    assert "0 with COSTURA_SECRET_KEY, 1 with COSTURA_SECRET_KEY_PREVIOUS" in (
        capsys.readouterr().out
    )

    _stdin(monkeypatch, "")
    assert secret.main(["rotate"]) == 0
    assert secret.main(["rotate"]) == 0
    capsys.readouterr()
    db_session.expire_all()
    row = db_session.scalar(select(ProviderCredential))
    assert row is not None and secrets.key_of(get_settings(), row.ciphertext) == "current"

    monkeypatch.setattr(get_settings(), "costura_secret_key_previous", None)
    assert secret.main(["check"]) == 0
    assert "1 with COSTURA_SECRET_KEY, 0 with" in capsys.readouterr().out
