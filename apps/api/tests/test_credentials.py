"""Per-organization credentials: encryption round trip, validation, resolution order."""

from collections.abc import Callable

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from costura import accounts, credentials, secrets
from costura.config import get_settings
from costura.models import Organization, ProviderCredential
from costura.providers.anthropic.client import AnthropicAdminClient
from tests.conftest import account_of, anthropic_fixture_handler

GOOD_KEY = "sk-ant-admin01-good-key-1234"
BAD_KEY = "sk-ant-admin01-revoked-key-9999"


def _handler(request: httpx.Request) -> httpx.Response:
    if request.headers["x-api-key"] == BAD_KEY:
        return httpx.Response(
            401, json={"error": {"type": "authentication_error", "message": "invalid x-api-key"}}
        )
    return anthropic_fixture_handler(request)


def factory(key: str) -> AnthropicAdminClient:
    return AnthropicAdminClient(
        admin_key=key, transport=httpx.MockTransport(_handler), sleep=lambda _: None
    )


def factory_for(handler: httpx.MockTransport) -> credentials.ClientFactory:
    return lambda key: AnthropicAdminClient(
        admin_key=key,
        transport=handler,
        max_retries=0,
        sleep=lambda _: None,
    )


def timeout_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("timed out", request=request)


@pytest.fixture
def secret_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = secrets.generate_key()
    monkeypatch.setattr(get_settings(), "costura_secret_key", SecretStr(key))
    return key


@pytest.fixture
def no_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "anthropic_admin_key", None)


def test_encrypt_decrypt_round_trip(secret_key: str) -> None:
    settings = get_settings()
    token = secrets.encrypt(settings, GOOD_KEY)

    assert token != GOOD_KEY.encode()
    assert GOOD_KEY.encode() not in token
    assert secrets.decrypt(settings, token) == GOOD_KEY


def test_missing_secret_key_raises_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "costura_secret_key", None)

    with pytest.raises(secrets.SecretKeyMissing, match="just api::secret-generate"):
        secrets.encrypt(get_settings(), GOOD_KEY)


def test_wrong_secret_key_raises_decrypt_error(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "costura_secret_key", SecretStr(secrets.generate_key()))
    token = secrets.encrypt(settings, GOOD_KEY)
    monkeypatch.setattr(settings, "costura_secret_key", SecretStr(secrets.generate_key()))

    with pytest.raises(secrets.DecryptError, match="reconnect the provider key"):
        secrets.decrypt(settings, token)


def test_set_credential_validates_encrypts_and_stores_hint(
    db_session: Session, org_id: int, secret_key: str
) -> None:
    row = credentials.set_credential(
        db_session, get_settings(), org_id, "anthropic", GOOD_KEY, factory=factory
    )

    stored = db_session.scalar(select(ProviderCredential))
    assert stored is not None and stored.id == row.id
    assert stored.key_hint == "1234"
    assert stored.key_version == secrets.KEY_VERSION
    assert stored.last_validated_at is not None
    assert stored.last_error is None
    assert GOOD_KEY.encode() not in stored.ciphertext
    assert _stored_key(stored) == GOOD_KEY


def test_rejected_key_is_not_stored(db_session: Session, org_id: int, secret_key: str) -> None:
    with pytest.raises(credentials.InvalidCredential, match="rejected the key \\(HTTP 401\\)"):
        credentials.set_credential(
            db_session, get_settings(), org_id, "anthropic", BAD_KEY, factory=factory
        )

    assert db_session.scalar(select(ProviderCredential)) is None


def test_rejected_replacement_keeps_old_key_and_records_error(
    db_session: Session, org_id: int, secret_key: str
) -> None:
    row = credentials.set_credential(
        db_session, get_settings(), org_id, "anthropic", GOOD_KEY, factory=factory
    )

    with pytest.raises(credentials.InvalidCredential):
        credentials.set_credential(
            db_session,
            get_settings(),
            org_id,
            "anthropic",
            BAD_KEY,
            account_id=row.account_id,
            factory=factory,
        )

    stored = db_session.scalar(select(ProviderCredential))
    assert stored is not None
    assert stored.key_hint == "1234"
    assert "HTTP 401" in (stored.last_error or "")
    assert _stored_key(stored) == GOOD_KEY


