"""Provider accounts: the named connection of one organization to one provider."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from costura.account_settings import CursorAccountSettings, copilot_logins, cursor_settings
from costura.errors import DomainError, InvalidInput
from costura.models import ProviderAccount, ProviderCredential
from costura.models.account import LABEL_MAX_LENGTH
from costura.providers.registry import get_spec
from costura.providers.spec import AccountInfo


class InvalidLabel(ValueError, DomainError):
    """The label is blank or longer than `LABEL_MAX_LENGTH`."""

    status = 422
    code = "invalid_label"


class DuplicateLabel(ValueError, DomainError):
    """Another account of the same provider already carries the label."""

    status = 422
    code = "duplicate_label"


class DuplicateKey(ValueError, DomainError):
    """The key is already the credential of another account of the same provider."""

    status = 422
    code = "duplicate_key"


class UnknownAccount(LookupError, DomainError):
    """No account with this id belongs to the organization and provider."""

    status = 404
    code = "unknown_account"


class AccountInUse(ValueError, DomainError):
    """The account holds rows or a credential and cannot be removed without `force`."""

    status = 409
    code = "account_in_use"


def set_copilot_logins(account: ProviderAccount, logins: dict[str, str]) -> dict[str, str]:
    """Replace the login-to-e-mail table; a login mapped to an empty value is dropped."""
    if not get_spec(account.provider).login_mapping:
        raise InvalidInput("login mapping applies only to GitHub Copilot accounts")
    cleaned: dict[str, str] = {}
    for login, email in logins.items():
        key = login.strip().lower()
        value = email.strip().lower()
        if not key:
            continue
        if not value:
            continue
        if "@" not in value or " " in value:
            raise InvalidInput(f"{login}: e-mail must look like you@example.com")
        cleaned[key] = value
    account.settings = {**(account.settings or {}), "logins": cleaned}
    return cleaned


def set_cursor_settings(
    account: ProviderAccount,
    *,
    seat_price_usd: Decimal,
    include_included_in_business: bool,
    effective_from: date | None = None,
) -> CursorAccountSettings:
    if not get_spec(account.provider).account_settings:
        raise InvalidInput("Cursor settings apply only to Cursor accounts")
    if not seat_price_usd.is_finite() or seat_price_usd < 0:
        raise InvalidInput("seat_price_usd must be a non-negative finite amount")
    today = datetime.now(UTC).date()
    previous = cursor_settings(account)
    had_seat_price = "seat_price_usd" in (account.settings or {})
    if effective_from is not None:
        boundary = effective_from
    elif had_seat_price and seat_price_usd != previous.seat_price_usd:
        boundary = today + timedelta(days=1)
    elif had_seat_price:
        boundary = previous.effective_from
    else:
        boundary = today
    account.settings = {
        "seat_price_usd": float(seat_price_usd),
        "include_included_in_business": include_included_in_business,
    }
    account.settings_effective_from = max(boundary, account.created_at.date())
    return cursor_settings(account)


def key_digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def clean_label(label: str) -> str:
    cleaned = " ".join(label.split())
    if not cleaned:
        raise InvalidLabel("the account label is required")
    if len(cleaned) > LABEL_MAX_LENGTH:
        raise InvalidLabel(f"the account label is longer than {LABEL_MAX_LENGTH} characters")
    return cleaned


def list_accounts(
    session: Session, organization_id: int, provider: str | None = None
) -> list[ProviderAccount]:
    stmt = select(ProviderAccount).where(ProviderAccount.organization_id == organization_id)
    if provider is not None:
        stmt = stmt.where(ProviderAccount.provider == provider)
    return list(session.scalars(stmt.order_by(ProviderAccount.provider, ProviderAccount.id)).all())


def get_account(
    session: Session, organization_id: int, provider: str, account_id: int
) -> ProviderAccount:
    account = session.get(ProviderAccount, account_id)
    if (
        account is None
        or account.organization_id != organization_id
        or account.provider != provider
    ):
        raise UnknownAccount(f"no {provider} account {account_id} in this organization")
    return account


def labels_in_use(session: Session, organization_id: int, provider: str) -> set[str]:
    return set(
        session.scalars(
            select(ProviderAccount.label).where(
                ProviderAccount.organization_id == organization_id,
                ProviderAccount.provider == provider,
            )
        ).all()
    )


def default_label(
    session: Session,
    organization_id: int,
    provider: str,
    info: AccountInfo | None,
) -> str:
    """The label a new account gets when the admin types none: the provider's own name for
    the account, else the provider label, with " 2", " 3" appended until it is free."""
    base = get_spec(provider).label
    if info is not None and info.name:
        base = clean_label(info.name)
    taken = labels_in_use(session, organization_id, provider)
    if base not in taken:
        return base
    n = 2
    while f"{base} {n}" in taken:
        n += 1
    return f"{base} {n}"


def create_account(
    session: Session,
    organization_id: int,
    provider: str,
    *,
    label: str | None = None,
    info: AccountInfo | None = None,
) -> ProviderAccount:
    """Add one account of `provider`. `info` (what the provider reported for the key) sets
    the external id and the default label; an account already carrying the same external id
    is returned instead of duplicated."""
    get_spec(provider)
    external_id = info.external_id if info is not None else None
    if external_id is not None:
        existing = session.scalars(
            select(ProviderAccount).where(
                ProviderAccount.organization_id == organization_id,
                ProviderAccount.provider == provider,
                ProviderAccount.external_id == external_id,
            )
        ).one_or_none()
        if existing is not None:
            return existing
    chosen = (
        clean_label(label)
        if label is not None and label.strip()
        else default_label(session, organization_id, provider, info)
    )
    if chosen in labels_in_use(session, organization_id, provider):
        raise DuplicateLabel(f"a {provider} account labelled {chosen!r} already exists")
    account = ProviderAccount(
        organization_id=organization_id,
        provider=provider,
        label=chosen,
        external_id=external_id,
    )
    session.add(account)
    session.flush()
    return account


def rename_account(
    session: Session, organization_id: int, provider: str, account_id: int, label: str
) -> ProviderAccount:
    account = get_account(session, organization_id, provider, account_id)
    chosen = clean_label(label)
    if chosen != account.label and chosen in labels_in_use(session, organization_id, provider):
        raise DuplicateLabel(f"a {provider} account labelled {chosen!r} already exists")
    account.label = chosen
    session.flush()
    return account


def ensure_default_account(
    session: Session, organization_id: int, provider: str
) -> ProviderAccount:
    """The account rows land in when no account is named: the only one of the provider, or a
    new one labelled with the provider's name. Used by the environment-key fallback and by
    seeds, which know no console."""
    accounts = list_accounts(session, organization_id, provider)
    if len(accounts) == 1:
        return accounts[0]
    if not accounts:
        return create_account(session, organization_id, provider)
    for account in accounts:
        if account.label == get_spec(provider).label:
            return account
    return accounts[0]


def remove_account(
    session: Session,
    organization_id: int,
    provider: str,
    account_id: int,
    *,
    force: bool = False,
) -> None:
    """Delete the account and, through the foreign keys, every row synced under it. Without
    `force`, an account that still has a credential is refused: disconnect first."""
    account = get_account(session, organization_id, provider, account_id)
    credential = session.scalars(
        select(ProviderCredential).where(ProviderCredential.account_id == account.id)
    ).one_or_none()
    if credential is not None and not force:
        raise AccountInUse(f"{provider} account {account.label!r} is still connected")
    session.delete(account)
    session.flush()


__all__ = [
    "AccountInUse",
    "DuplicateKey",
    "DuplicateLabel",
    "InvalidLabel",
    "UnknownAccount",
    "copilot_logins",
    "create_account",
    "cursor_settings",
    "default_label",
    "ensure_default_account",
    "get_account",
    "key_digest",
    "list_accounts",
    "remove_account",
    "rename_account",
    "set_copilot_logins",
    "set_cursor_settings",
]
