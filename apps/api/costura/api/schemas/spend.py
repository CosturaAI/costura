"""Month report, spend query, projection, people and activity shapes."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class MonthsOut(BaseModel):
    months: list[str]


class UsageRowOut(BaseModel):
    key: str | None
    label: str
    # Provider the row's lines came from; None only for sentinel rows spanning providers.
    provider: str | None
    details: dict[str, str]
    amount: str | None
    share: str | None
    tokens: dict[str, int]
    total_tokens: int
    web_search_requests: int
    # BYOK inference billed by another provider, not included in `amount`; null when the
    # row's lines report none (every Anthropic row).
    byok_amount: str | None = None
    # E-mail identity of the row's account across providers when the inventory knows it
    # (account, creator and person rows); the web links such rows to the person page.
    person: str | None = None
    # The provider account the row came from and its label, for the "Provider - Account"
    # badge; None when the row spans accounts or predates them.
    provider_account_id: int | None = None
    provider_account_label: str | None = None


class UsageOut(BaseModel):
    dimension: str
    allocated: bool
    cost_total: str | None
    rows: list[UsageRowOut]


class MoverRowOut(BaseModel):
    key: str | None
    label: str
    provider: str | None
    # The provider account the row came from and its label, for the "Provider - Account"
    # badge; None when the row spans accounts or predates them.
    provider_account_id: int | None = None
    provider_account_label: str | None = None
    amount: str
    previous_amount: str
    # Signed: positive when the month spends more than the previous one.
    delta: str
    # Null when the previous month spent nothing on the row, which `is_new` reports instead.
    change_percent: str | None
    is_new: bool
    is_gone: bool


class MoversOut(BaseModel):
    dimension: str
    # False when either month lacks an allocation; `rows` is then empty, since every delta
    # would be the whole amount of the allocated side.
    allocated: bool
    previous_month: str
    previous_start: str
    previous_end: str
    rows: list[MoverRowOut]


class AllocationOut(BaseModel):
    run_id: int
    allocated: str
    unallocated: str
    by_reason: dict[str, str]
    coverage_percent: str | None
    delta: str
    ok: bool


class SeriesOut(BaseModel):
    key: str | None
    label: str
    provider: str | None
    values: list[str]
    total: str


class DailySeriesOut(BaseModel):
    month: str
    dimension: str
    source: str
    days: list[str]
    series: list[SeriesOut]
    other: list[str] | None
    total: list[str]
    month_total: str


class QuerySeriesOut(BaseModel):
    keys: dict[str, str | None]
    labels: dict[str, str]
    provider: str | None
    values: list[str | int]
    total: str | int


class QueryComparisonOut(BaseModel):
    start: str
    end: str
    buckets: list[str]
    series: list[QuerySeriesOut]
    other: list[str | int] | None
    total: list[str | int]


class QueryProjectionOut(BaseModel):
    mode: Literal["linear"]
    lookback: int
    horizon: int
    buckets: list[str]
    anchor: str | int | None
    values: list[str | int]


class QueryOut(BaseModel):
    measure: str
    dimensions: list[str]
    start: str
    end: str
    interval: str
    source: str
    buckets: list[str]
    series: list[QuerySeriesOut]
    other: list[str | int] | None
    total: list[str | int]
    comparison: QueryComparisonOut | None
    projection: QueryProjectionOut | None


class QueriesOut(BaseModel):
    """One query result per requested measure, in the order the caller named them."""

    results: list[QueryOut]


class SummaryOut(BaseModel):
    month: str
    start: str
    end: str
    previous_start: str
    previous_end: str
    comparison_basis: Literal["full_month", "month_to_date", "preceding_period"]
    currency: str | None
    total: str
    previous_month: str
    previous_total: str | None
    change_percent: str | None
    days_in_month: int
    days_with_data: int
    last_day_with_data: str | None
    # Last day every account in scope has a succeeded cost sync for; the comparison and the
    # projection stop there when it is before the window's end. `data_stale`: a later cost
    # sync failed.
    complete_through: str | None = None
    data_stale: bool = False
    # Last day anomaly detection covered for every account in scope.
    detection_through: str | None = None
    # Pairs of accounts whose inventories overlap: their spend is likely counted twice.
    duplicate_accounts: list[str] = []
    # Costura's total minus the provider's total; the reconciliation page has the detail.
    provider_difference: str | None = None
    # Spend per currency when the scope bills in several; `total` is then not a usable sum.
    currency_totals: dict[str, str] | None = None
    daily_average: str | None
    is_current_month: bool
    projected_total: str | None
    top_keys_share: str | None
    top_key_count: int
    cache_read_share: str | None
    tokens: dict[str, int]
    allocation: AllocationOut | None
    provider_total: str | None
    provider_matches: bool | None
    # Inference routed through OpenRouter on the organization's own provider keys, billed by
    # those providers; not part of `total`. Null when no usage line in scope reports it.
    byok_total: str | None = None
    # Spend attributed to one e-mail in the `person` dimension, and its share of `total`.
    # Null until allocation runs.
    people_total: str | None = None
    people_share: str | None = None


class ActivityRowOut(BaseModel):
    family: str
    unit: str
    quantity: str
    requests: int
    billed_usd: str
    cost_per_unit: str | None


class BreakdownRowOut(BaseModel):
    label: str
    amount: str


class RawCheckOut(BaseModel):
    run_id: int
    raw_total: str
    delta: str
    ok: bool


class ProviderCheckOut(BaseModel):
    """Costura total against the provider's own ungrouped total (`cost_total` run)."""

    run_id: int
    provider_total: str
    delta: str
    ok: bool
    label: str = "Provider-reported usage"
    derived_seat_total: str = "0.00"


