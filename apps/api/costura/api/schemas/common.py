"""Response shapes. Money travels as strings: `*_exact` fields keep the stored 8 decimals,
every other amount is rounded to cents for display; tokens are ints; timestamps are ISO 8601.

Shapes and money formatters more than one router answers with."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from costura.models.budget import BudgetAlertKind as BudgetAlertKind
from costura.models.budget import BudgetPeriod as BudgetPeriod
from costura.models.budget import BudgetScopeKind as BudgetScopeKind
from costura.models.intelligence import AnomalyKind as AnomalyKind
from costura.models.intelligence import AnomalySeriesKind as AnomalySeriesKind
from costura.models.intelligence import AnomalySeverity as AnomalySeverity
from costura.models.intelligence import AnomalyStatus as AnomalyStatus
from costura.models.owner import OwnerAssignmentKind as OwnerAssignmentKind
from costura.models.scheduler import SchedulerRunStatus as SchedulerRunStatus
from costura.models.scheduler import SchedulerTrigger as SchedulerTrigger
from costura.models.sync import SyncRunStatus as SyncRunStatus
from costura.spend.money import to_cents

Role = Literal["owner", "member", "viewer"]
SyncStepStatus = Literal["ok", "failed", "skipped"]


def money(value: Decimal | int | None) -> str | None:
    return None if value is None else f"{to_cents(Decimal(value)):.2f}"


def money_exact(value: Decimal | None) -> str | None:
    return None if value is None else f"{Decimal(value):.8f}"


class OrganizationOut(BaseModel):
    slug: str
    name: str
    is_demo: bool = False
    # Null on the demo organization, which nobody is a member of.
    role: Role | None = None
    created_at: datetime | None = None


class RunOut(BaseModel):
    id: int
    provider: str
    # The provider account the row came from and its label, for the "Provider - Account"
    # badge; None when the row spans accounts or predates them.
    provider_account_id: int | None = None
    provider_account_label: str | None = None
    endpoint: str
    status: SyncRunStatus
    window_start: datetime
    window_end: datetime
    started_at: datetime
    finished_at: datetime | None
    data_refreshed_at: datetime | None = None
    duration_seconds: float | None
    pages_fetched: int
    raw_results: int
    rows_upserted: int
    error: str | None


class ScheduleOut(BaseModel):
    last_run_id: int | None
    last_run_at: datetime | None
    last_finished_at: datetime | None
    status: str | None
    trigger: str | None
    error: str | None
    failed_steps: list[str]
    next_run_at: datetime | None
    schedule_at: str


class AccountOut(BaseModel):
    """One provider account of the organization: the console an admin key opens,
    with the state of that key. `connected` is per account; a provider is connected when any
    of its accounts is."""

    id: int
    provider: str
    label: str
    external_id: str | None
    connected: bool
    source: Literal["stored", "environment"] | None
    key_hint: str | None
    last_validated_at: datetime | None
    last_error: str | None
    schedule: ScheduleOut
    # Id of the first sync a connect enqueued; null on reads and when a run already succeeded.
    first_sync_run_id: int | None = None
    seat_price_usd: str | None = None
    include_included_in_business: bool | None = None
    settings_effective_from: date | None = None


class SyncStepOut(BaseModel):
    step: str
    month: str | None
    status: SyncStepStatus
    attempts: int
    detail: str | None
    duration_seconds: float


class ProviderOut(BaseModel):
    provider: str
    connection_type: str
    label: str
    vendor: str
    surface: str
    key_label: str
    key_prefix: str
    console_label: str
    console_url: str
    keys_console_url: str | None = None
    env_var: str
    attribution: str
    experimental: bool = False
    connected: bool
    source: Literal["stored", "environment"] | None
    key_hint: str | None
    last_validated_at: datetime | None
    last_error: str | None
    last_run: RunOut | None
    accounts: list[AccountOut] = []
