"""Provider connections, accounts, keys, Codex credit prices and the manual sync."""

import logging

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy.orm import Session

from costura import (
    accounts,
    audit,
    connections,
    credentials,
    secrets,
)
from costura.api import schemas
from costura.api.deps import (
    ConcreteProviderDep,
    OrgDep,
    OwnedOrgDep,
    SessionDep,
    SettingsDep,
)
from costura.api.guard import VerifiedWriteDep, can_write
from costura.api.presenters.common import (
    account_out,
    provider_accounts,
    provider_list,
    provider_states,
)
from costura.config import Settings
from costura.errors import DomainError
from costura.models import ProviderCredential
from costura.providers.http import redact_and_cap
from costura.run_state import latest_runs

log = logging.getLogger("costura.api")
router = APIRouter()

KEY_STORAGE_UNCONFIGURED = (
    "key storage is not configured on this instance; ask whoever runs Costura to set "
    "COSTURA_SECRET_KEY"
)


CONNECT_FAILED = "the key could not be stored; the server log has the reason"


@router.get("/orgs/{org}/providers/{provider}/connection", response_model=schemas.ConnectionOut)
def connection(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    org: OrgDep,
    provider: ConcreteProviderDep,
) -> schemas.ConnectionOut:
    return _connection(request, session, settings, org.id, provider)


@router.put("/orgs/{org}/providers/{provider}/connection", response_model=schemas.ConnectionOut)
def connect(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    org: OwnedOrgDep,
    provider: ConcreteProviderDep,
    body: schemas.ConnectionIn,
    _guard: VerifiedWriteDep,
) -> schemas.ConnectionOut:
    """Validate the key with one provider request, then store it encrypted. Key rejection is
    422, temporary upstream failure is 503, an unexpected upstream response is 502, and a
    missing COSTURA_SECRET_KEY is 503. Until a scheduler run has succeeded for the account,
    storing a key queues its first sync; `first_sync_run_id` names that row. The worker
    executes it."""
    account_id = connections.only_account_id(session, org.id, provider)
    workspace_id = connections.workspace_id_for(
        session, org.id, provider, account_id, body.workspace_id
    )
    row = _store_key(
        session,
        settings,
        org.id,
        provider,
        body.admin_key,
        account_id,
        body.label,
        workspace_id,
    )
    connections.apply_account_settings(
        session,
        org.id,
        provider,
        row.account_id,
        body.seat_price_usd,
        body.include_included_in_business,
        initialize=account_id is None,
    )
    first_sync_run_id = connections.first_sync(session, org.id, provider, row.account_id)
    return _connection(
        request, session, settings, org.id, provider, first_sync_run_id=first_sync_run_id
    )


def _store_key(
    session: Session,
    settings: Settings,
    org_id: int,
    provider: str,
    admin_key: str,
    account_id: int | None,
    label: str | None = None,
    external_id: str | None = None,
) -> ProviderCredential:
    """Validate and store a key for one account (or a new one), mapping every failure to its
    status: 422 for a rejected key, a duplicate key or a bad label, 503 while the provider is
    unavailable or the key store is unconfigured, 502 on an unexpected upstream answer."""
    try:
        stored = credentials.set_credential(
            session,
            settings,
            org_id,
            provider,
            admin_key,
            account_id=account_id,
            label=label,
            external_id=external_id,
        )
    except DomainError:
        raise
    except secrets.SecretKeyMissing as exc:
        raise HTTPException(status_code=503, detail=KEY_STORAGE_UNCONFIGURED) from exc
    except RuntimeError as exc:
        log.error(
            "connect failed for org %s %s: %s", org_id, provider, redact_and_cap(str(exc), 500)
        )
        raise HTTPException(status_code=503, detail=CONNECT_FAILED) from exc
    audit.record(
        "provider_key_replaced" if account_id is not None else "provider_key_connected",
        session=session,
        org_id=org_id,
        target=f"{provider}:{stored.account_id}",
        provider=provider,
    )
    return stored


@router.delete("/orgs/{org}/providers/{provider}/connection", response_model=schemas.ConnectionOut)
def disconnect(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    org: OwnedOrgDep,
    provider: ConcreteProviderDep,
    _guard: VerifiedWriteDep,
) -> schemas.ConnectionOut:
    """Forget the key of the provider's only account; 409 with several accounts (disconnect
    each through the accounts routes)."""
    account_id = connections.only_account_id(session, org.id, provider)
    if account_id is not None:
        credentials.clear_credential(session, org.id, provider, account_id)
        _key_removed(session, org.id, provider, account_id)
    return _connection(request, session, settings, org.id, provider)


def _key_removed(session: Session, org_id: int, provider: str, account_id: int) -> None:
    audit.record(
        "provider_key_removed",
        session=session,
        org_id=org_id,
        target=f"{provider}:{account_id}",
        provider=provider,
    )


@router.get("/orgs/{org}/providers/{provider}/accounts", response_model=schemas.AccountsOut)
def list_provider_accounts(
    session: SessionDep, settings: SettingsDep, org: OrgDep, provider: ConcreteProviderDep
) -> schemas.AccountsOut:
    """Every account of the provider with the state of its key."""
    return schemas.AccountsOut(accounts=provider_accounts(session, settings, org.id, provider))


