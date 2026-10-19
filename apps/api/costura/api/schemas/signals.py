from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

SignalKindOut = Literal[
    "anomaly",
    "budget",
    "sync_stale",
    "webhook_failing",
    "model_retiring",
    "near_limit",
    "idle_seat",
    "seat_no_limit",
    "unit_cost_up",
    "no_owner",
    "no_limit",
    "owner_left",
    "idle_active",
    "new_key",
]
InboxSignalKind = Literal[
    "budget",
    "sync_stale",
    "webhook_failing",
    "model_retiring",
    "near_limit",
    "idle_seat",
    "seat_no_limit",
    "unit_cost_up",
    "no_owner",
    "no_limit",
    "owner_left",
    "idle_active",
    "new_key",
]


class SignalFields(BaseModel):
    provider: str
    entity_kind: str
    entity_id: str
    label: str
    detail: str
    dollars_at_risk: str
    currency: str
    owner: str | None
    owner_role: str | None
    detected_at: datetime
    reference: str
    # Times this entity's signal opened in the last 90 days, this one included; 0 before the
    # worker's history pass has seen it.
    occurrences: int


class SignalOut(SignalFields):
    kind: SignalKindOut


class ClosedSignalOut(BaseModel):
    kind: SignalKindOut
    provider: str
    entity_kind: str
    entity_id: str
    label: str
    detail: str
    dollars_at_risk: str
    currency: str
    opened_at: datetime
    closed_at: datetime
    hours_open: str


class SignalHistoryOut(BaseModel):
    # Signals closed in the last 90 days, newest first.
    items: list[ClosedSignalOut]


SnoozeKind = Literal[
    "no_owner", "no_limit", "owner_left", "idle_active", "new_key", "idle_seat", "seat_no_limit"
]


class SnoozeOut(BaseModel):
    kind: SnoozeKind
    provider: str
    key_id: str
    until: date
    note: str | None


class SnoozeIn(BaseModel):
    kind: SnoozeKind
    key_id: str = Field(min_length=1, max_length=255)
    days: Literal[7, 30, 90]
    note: str | None = Field(default=None, max_length=280)


class SignalsOut(BaseModel):
    items: list[SignalOut]
    total: int
    # Key gaps a member snoozed that have not come back yet; they are not in `items`.
    snoozed: list[SnoozeOut] = []


class InboxSignalOut(SignalFields):
    kind: InboxSignalKind
    # What a read mark names: the budget alert id for a budget, `reference` otherwise.
    read_reference: str
    read_at: datetime | None


class SignalReadIn(BaseModel):
    kind: InboxSignalKind
    provider: str = Field(min_length=1, max_length=64)
    read_reference: str = Field(min_length=1, max_length=255)