class KeyDeltaOut(BaseModel):
    api_key_id: str
    label: str
    provider_amount: str
    allocated_amount: str
    delta: str


class KeyCheckOut(BaseModel):
    """The provider's own per-key money (`costs_by_key` run) against the allocated rows per
    key; `keys_off` lists the keys outside the one-cent tolerance, largest delta first."""

    run_id: int
    keys_compared: int
    keys_off: list[KeyDeltaOut]
    provider_total: str
    allocated_total: str
    ok: bool


class AccountRefOut(BaseModel):
    id: int
    provider: str
    label: str


class ActivityCoverageOut(BaseModel):
    covered_families: list[str]
    missing_families: list[str]
    complete: bool


class CodexCreditCheckOut(BaseModel):
    workspace_credits: str
    user_credits: str
    delta: str
    missing_price_days: list[str]
    workspace_run_id: int
    user_run_id: int | None
    usd_cost_basis: str = "derived"
    ok: bool


class ReconcileOut(BaseModel):
    month: str
    currency: str | None
    costura_total: str
    costura_total_exact: str
    reported_total: str | None
    delta: str | None
    delta_percent: str | None
    matches: bool | None
    # Where `reported_total` came from: "query" (`?reported=`), "invoice" (the totals stored
    # for the calendar month), or None when there is nothing to compare with.
    reported_source: Literal["query", "invoice"] | None = None
    breakdown_dimension: str
    breakdown: list[BreakdownRowOut]
    raw_check: RawCheckOut | None
    provider_check: ProviderCheckOut | None
    allocation: AllocationOut | None
    # None while the provider publishes per-key money but no run or allocation covers the
    # month yet; `key_check_supported` is false for providers that never publish it.
    key_check: KeyCheckOut | None
    key_check_supported: bool
    token_totals: dict[str, int]
    activity_coverage: ActivityCoverageOut | None = None
    codex_credit_check: CodexCreditCheckOut | None = None
    data_refreshed_at: datetime | None = None
    user_attributed_total: str | None = None
    user_unattributed_total: str | None = None
    # The account the report is narrowed to (`?account=`), and every account of the scope so
    # the page can offer one card per account.
    account_id: int | None = None
    account_label: str | None = None
    accounts: list[AccountRefOut] = []


class PersonIdentityOut(BaseModel):
    """One provider account of a person: the inventory row that carries the e-mail."""

    provider: str
    external_id: str
    role: str
    added_at: datetime | None
    missing: bool
    # Live API keys the account created on this provider.
    keys_created: int


class PersonOut(BaseModel):
    """One e-mail across providers."""

    email: str
    identities: list[PersonIdentityOut]
    # Providers with at least one identity, in registry order.
    providers: list[str]


class ProjectedDayOut(BaseModel):
    day: str
    expected: str
    low: str
    high: str
    samples: int  # same-weekday amounts the band was drawn from


class ProjectionOut(BaseModel):
    provider: str
    series_kind: str
    series_id: str
    label: str
    as_of_day: str
    mtd: str
    projected_total: str
    low: str
    high: str
    currency: str
    days: list[ProjectedDayOut]
    computed_at: datetime


class ProjectionsOut(BaseModel):
    month: str
    by: str
    projections: list[ProjectionOut]
