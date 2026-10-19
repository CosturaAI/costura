"""Connecting provider accounts and queueing their syncs, shared by the connection and sync
routers: the rules that sit between a stored key and the queue."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from costura import accounts, scheduler, scheduler_lock
from costura.errors import DomainError, InvalidInput
from costura.models import SchedulerRun
from costura.providers.registry import get_spec


class SyncActive(DomainError):
    """The account has a queued or running sync, so it cannot be removed. Answers 409."""

    status = 409
    code = "sync_active"


class SeveralAccounts(DomainError):
    """A provider-level key route met a provider with more than one account. Answers 409."""

    status = 409
    code = "several_accounts"


def enqueue_syncs(
    session: Session,
    org_id: int,
    providers: list[str],
    *,
    trigger: scheduler.Trigger,
    account_ids: dict[str, list[int]] | None = None,
) -> list[SchedulerRun]:
    """Persist one queued row per connected account (or the named accounts) and return them.
    The sync worker claims the rows; this process does not run them."""
    return scheduler.enqueue_runs(
        session, org_id, providers, trigger=trigger, account_ids=account_ids
    )


def only_account_id(session: Session, org_id: int, provider: str) -> int | None:
    """The provider's single account, None when it has none; `SeveralAccounts` otherwise."""
    existing = accounts.list_accounts(session, org_id, provider)
    if len(existing) > 1:
        raise SeveralAccounts(
            f"{get_spec(provider).label} has several accounts; use the accounts routes"
        )
    return existing[0].id if existing else None


def workspace_id_for(
    session: Session,
    org_id: int,
    provider: str,
    account_id: int | None,
    supplied: str | None,
) -> str | None:
    """The workspace a key belongs to, for providers that need one: required for a new
    account, fixed for an existing one."""
    if not get_spec(provider).requires_workspace:
        return None
    if account_id is None:
        if supplied is None:
            raise InvalidInput(f"workspace_id is required for {get_spec(provider).label}")
        return supplied
    account = accounts.get_account(session, org_id, provider, account_id)
    if supplied is not None and supplied.strip() != account.external_id:
        raise InvalidInput(
            f"workspace_id cannot be changed when replacing a {get_spec(provider).label} key"
        )
    return account.external_id


def apply_account_settings(
    session: Session,
    org_id: int,
    provider: str,
    account_id: int,
    seat_price_usd: Decimal | None,
    include_included_in_business: bool | None,
    *,
    initialize: bool = False,
) -> None:
    """Store the seat price and the business-plan switch for providers with account settings;
    a value left out keeps the current one."""
    if not get_spec(provider).account_settings or (
        seat_price_usd is None and include_included_in_business is None and not initialize
    ):
        return
    account = accounts.get_account(session, org_id, provider, account_id)
    current = accounts.cursor_settings(account)
    accounts.set_cursor_settings(
        account,
        seat_price_usd=seat_price_usd if seat_price_usd is not None else current.seat_price_usd,
        include_included_in_business=(
            include_included_in_business
            if include_included_in_business is not None
            else current.include_included_in_business
        ),
    )
    session.flush()


def has_succeeded_run(
    session: Session, org_id: int, provider: str, account_id: int | None = None
) -> bool:
    stmt = select(SchedulerRun.id).where(
        SchedulerRun.organization_id == org_id,
        SchedulerRun.provider == provider,
        SchedulerRun.status == "succeeded",
    )
    if account_id is not None:
        stmt = stmt.where(SchedulerRun.provider_account_id == account_id)
    return session.scalar(stmt.limit(1)) is not None


def first_sync(session: Session, org_id: int, provider: str, account_id: int) -> int | None:
    """Enqueue the account's first sync unless one of its cycles already succeeded."""
    if has_succeeded_run(session, org_id, provider, account_id):
        return None
    [run] = enqueue_syncs(
        session, org_id, [provider], trigger="connect", account_ids={provider: [account_id]}
    )
    return run.id


def remove_account(session: Session, org_id: int, provider: str, account_id: int) -> None:
    """Remove the account with its key and every row synced under it; `SyncActive` while a
    sync of it is queued or running."""
    active = session.scalar(
        select(SchedulerRun.id)
        .where(
            SchedulerRun.provider_account_id == account_id,
            SchedulerRun.status.in_(scheduler_lock.ACTIVE_RUN_STATUSES),
        )
        .limit(1)
    )
    if active is not None:
        raise SyncActive(f"sync running (scheduler run {active})")
    accounts.remove_account(session, org_id, provider, account_id, force=True)
    session.flush()
