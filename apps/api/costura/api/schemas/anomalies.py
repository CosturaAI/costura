"""Anomaly list, detail, evidence and alert inbox shapes."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from costura.api.schemas.common import (
    AnomalyKind,
    AnomalySeriesKind,
    AnomalySeverity,
    AnomalyStatus,
    SyncRunStatus,
)
from costura.api.schemas.signals import InboxSignalOut, SignalReadIn


class OwnerOut(BaseModel):
    email: str
    # "assigned in Costura", "created the key", "used their own login", "workspace admin" or
    # "organization owner".
    role: str
    # The key or workspace that led to this person, or "Costura organization".
    source: str
    # The note of an assignment made in Costura; null for owners read from the inventory.
    note: str | None = None


class RootCauseOut(BaseModel):
    kind: str
    id: str
    label: str
    actual: str
    baseline: str
    delta: str
    share: str | None = None


class AnomalyInvestigateOut(BaseModel):
    by: str
    filters: dict[str, str]
    measure: str = "billed_usd"


class AnomalyOut(BaseModel):
    explanation: str = ""
    # Why the anomaly was acknowledged or ignored, by whom and when; null while open.
    status_reason: str | None = None
    status_changed_by: str | None = None
    status_changed_at: datetime | None = None
    id: int
    provider: str
    # The provider account the row came from and its label, for the "Provider - Account"
    # badge; None when the row spans accounts or predates them.
    provider_account_id: int | None = None
    provider_account_label: str | None = None
    # "org" (the organization total), "api_key" or "account" (an OAuth login, the user
    # directly); workspaces and models appear only under `root_causes`.
    series_kind: AnomalySeriesKind
    series_id: str
    label: str
    # "spike" (above the upper bound), "drop" (below the lower one) or "new_principal" (a key
    # or login spending a share of the day before it has any history).
    kind: AnomalyKind
    # First and last day of the episode; equal for a one-day one. `ongoing` is true when the
    # last day is the last day with data, so the episode may still be running.
    day: str
    end_day: str
    ongoing: bool
    duration_days: int
    # The first day of the episode, against the baseline held for its whole run.
    actual: str
    expected: str
    upper_bound: str
    lower_bound: str | None
    # "weekday", "active_days", "trailing" or "new_series".
    baseline_method: str
    baseline_samples: int
    # Distance from the expected amount, always a magnitude: money above the baseline for a
    # spike, money missing from it for a drop.
    impact: str
    impact_percent: str | None
    # Impact as a percentage of the organization's spend of this provider from the first of
    # the month to the anomaly day ("12.34"); null when that total is zero.
    impact_share: str | None
    # Summed over the episode, and its worst single day.
    total_actual: str
    total_expected: str
    total_impact: str
    max_impact: str
    # The worst day's impact in units of the series' own spread; null for a `new_principal`.
    deviation: str | None
    severity: AnomalySeverity
    currency: str
    unit: str = "USD"
    status: AnomalyStatus
    root_causes: list[RootCauseOut]
    # Who to contact, most specific first (`costura.spend.owners`).
    owners: list[OwnerOut]
    # Why the provider inventory names nobody (the owners above are then the Costura
    # organization owners, a fallback); null when it names someone.
    owners_gap: str | None
    investigate: AnomalyInvestigateOut
    detected_at: datetime
    updated_at: datetime


class AnomaliesOut(BaseModel):
    month: str
    start: str
    end: str
    window_total: str
    open_count: int
    # Open anomalies of any day under the same provider and series filters.
    open_total: int = 0
    anomalies: list[AnomalyOut]
    # Rows matching the filters before `offset` and `limit`; `anomalies` holds at most `limit`.
    total: int = 0
    limit: int = 0
    offset: int = 0


class AnomalyStatusIn(BaseModel):
    status: AnomalyStatus
    reason: str | None = Field(default=None, max_length=280)


class SeriesPointOut(BaseModel):
    day: str
    amount: str
    # True on the days the detector took as baseline samples for the anomaly day.
    baseline_sample: bool


class SameDayAnomalyOut(BaseModel):
    id: int
    kind: AnomalyKind
    series_kind: AnomalySeriesKind
    series_id: str
    label: str
    impact: str
    status: AnomalyStatus


class BaselineSampleOut(BaseModel):
    day: str
    amount: str
    # The amount the median and the MAD read: the observed one carried along the trend, or the
    # expectation of an acknowledged episode the day falls inside.
    value: str
    adjusted: bool


class BaselineEvidenceOut(BaseModel):
    # "weekday" (same weekday over the trailing weeks), "active_days" (the non-zero days of
    # the trailing 28) or "trailing" (the trailing 28 days).
    method: str
    samples: list[BaselineSampleOut]
    # Slope of the samples in USD per week, "0.00" when the series is too young for one.
    trend_per_week: str
    sensitivity: str
    median: str
    mad: str
    margin_mad: str
    margin_relative: str
    margin_absolute: str
    # "mad", "relative" or "absolute": the candidate margin that fixed the upper bound.
    margin_rule: str
    margin: str
    upper_bound: str
    lower_bound: str
    # The day's amount, expected and upper bound as stored at detection, next to the values
    # recomputed from the data now; `matches_stored` is false after a re-sync changed the day.
    stored_actual: str
    stored_expected: str
    stored_upper_bound: str
    actual_now: str
    matches_stored: bool


class CheckOut(BaseModel):
    name: str
    passed: bool
    observed: str | None
    threshold: str | None
    # The sentence the detector records when the check fails.
    reason: str


class DayRowOut(BaseModel):
    key: str | None
    label: str
    amount: str | None
    tokens: dict[str, int]
    request_count: int
    cost_per_million: str | None
    trailing_average: str | None
    delta: str | None
    new: bool


class DayBreakdownOut(BaseModel):
    dimension: str
    rows: list[DayRowOut]


class UsageTotalsOut(BaseModel):
    amount: str
    tokens: dict[str, int]
    total_tokens: int
    request_count: int
    cost_per_million: str | None


class UnitEconomicsOut(BaseModel):
    day: UsageTotalsOut
    # Mean over the baseline sample days.
    baseline: UsageTotalsOut
    sample_days: int


class RunSummaryOut(BaseModel):
    id: int
    endpoint: str
    status: SyncRunStatus
    started_at: datetime
    finished_at: datetime | None
    rows_upserted: int


class DataQualityOut(BaseModel):
    runs: list[RunSummaryOut]
    cost_lines: int
    usage_lines: int
    allocated_lines: int
    unallocated_amount: str
    changed_since_detection: bool


class HistoryItemOut(BaseModel):
    id: int
    kind: AnomalyKind
    day: str
    actual: str
    impact: str
    status: AnomalyStatus


class DecompositionOut(BaseModel):
    change: str
    volume: str
    mix: str
    price: str
    top_model: str
    top_share_baseline: str
    top_share_day: str
    switch_day: str | None


class EvidenceOut(BaseModel):
    # Null when the series has no data before the day any more (everything was re-synced away).
    baseline: BaselineEvidenceOut | None
    checks: list[CheckOut]
    breakdowns: list[DayBreakdownOut]
    unit_economics: UnitEconomicsOut | None
    data_quality: DataQualityOut
    history: list[HistoryItemOut]
    decomposition: DecompositionOut | None = None


class AnomalyDetailOut(AnomalyOut):
    # Daily amounts of the flagged series over the eight weeks ending on the anomaly day.
    series: list[SeriesPointOut]
    same_day: list[SameDayAnomalyOut]
    evidence: EvidenceOut


class AlertItemOut(AnomalyOut):
    read_at: datetime | None


class AlertsOut(BaseModel):
    opted_in: bool
    # Unread anomalies, budget alerts and key gaps together; `unread_by_kind` splits it.
    unread_count: int
    items: list[AlertItemOut]
    signals: list[InboxSignalOut] = []
    unread_by_kind: dict[str, int] = {}


class AlertSettingsIn(BaseModel):
    opted_in: bool


class AnomalySettingsOut(BaseModel):
    sensitivity: Literal["low", "normal", "high"]
    detect_drops: bool
    detect_new_principals: bool
    retention_days: int
    idle_days: int
    new_key_days: int


class AnomalySettingsIn(BaseModel):
    sensitivity: Literal["low", "normal", "high"]
    detect_drops: bool
    detect_new_principals: bool
    retention_days: int = Field(ge=30, le=365)
    idle_days: int = Field(default=30, ge=7, le=365)
    new_key_days: int = Field(default=7, ge=1, le=90)


class AlertReadIn(BaseModel):
    anomaly_ids: list[int] = Field(default=[], max_length=500)
    signals: list[SignalReadIn] = Field(default=[], max_length=500)
    all: bool = False