@pytest.mark.parametrize(
    ("handler", "error"),
    [
        (
            lambda request: httpx.Response(429, request=request, json={"error": "rate limited"}),
            credentials.CredentialUnavailable,
        ),
        (
            lambda request: httpx.Response(503, request=request, json={"error": "down"}),
            credentials.CredentialUnavailable,
        ),
        (
            timeout_handler,
            credentials.CredentialUnavailable,
        ),
        (
            lambda request: httpx.Response(400, request=request, json={"error": "leaked-body"}),
            credentials.CredentialProtocolError,
        ),
        (
            lambda request: httpx.Response(200, request=request, content=b"not-json"),
            credentials.CredentialProtocolError,
        ),
    ],
)
def test_upstream_validation_failure_does_not_mutate_stored_credential(
    db_session: Session,
    org_id: int,
    secret_key: str,
    handler: Callable[[httpx.Request], httpx.Response],
    error: type[Exception],
) -> None:
    before = credentials.set_credential(
        db_session, get_settings(), org_id, "anthropic", GOOD_KEY, factory=factory
    )
    snapshot = (
        before.ciphertext,
        before.key_hint,
        before.last_validated_at,
        before.last_error,
    )

    with pytest.raises(error) as info:
        credentials.set_credential(
            db_session,
            get_settings(),
            org_id,
            "anthropic",
            "sk-ant-admin01-replacement",
            factory=factory_for(httpx.MockTransport(handler)),
        )
    # The message reaches the browser as `detail`: the provider's response body stays out.
    assert "leaked-body" not in str(info.value) and "body=" not in str(info.value)

    db_session.refresh(before)
    assert (
        before.ciphertext,
        before.key_hint,
        before.last_validated_at,
        before.last_error,
    ) == snapshot


def test_empty_key_is_rejected_before_any_request(
    db_session: Session, org_id: int, secret_key: str
) -> None:
    with pytest.raises(credentials.InvalidCredential, match="empty"):
        credentials.set_credential(
            db_session, get_settings(), org_id, "anthropic", "   ", factory=factory
        )


def test_resolve_prefers_stored_over_environment(
    db_session: Session, org_id: int, secret_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "anthropic_admin_key", SecretStr("sk-ant-admin01-env"))
    assert credentials.resolve_key(
        db_session, get_settings(), org_id, "anthropic", account_of(db_session, org_id, "anthropic")
    ) == (
        "sk-ant-admin01-env",
        "environment",
    )
    assert credentials.connection(
        db_session, get_settings(), org_id, "anthropic", account_of(db_session, org_id, "anthropic")
    ).source == ("environment")

    credentials.set_credential(
        db_session, get_settings(), org_id, "anthropic", GOOD_KEY, factory=factory
    )

    assert credentials.resolve_key(
        db_session, get_settings(), org_id, "anthropic", account_of(db_session, org_id, "anthropic")
    ) == (
        GOOD_KEY,
        "stored",
    )
    conn = credentials.connection(
        db_session, get_settings(), org_id, "anthropic", account_of(db_session, org_id, "anthropic")
    )
    assert conn.connected and conn.source == "stored" and conn.key_hint == "1234"


