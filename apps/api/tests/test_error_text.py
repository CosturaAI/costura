"""Provider errors stored or logged for an operator stay short and token-free."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from costura import credentials
from costura.models import ProviderCredential, ProviderSyncRun
from costura.providers.http import (
    ProviderApiError,
    public_message,
    redact_and_cap,
    sanitize_stored_error,
    stored_exception_text,
)
from costura.providers.runs import close_run
from tests.conftest import ORG_ID, account_of

SECRET = "sk-ant-admin01-" + ("a" * 24)
START = datetime(2026, 8, 1, tzinfo=UTC)
END = datetime(2026, 8, 2, tzinfo=UTC)


def test_stored_error_drops_the_body_and_a_token_but_keeps_a_prefix_hint() -> None:
    body = "z" * 800
    cleaned = sanitize_stored_error(f"status=400 path=/v1/costs body='{SECRET} {body}'")
    assert cleaned is not None
    assert cleaned.startswith("status=400")
    assert "body=" not in cleaned
    assert SECRET not in cleaned
    assert len(cleaned) <= 500
    hint = sanitize_stored_error("use an sk-ant-admin... key")
    assert hint is not None and "sk-ant-admin" in hint
    assert sanitize_stored_error(None) is None
    assert sanitize_stored_error("   ") is None


def test_provider_log_line_is_capped_and_redacted() -> None:
    text = f"status=500 path=/v1 {SECRET} body='{'z' * 2000}'"
    logged = redact_and_cap(text, 500)
    assert SECRET not in logged
    assert "[redacted]" in logged
    assert len(logged) <= 500
    assert "z" * 2000 not in logged
    visible = public_message(
        ProviderApiError(
            text,
            status_code=500,
            public="Anthropic answered HTTP 500 to /v1 (request id unknown)",
        )
    )
    assert visible == "Anthropic answered HTTP 500 to /v1 (request id unknown)"
    assert SECRET not in visible
    assert "body=" not in visible


def test_close_run_and_last_error_keep_the_public_sentence(db_session: Session) -> None:
    account_id = account_of(db_session, ORG_ID, "anthropic")
    run = ProviderSyncRun(
        organization_id=ORG_ID,
        provider="anthropic",
        provider_account_id=account_id,
        endpoint="cost_report",
        window_start=START,
        window_end=END,
        status="running",
    )
    db_session.add(run)
    db_session.flush()
    close_run(
        db_session,
        run,
        pages_fetched=0,
        raw_results=0,
        rows_upserted=0,
        error=ProviderApiError(
            f"Anthropic request failed: status=401 path=/x body='leaked-body {SECRET}'",
            status_code=401,
            public="Anthropic answered HTTP 401 to /x (request id unknown)",
        ),
    )
    assert run.error == "Anthropic answered HTTP 401 to /x (request id unknown)"
    stored = stored_exception_text(RuntimeError(f"token {SECRET}"))
    assert SECRET not in stored
    assert "[redacted]" in stored

    row = ProviderCredential(
        organization_id=ORG_ID,
        provider="anthropic",
        account_id=account_id,
        key_digest="digest",
        ciphertext=b"cipher",
        key_hint="1234",
    )
    db_session.add(row)
    db_session.commit()
    credentials.record_error(db_session, account_id, f"status=401 path=/v1 body='{SECRET}'")
    db_session.refresh(row)
    assert row.last_error is not None
    assert "body=" not in row.last_error
    assert SECRET not in row.last_error
    assert "401" in row.last_error