@router.post(
    "/orgs/{org}/providers/{provider}/accounts",
    response_model=schemas.AccountOut,
    status_code=201,
)
def add_provider_account(
    session: SessionDep,
    settings: SettingsDep,
    org: OwnedOrgDep,
    provider: ConcreteProviderDep,
    body: schemas.AccountIn,
    _guard: VerifiedWriteDep,
) -> schemas.AccountOut:
    """Connect one more account of the provider: the key is validated, the account labelled
    (`label`, else what the provider reports, else the provider's name) and its first sync
    enqueued. 422 when the key already connects another account or the label is taken."""
    workspace_id = connections.workspace_id_for(session, org.id, provider, None, body.workspace_id)
    row = _store_key(
        session,
        settings,
        org.id,
        provider,
        body.admin_key,
        None,
        body.label,
        workspace_id,
    )
    connections.apply_account_settings(
        session,
        org.id,
        provider,
        row.account_id,
        body.seat_price_usd,
        body.include_included_in_business,
        initialize=True,
    )
    first_sync_run_id = connections.first_sync(session, org.id, provider, row.account_id)
    return _account(
        session, settings, org.id, provider, row.account_id, first_sync_run_id=first_sync_run_id
    )


@router.patch(
    "/orgs/{org}/providers/{provider}/accounts/{account_id}", response_model=schemas.AccountOut
)
def rename_provider_account(
    session: SessionDep,
    settings: SettingsDep,
    org: OwnedOrgDep,
    provider: ConcreteProviderDep,
    account_id: int,
    body: schemas.AccountLabelIn,
    _guard: VerifiedWriteDep,
) -> schemas.AccountOut:
    accounts.rename_account(session, org.id, provider, account_id, body.label)
    connections.apply_account_settings(
        session,
        org.id,
        provider,
        account_id,
        body.seat_price_usd,
        body.include_included_in_business,
    )
    session.flush()
    return _account(session, settings, org.id, provider, account_id)


@router.put(
    "/orgs/{org}/providers/{provider}/accounts/{account_id}/key",
    response_model=schemas.AccountOut,
)
def replace_provider_account_key(
    session: SessionDep,
    settings: SettingsDep,
    org: OwnedOrgDep,
    provider: ConcreteProviderDep,
    account_id: int,
    body: schemas.ConnectionIn,
    _guard: VerifiedWriteDep,
) -> schemas.AccountOut:
    """Replace (or set) the key of one account; the account and its rows stay."""
    workspace_id = connections.workspace_id_for(
        session, org.id, provider, account_id, body.workspace_id
    )
    row = _store_key(
        session,
        settings,
        org.id,
        provider,
        body.admin_key,
        account_id,
        external_id=workspace_id,
    )
    connections.apply_account_settings(
        session,
        org.id,
        provider,
        account_id,
        body.seat_price_usd,
        body.include_included_in_business,
    )
    first_sync_run_id = connections.first_sync(session, org.id, provider, row.account_id)
    return _account(
        session, settings, org.id, provider, account_id, first_sync_run_id=first_sync_run_id
    )


@router.delete(
    "/orgs/{org}/providers/{provider}/accounts/{account_id}/key",
    response_model=schemas.AccountOut,
)
def disconnect_provider_account(
    session: SessionDep,
    settings: SettingsDep,
    org: OwnedOrgDep,
    provider: ConcreteProviderDep,
    account_id: int,
    _guard: VerifiedWriteDep,
) -> schemas.AccountOut:
    """Forget the account's key; its synced rows stay until the account is removed."""
    credentials.clear_credential(session, org.id, provider, account_id)
    _key_removed(session, org.id, provider, account_id)
    return _account(session, settings, org.id, provider, account_id)


@router.delete("/orgs/{org}/providers/{provider}/accounts/{account_id}", status_code=204)
def remove_provider_account(
    session: SessionDep,
    org: OwnedOrgDep,
    provider: ConcreteProviderDep,
    account_id: int,
    _guard: VerifiedWriteDep,
) -> Response:
    """Remove the account with its key and every row synced under it (cost, usage, allocated
    lines, inventory, runs, anomalies, projections). 409 while a sync of it is queued or
    running."""
    connections.remove_account(session, org.id, provider, account_id)
    audit.record(
        "provider_account_removed",
        session=session,
        org_id=org.id,
        target=f"{provider}:{account_id}",
        provider=provider,
    )
    return Response(status_code=204)


def _account(
    session: Session,
    settings: Settings,
    org_id: int,
    provider: str,
    account_id: int,
    *,
    first_sync_run_id: int | None = None,
) -> schemas.AccountOut:
    loaded = credentials.organization_connections(session, settings, org_id, [provider])
    for account, conn in loaded.accounts[provider]:
        if conn.account_id == account_id:
            last = latest_runs(session, org_id, [provider]).by_account.get((provider, account_id))
            return account_out(account, conn, last, settings, first_sync_run_id=first_sync_run_id)
    raise HTTPException(status_code=404, detail=f"no {provider} account {account_id}")


@router.get("/orgs/{org}/providers", response_model=list[schemas.ProviderOut])
def providers(session: SessionDep, settings: SettingsDep, org: OrgDep) -> list[schemas.ProviderOut]:
    """Every registered provider with its registry facts and this organization's connection
    state; the web builds the scope select and the settings cards from it."""
    return provider_list(session, settings, org.id)


def _connection(
    request: Request,
    session: Session,
    settings: Settings,
    org_id: int,
    provider: str,
    *,
    first_sync_run_id: int | None = None,
) -> schemas.ConnectionOut:
    state = provider_states(session, settings, org_id, [provider])[provider]
    conn = state.connection
    return schemas.ConnectionOut(
        provider=provider,
        connected=conn.connected,
        source=conn.source,
        key_hint=conn.key_hint,
        last_validated_at=conn.last_validated_at,
        last_error=conn.last_error,
        writes_enabled=can_write(request, session),
        secret_key_configured=settings.costura_secret_key is not None,
        first_sync_run_id=first_sync_run_id,
        schedule=state.schedule,
        accounts=state.accounts,
    )