def test_environment_key_is_scoped_to_costura_org_across_two_organizations(
    db_session: Session, org_id: int, secret_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "costura_org", "default")
    monkeypatch.setattr(settings, "anthropic_admin_key", SecretStr("sk-ant-admin01-env"))
    other = Organization(slug="other", name="Other")
    db_session.add(other)
    db_session.commit()

    assert credentials.resolve_key(
        db_session, settings, org_id, "anthropic", account_of(db_session, org_id, "anthropic")
    ) == (
        "sk-ant-admin01-env",
        "environment",
    )
    with pytest.raises(credentials.NoCredential):
        credentials.resolve_key(
            db_session,
            settings,
            other.id,
            "anthropic",
            account_of(db_session, other.id, "anthropic"),
        )
    assert (
        credentials.connection(
            db_session,
            settings,
            other.id,
            "anthropic",
            account_of(db_session, other.id, "anthropic"),
        ).connected
        is False
    )

    credentials.set_credential(
        db_session, settings, other.id, "anthropic", GOOD_KEY, factory=factory
    )
    assert credentials.resolve_key(
        db_session, settings, other.id, "anthropic", account_of(db_session, other.id, "anthropic")
    ) == (
        GOOD_KEY,
        "stored",
    )
    assert (
        credentials.connection(
            db_session,
            settings,
            other.id,
            "anthropic",
            account_of(db_session, other.id, "anthropic"),
        ).source
        == "stored"
    )


def test_no_credential_anywhere_raises(db_session: Session, org_id: int, no_env_key: None) -> None:
    with pytest.raises(credentials.NoCredential, match="web settings page"):
        credentials.get_client(
            db_session,
            get_settings(),
            org_id,
            "anthropic",
            account_of(db_session, org_id, "anthropic"),
            factory=factory,
        )

    conn = credentials.connection(
        db_session, get_settings(), org_id, "anthropic", account_of(db_session, org_id, "anthropic")
    )
    assert not conn.connected and conn.source is None and conn.key_hint is None


def test_clear_credential(db_session: Session, org_id: int, secret_key: str) -> None:
    credentials.set_credential(
        db_session, get_settings(), org_id, "anthropic", GOOD_KEY, factory=factory
    )

    assert (
        credentials.clear_credential(
            db_session, org_id, "anthropic", account_of(db_session, org_id, "anthropic")
        )
        is True
    )
    assert (
        credentials.clear_credential(
            db_session, org_id, "anthropic", account_of(db_session, org_id, "anthropic")
        )
        is False
    )
    assert db_session.scalar(select(ProviderCredential)) is None


def _stored_key(row: ProviderCredential) -> str:
    context = secrets.credential_context(row.organization_id, row.provider, row.account_id)
    return secrets.decrypt_bound(get_settings(), context, row.ciphertext)


def test_a_ciphertext_moved_to_another_row_does_not_decrypt(
    db_session: Session, org_id: int, secret_key: str
) -> None:
    first = credentials.set_credential(
        db_session, get_settings(), org_id, "anthropic", GOOD_KEY, factory=factory
    )
    other = accounts.create_account(db_session, org_id, "anthropic", label="Second")
    second = ProviderCredential(
        organization_id=org_id,
        provider="anthropic",
        account_id=other.id,
        key_digest="copied",
        ciphertext=first.ciphertext,
        key_hint="1234",
    )
    db_session.add(second)
    db_session.flush()

    with pytest.raises(secrets.ContextMismatch):
        credentials.resolve_key(db_session, get_settings(), org_id, "anthropic", second.account_id)
    key, source = credentials.resolve_key(
        db_session, get_settings(), org_id, "anthropic", first.account_id
    )
    assert (key, source) == (GOOD_KEY, "stored")


def test_a_row_written_before_binding_reads_until_rotation_binds_it(
    db_session: Session, org_id: int, secret_key: str
) -> None:
    row = credentials.set_credential(
        db_session, get_settings(), org_id, "anthropic", GOOD_KEY, factory=factory
    )
    row.ciphertext = secrets.encrypt(get_settings(), GOOD_KEY)
    context = secrets.credential_context(row.organization_id, row.provider, row.account_id)
    assert not secrets.is_bound(get_settings(), context, row.ciphertext)
    assert _stored_key(row) == GOOD_KEY

    row.ciphertext = secrets.reencrypt(None, get_settings(), row.ciphertext, context)
    assert secrets.is_bound(get_settings(), context, row.ciphertext)
    assert _stored_key(row) == GOOD_KEY
    with pytest.raises(secrets.ContextMismatch):
        secrets.reencrypt(None, get_settings(), row.ciphertext, "credential|0|x|0")
