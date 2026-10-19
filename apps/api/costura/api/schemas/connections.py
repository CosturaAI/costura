"""Provider connection, account, key, credit price and sync shapes."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from costura.api.schemas.common import AccountOut, ScheduleOut, SchedulerRunStatus, SyncStepOut

AdminKey = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=512, pattern=r"^[\x21-\x7e]*$")
]


class AccountsOut(BaseModel):
    accounts: list[AccountOut]


class AccountIn(BaseModel):
    """Connect a new account: the key is validated first; the label defaults to what the
    provider reports for the key (Anthropic organization name, OpenRouter key label), else
    the provider's name."""

    admin_key: AdminKey
    label: str | None = None
    workspace_id: str | None = None
    seat_price_usd: Annotated[Decimal, Field(ge=0)] | None = None
    include_included_in_business: bool = True


class AccountLabelIn(BaseModel):
    label: str
    seat_price_usd: Annotated[Decimal, Field(ge=0)] | None = None
    include_included_in_business: bool | None = None


class ConnectionOut(BaseModel):
    """The provider's connection as one card: `connected` when any account is, the key fields
    of the first connected account, and every account under `accounts`."""

    provider: str
    connected: bool
    source: Literal["stored", "environment"] | None
    key_hint: str | None
    last_validated_at: datetime | None
    last_error: str | None
    writes_enabled: bool
    # False when COSTURA_SECRET_KEY is absent: the connect form cannot store a key.
    secret_key_configured: bool
    schedule: ScheduleOut
    # Id of the first sync a PUT enqueued; null on reads and when a run already succeeded.
    first_sync_run_id: int | None = None
    accounts: list[AccountOut] = []


class ConnectionIn(BaseModel):
    admin_key: AdminKey
    # Optional label for the account the key connects when the provider has none yet.
    label: str | None = None
    workspace_id: str | None = None
    seat_price_usd: Annotated[Decimal, Field(ge=0)] | None = None
    include_included_in_business: bool | None = None


class CreditPriceIn(BaseModel):
    effective_from: date
    price_per_credit: Annotated[Decimal, Field(gt=0)]


class CreditPriceOut(BaseModel):
    id: int
    organization_id: int
    provider_account_id: int
    effective_from: date
    price_per_credit: str
    created_by: int | None
    created_at: datetime


class SyncResultOut(BaseModel):
    provider: str
    provider_account_id: int | None = None
    run_id: int
    status: SchedulerRunStatus
    error: str | None
    steps: list[SyncStepOut]


class SyncResultsOut(BaseModel):
    """One scheduler run per provider the POST covered: one for a concrete provider, one per
    connected provider under `all`. The POST answers before lock acquisition, so every result
    is `queued` with no steps; `GET /orgs/{org}/setup` carries the live rows."""

    results: list[SyncResultOut]


class CopilotLoginsIn(BaseModel):
    # GitHub login -> e-mail; an empty e-mail removes the login from the table.
    logins: dict[str, str]


class CopilotLoginsOut(BaseModel):
    account_id: int
    logins: dict[str, str]
