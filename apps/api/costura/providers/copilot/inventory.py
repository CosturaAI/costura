"""Snapshot the organization's Copilot seat holders as users.

GitHub identifies a seat holder by login and returns no e-mail. A person joins across
providers by e-mail, so the login is mapped through, in order: the login-to-e-mail table an
owner keeps on the account, then the public e-mail of the GitHub profile, else the login
itself (which joins nobody). A seat pending cancellation stays until GitHub drops it.
"""

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from costura import account_settings
from costura.models import ProviderAccount, ProviderLimit, ProviderUser
from costura.providers.copilot import PROVIDER
from costura.providers.copilot.client import GitHubBillingClient
from costura.providers.normalization import (
    loose_text,
    optional_day,
    optional_decimal,
    optional_timestamp,
    text,
)
from costura.providers.records import (
    LIMIT_REPLACE_COLUMNS,
    USER_REPLACE_COLUMNS,
    LimitRecord,
    UserRecord,
)
from costura.providers.runs import (
    InventorySummary,
    ScopedListingOptions,
    Target,
    run_listing,
    run_scoped_listing,
)

ENDPOINT_SEATS = "seats"
ENDPOINT_BUDGETS = "budgets"
SKIPPABLE_BUDGET_STATUSES = frozenset({403, 404})


def seat_login(item: dict[str, Any]) -> str | None:
    assignee = item.get("assignee")
    return loose_text(assignee.get("login")) if isinstance(assignee, dict) else None


def users_from_payload(
    payload: dict[str, Any], emails: dict[str, str] | None = None
) -> list[UserRecord]:
    emails = emails or {}
    records: list[UserRecord] = []
    for item in payload.get("seats", []):
        if not isinstance(item, dict):
            continue
        login = seat_login(item)
        if login is None:
            continue
        records.append(
            UserRecord(
                external_id=login,
                email=emails.get(login.lower()) or login,
                role=text(item.get("plan_type") or "unknown", field="plan_type"),
                added_at=optional_timestamp(item.get("created_at"), field="created_at"),
                provider=PROVIDER,
                last_active_at=optional_timestamp(
                    item.get("last_activity_at"), field="last_activity_at"
                ),
                pending_removal_at=pending_removal(item.get("pending_cancellation_date")),
            )
        )
    return records


def pending_removal(value: Any) -> datetime | None:
    if isinstance(value, str) and len(value) == len("2026-01-01"):
        return optional_day(value, field="pending_cancellation_date")
    return optional_timestamp(value, field="pending_cancellation_date")


def budgets_from_payload(payload: dict[str, Any]) -> list[LimitRecord]:
    records: list[LimitRecord] = []
    for item in payload.get("budgets", []):
        if not isinstance(item, dict):
            continue
        amount = optional_decimal(item.get("budget_amount"), field="budget_amount")
        if amount is None:
            continue
        records.append(
            LimitRecord(
                external_id=text(item.get("id"), field="id"),
                scope_kind=text(item.get("budget_scope"), field="budget_scope"),
                scope_name=loose_text(item.get("budget_entity_name"))
                or loose_text(item.get("user")),
                product=loose_text(item.get("budget_product_sku")),
                amount=amount,
                consumed=optional_decimal(item.get("consumed_amount"), field="consumed_amount"),
                enforcement="hard" if item.get("prevent_further_usage") is True else "soft",
                provider=PROVIDER,
            )
        )
    return records


def public_emails(client: GitHubBillingClient, logins: list[str]) -> dict[str, str]:
    """Public profile e-mails, for logins the owner has not mapped. One request per login."""
    found: dict[str, str] = {}
    for login in logins:
        email = loose_text(client.user(login).get("email"))
        if email and "@" in email:
            found[login.lower()] = email.strip().lower()
    return found


def run_inventory_sync(
    session: Session, target: Target, client: GitHubBillingClient
) -> list[InventorySummary]:

    account = session.get(ProviderAccount, target.account_id)
    if account is None:
        raise LookupError(f"Copilot account {target.account_id} not found")
    mapped = account_settings.copilot_logins(account)
    pages = list(client.seats_pages())
    logins = [
        login
        for page in pages
        for item in page.items
        if (login := seat_login(item)) is not None and login.lower() not in mapped
    ]
    emails = {**public_emails(client, logins), **mapped}
    seats = run_listing(
        session,
        target,
        PROVIDER,
        endpoint=ENDPOINT_SEATS,
        pages=lambda: iter(pages),
        normalize=lambda payload: users_from_payload(payload, emails),
        model=ProviderUser,
        constraint="uq_provider_users_external_id",
        replace_columns=USER_REPLACE_COLUMNS,
    )
    budgets = run_scoped_listing(
        session,
        target,
        PROVIDER,
        endpoint=ENDPOINT_BUDGETS,
        scopes=[client.org],
        pages=lambda _org: client.budgets_pages(),
        normalize=lambda payload, _org: budgets_from_payload(payload),
        scope_param="org",
        model=ProviderLimit,
        constraint="uq_provider_limits_external_id",
        replace_columns=LIMIT_REPLACE_COLUMNS,
        options=ScopedListingOptions(skippable_statuses=SKIPPABLE_BUDGET_STATUSES),
    )
    return [seats, budgets]


__all__ = [
    "ENDPOINT_BUDGETS",
    "ENDPOINT_SEATS",
    "budgets_from_payload",
    "public_emails",
    "run_inventory_sync",
    "seat_login",
    "users_from_payload",
]
