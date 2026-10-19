"""Per-account provider credentials: store (after validating), resolve, clear.

An organization holds one credential per provider account. Resolution order for a client of
one account: the stored credential of that account, then the provider's environment key
(`ANTHROPIC_ADMIN_KEY`, `OPENROUTER_ADMIN_KEY`, `OPENAI_ADMIN_KEY`; the `just dev` fallback
for a single organization), which applies to the provider's first account only and only while
no account of that provider has a stored key. Client construction and validation dispatch
through the provider registry.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from costura import accounts, secrets
from costura.config import Settings
from costura.errors import DomainError, InvalidInput
from costura.models.account import ProviderAccount
from costura.models.credential import ProviderCredential
from costura.models.organization import Organization
from costura.providers.http import (
    ProviderApiError,
    ProviderAuthError,
    public_message,
    sanitize_stored_error,
)
from costura.providers.registry import AccountInfo, NotManagementKey, ProviderSpec, get_spec

log = logging.getLogger(__name__)

ClientFactory = Callable[[str], Any]
Source = Literal["stored", "environment"]

HINT_LENGTH = 4


class NoCredential(LookupError, DomainError):
    status = 422
    code = "no_credential"

    def __init__(self, provider: str) -> None:
        spec = get_spec(provider)
        super().__init__(
            f"no {spec.label} {spec.key_label} for this account; connect one in the web "
            "settings page"
        )
        self.provider = provider


class InvalidCredential(ValueError, DomainError):
    """The provider rejected the key during validation."""

    status = 422
    code = "invalid_credential"


class CredentialUnavailable(DomainError):
    """Validation could not finish because the provider was temporarily unavailable."""

    status = 503
    code = "provider_unavailable"


class CredentialProtocolError(DomainError):
    """Validation received an unexpected non-authentication provider response."""

    status = 502
    code = "provider_protocol_error"


@dataclass(frozen=True)
class Connection:
    connected: bool
    source: Source | None
    key_hint: str | None
    last_validated_at: datetime | None
    last_error: str | None


@dataclass(frozen=True)
class AccountConnection:
    """One account of a provider and the state of its key."""

    account_id: int
    label: str
    external_id: str | None
    connection: Connection


DISCONNECTED = Connection(
    connected=False, source=None, key_hint=None, last_validated_at=None, last_error=None
)


def default_factory(
    settings: Settings, provider: str, account_external_id: str | None = None
) -> ClientFactory:
    spec = get_spec(provider)
    return lambda key: spec.client_factory(settings, key, account_external_id)


def hint(key: str) -> str:
    return key[-HINT_LENGTH:] if len(key) >= HINT_LENGTH else key


def validate_key(
    key: str, provider: str, factory: ClientFactory, *, read_account: bool = False
) -> AccountInfo | None:
    """One read call chosen by the provider spec (Anthropic: the workspaces listing;
    OpenRouter: `GET /key` must report a management key). Raises InvalidCredential. With
    `read_account`, also returns what the provider reports about the account the key opens;
    that read is best-effort, a key that validated is stored even when the provider does not
    answer it (the account then takes the provider's name)."""
    spec = get_spec(provider)
    if not key.strip():
        raise InvalidCredential(f"the {spec.key_label} is empty")
    try:
        with factory(key) as client:
            spec.validate(client)
            if read_account and spec.account_info is not None:
                return _account_info(spec, client)
            return None
    except ProviderAuthError as exc:
        public_message(exc)
        raise InvalidCredential(
            f"{spec.label} rejected the key (HTTP {exc.status_code}). Check that it is a "
            f"{spec.key_label} ({spec.key_prefix}...), not a regular API key, and that it was "
            "not revoked."
        ) from exc
    except NotManagementKey as exc:
        raise InvalidCredential(f"{spec.label} accepted the key but {exc}") from exc
    except InvalidCredential:
        raise
    except ValueError as exc:
        raise InvalidInput(str(exc)) from exc
    except ProviderApiError as exc:
        status = exc.status_code
        # The browser gets the sentence without the response body; the body is in the log.
        public = public_message(exc)
        if exc.unavailable or status == 429 or (status is not None and status >= 500):
            raise CredentialUnavailable(
                f"{spec.label} could not validate the key because the provider is temporarily "
                f"unavailable: {public}"
            ) from exc
        raise CredentialProtocolError(
            f"{spec.label} returned an unexpected response while validating the key: {public}"
        ) from exc


def _account_info(spec: ProviderSpec, client: Any) -> AccountInfo | None:
    assert spec.account_info is not None
    try:
        return spec.account_info(client)
    except ProviderApiError as exc:
        log.debug("%s did not report the account behind the key: %s", spec.label, exc)
        return None


def _spec(provider: str) -> ProviderSpec:
    return get_spec(provider)


def _row(session: Session, account_id: int) -> ProviderCredential | None:
    return session.scalar(
        select(ProviderCredential).where(ProviderCredential.account_id == account_id)
    )


def _rows(session: Session, org_id: int, provider: str) -> list[ProviderCredential]:
    return list(
        session.scalars(
            select(ProviderCredential).where(
                ProviderCredential.organization_id == org_id,
                ProviderCredential.provider == provider,
            )
        ).all()
    )


def _environment_key(
    session: Session, settings: Settings, org_id: int, provider: str
) -> str | None:
    """Return the process key only for the organization selected by `COSTURA_ORG`, and only
    while no account of the provider holds a stored key."""
    slug = session.scalar(select(Organization.slug).where(Organization.id == org_id))
    if slug != settings.costura_org:
        return None
    if _rows(session, org_id, provider):
        return None
    return _environment_key_for(settings, provider)


def environment_account(
    session: Session, settings: Settings, org_id: int, provider: str
) -> ProviderAccount | None:
    """The account the environment key syncs into: the provider's first account, created
    with the provider's label when the organization has none yet. None when no environment
    key applies. The organization row is locked first, so two writers create one account.
    Only writers call this: enqueue, the scheduler pass and a cycle's account lookup."""
    if _environment_key(session, settings, org_id, provider) is None:
        return None
    session.scalar(select(Organization.id).where(Organization.id == org_id).with_for_update())
    spec = _spec(provider)
    external_id = spec.env_account(settings)
    existing = accounts.list_accounts(session, org_id, provider)
    if existing:
        account = existing[0]
        if external_id and account.external_id is None:
            account.external_id = external_id
    else:
        info = AccountInfo(external_id=external_id, name=None) if external_id else None
        account = accounts.create_account(session, org_id, provider, info=info)
    session.flush()
    return account


def _is_environment_account(
    session: Session, settings: Settings, org_id: int, provider: str, account_id: int
) -> bool:
    if _environment_key(session, settings, org_id, provider) is None:
        return False
    first = accounts.list_accounts(session, org_id, provider)
    return bool(first) and first[0].id == account_id


def _validate_remote(
    session: Session,
    settings: Settings,
    org_id: int,
    provider: str,
    key: str,
    *,
    account_id: int | None,
    external_id: str | None,
    factory: ClientFactory | None,
    row: ProviderCredential | None,
) -> tuple[Any, AccountInfo | None]:
    """The provider round trip: the account the key belongs to and what the provider reports
    about it. A rejected key records the error on the existing credential and is re-raised."""
    account = (
        accounts.get_account(session, org_id, provider, account_id)
        if account_id is not None
        else None
    )
    account_external_id = external_id or (account.external_id if account is not None else None)
    factory = factory or default_factory(settings, provider, account_external_id)
    try:
        info = validate_key(key, provider, factory, read_account=account_id is None)
    except InvalidCredential as exc:
        if row is not None:
            row.last_error = sanitize_stored_error(str(exc))
            session.commit()
        raise
    return account, info


def _resolve_account(
    session: Session,
    org_id: int,
    provider: str,
    account_id: int | None,
    label: str | None,
    info: AccountInfo | None,
    account: Any,
    row: ProviderCredential | None,
) -> tuple[int, ProviderCredential | None]:
    """A new key opens a new account; a replacement keeps the account it names."""
    if account_id is None:
        account = accounts.create_account(session, org_id, provider, label=label, info=info)
        account_id = account.id
        row = _row(session, account_id)
    return account_id, row


def set_credential(
    session: Session,
    settings: Settings,
    org_id: int,
    provider: str,
    key: str,
    *,
    account_id: int | None = None,
    label: str | None = None,
    external_id: str | None = None,
    factory: ClientFactory | None = None,
) -> ProviderCredential:
    """Validate, encrypt and store the key. Without `account_id` the key connects a new
    account, labelled `label` or what the provider reports for the key (else the provider's
    name), except when the provider's only account has no stored key yet (the environment
    fallback account, or one whose key was cleared): the key lands there. With `account_id`
    it replaces that account's key. A rejected key is not stored; when the account already
    has a credential its `last_error` records the rejection and its key is kept. The same key
    cannot connect two accounts of one provider."""
    key = key.strip()
    if settings.costura_secret_key is None:
        # Fail before the provider round trip: nothing could be stored anyway.
        raise secrets.SecretKeyMissing()
    if account_id is None and label is None:
        account_id = _lone_keyless_account(session, org_id, provider)
    row = _row(session, account_id) if account_id is not None else None
    account, info = _validate_remote(
        session,
        settings,
        org_id,
        provider,
        key,
        account_id=account_id,
        external_id=external_id,
        factory=factory,
        row=row,
    )
    digest = accounts.key_digest(key)
    holder = session.scalar(
        select(ProviderCredential).where(
            ProviderCredential.organization_id == org_id,
            ProviderCredential.provider == provider,
            ProviderCredential.key_digest == digest,
        )
    )
    if holder is not None and holder.account_id != account_id:
        other = session.get(ProviderAccount, holder.account_id)
        raise accounts.DuplicateKey(
            f"this key already connects the {_spec(provider).label} account "
            f"{other.label if other else holder.account_id!r}"
        )
    account_id, row = _resolve_account(
        session, org_id, provider, account_id, label, info, account, row
    )
    ciphertext = secrets.encrypt_bound(
        settings, secrets.credential_context(org_id, provider, account_id), key
    )
    now = datetime.now(UTC)
    if row is None:
        row = ProviderCredential(
            organization_id=org_id,
            provider=provider,
            account_id=account_id,
            key_digest=digest,
            ciphertext=ciphertext,
        )
        session.add(row)
    else:
        row.ciphertext = ciphertext
        row.key_digest = digest
    row.key_version = secrets.KEY_VERSION
    row.key_hint = hint(key)
    row.last_validated_at = now
    row.last_error = None
    stored_account = session.get(ProviderAccount, account_id)
    if stored_account is not None:
        stored_account.disconnected_at = None
    session.flush()
    return row


def _lone_keyless_account(session: Session, org_id: int, provider: str) -> int | None:
    existing = accounts.list_accounts(session, org_id, provider)
    if len(existing) == 1 and _row(session, existing[0].id) is None:
        return existing[0].id
    return None


def clear_credential(session: Session, org_id: int, provider: str, account_id: int) -> bool:
    """Forget the account's key. The account and its rows stay; `accounts.remove_account`
    drops them."""
    account = accounts.get_account(session, org_id, provider, account_id)
    row = _row(session, account_id)
    if row is None:
        return False
    session.delete(row)
    account.disconnected_at = datetime.now(UTC)
    session.flush()
    return True


def resolve_key(
    session: Session, settings: Settings, org_id: int, provider: str, account_id: int
) -> tuple[str, Source]:
    row = _row(session, account_id)
    if row is not None:
        context = secrets.credential_context(row.organization_id, row.provider, row.account_id)
        return secrets.decrypt_bound(settings, context, row.ciphertext), "stored"
    if _is_environment_account(session, settings, org_id, provider, account_id):
        env_key = _environment_key(session, settings, org_id, provider)
        if env_key is not None:
            return env_key, "environment"
    raise NoCredential(provider)


def get_client(
    session: Session,
    settings: Settings,
    org_id: int,
    provider: str,
    account_id: int,
    *,
    factory: ClientFactory | None = None,
) -> Any:
    key, _ = resolve_key(session, settings, org_id, provider, account_id)
    account = accounts.get_account(session, org_id, provider, account_id)
    return (factory or default_factory(settings, provider, account.external_id))(key)


def _connection_of(row: ProviderCredential) -> Connection:
    return Connection(
        connected=True,
        source="stored",
        key_hint=row.key_hint,
        last_validated_at=row.last_validated_at,
        last_error=row.last_error,
    )


def connection(
    session: Session, settings: Settings, org_id: int, provider: str, account_id: int
) -> Connection:
    row = _row(session, account_id)
    if row is not None:
        return _connection_of(row)
    if _is_environment_account(session, settings, org_id, provider, account_id):
        env_key = _environment_key(session, settings, org_id, provider)
        if env_key is not None:
            return Connection(
                connected=True,
                source="environment",
                key_hint=hint(env_key),
                last_validated_at=None,
                last_error=None,
            )
    return DISCONNECTED


@dataclass(frozen=True)
class OrganizationConnections:
    """Every account of an organization with the state of its key, loaded in three queries.
    `environment` holds the process key's connection for a provider whose fallback account
    does not exist yet."""

    accounts: dict[str, list[tuple[ProviderAccount, AccountConnection]]]
    environment: dict[str, Connection]


def organization_connections(
    session: Session, settings: Settings, org_id: int, providers: Sequence[str]
) -> OrganizationConnections:
    slug = session.scalar(select(Organization.slug).where(Organization.id == org_id))
    stored: dict[int, ProviderCredential] = {}
    stored_providers: set[str] = set()
    for row in session.scalars(
        select(ProviderCredential).where(
            ProviderCredential.organization_id == org_id,
            ProviderCredential.provider.in_(providers),
        )
    ):
        stored[row.account_id] = row
        stored_providers.add(row.provider)
    by_provider: dict[str, list[ProviderAccount]] = {name: [] for name in providers}
    for account in session.scalars(
        select(ProviderAccount)
        .where(ProviderAccount.organization_id == org_id, ProviderAccount.provider.in_(providers))
        .order_by(ProviderAccount.provider, ProviderAccount.id)
    ):
        by_provider[account.provider].append(account)
    result: dict[str, list[tuple[ProviderAccount, AccountConnection]]] = {}
    environment: dict[str, Connection] = {}
    for name in providers:
        env_key = (
            _environment_key_for(settings, name)
            if slug == settings.costura_org and name not in stored_providers
            else None
        )
        rows: list[tuple[ProviderAccount, AccountConnection]] = []
        for index, account in enumerate(by_provider[name]):
            row = stored.get(account.id)
            if row is not None:
                conn = _connection_of(row)
            elif index == 0 and env_key is not None:
                conn = _environment_connection(env_key)
            else:
                conn = DISCONNECTED
            rows.append(
                (
                    account,
                    AccountConnection(
                        account_id=account.id,
                        label=account.label,
                        external_id=account.external_id,
                        connection=conn,
                    ),
                )
            )
        result[name] = rows
        if env_key is not None and not rows:
            environment[name] = _environment_connection(env_key)
    return OrganizationConnections(accounts=result, environment=environment)


def _environment_key_for(settings: Settings, provider: str) -> str | None:
    spec = _spec(provider)
    if spec.env_account_id is not None and not spec.env_account(settings):
        return None
    return spec.env_key(settings)


def _environment_connection(env_key: str) -> Connection:
    return Connection(
        connected=True,
        source="environment",
        key_hint=hint(env_key),
        last_validated_at=None,
        last_error=None,
    )


def connections(
    session: Session, settings: Settings, org_id: int, provider: str
) -> list[AccountConnection]:
    """Every account of the provider with the state of its key, in creation order. Reads only:
    the environment fallback account is created by the writers (`environment_account`), so a
    page view never inserts a row."""
    loaded = organization_connections(session, settings, org_id, [provider])
    return [conn for _, conn in loaded.accounts[provider]]


def connected_accounts(
    session: Session, settings: Settings, org_id: int, provider: str
) -> list[AccountConnection]:
    return [c for c in connections(session, settings, org_id, provider) if c.connection.connected]


def provider_connected(session: Session, settings: Settings, org_id: int, provider: str) -> bool:
    """True when at least one account of the provider has a key, or the process key applies
    before its fallback account exists: the provider-level answer the setup checklist and the
    scope list ask for."""
    if connected_accounts(session, settings, org_id, provider):
        return True
    return _environment_key(session, settings, org_id, provider) is not None


def record_error(session: Session, account_id: int, message: str) -> None:
    """Called by the scheduler when the stored key stops working."""
    row = _row(session, account_id)
    if row is not None:
        row.last_error = sanitize_stored_error(message)
        session.commit()
