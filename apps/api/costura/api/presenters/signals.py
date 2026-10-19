from decimal import Decimal
from typing import cast

from sqlalchemy.orm import Session

from costura.api import schemas
from costura.api.presenters.common import series_label
from costura.api.schemas.signals import SignalKindOut
from costura.spend.inbox import InboxSignal, read_reference
from costura.spend.inventory import InventoryResolver
from costura.spend.owners import Owner, anomaly_owners, load_assignments, organization_owners
from costura.spend.signal_events import ClosedSignal, occurrences, signal_key
from costura.spend.signals import Signal


class SignalView:
    def __init__(self, session: Session, org_id: int, provider: str) -> None:
        self.resolver = InventoryResolver(session, org_id, provider)
        self.org_owners = organization_owners(session, org_id)
        self.assignments = load_assignments(session, org_id, provider)
        self.history = occurrences(session, org_id)

    def owner(self, signal: Signal) -> Owner | None:
        if signal.anomaly is not None:
            owners = anomaly_owners(
                self.resolver, signal.anomaly, self.org_owners, self.assignments
            )
            return owners[0] if owners else None
        if signal.budget is not None and signal.budget.scope_kind == "person":
            return Owner(email=signal.budget.scope_id, role="budgeted person", source="budget")
        if signal.posture is not None and signal.posture.owner is not None:
            return Owner(
                email=signal.posture.owner,
                role=signal.posture.owner_source or "owner",
                source=signal.entity_id,
            )
        return self.org_owners[0] if self.org_owners else None

    def label(self, signal: Signal) -> str:
        if signal.sync is not None:
            return signal.sync.account.label
        if signal.webhook is not None:
            return f"webhook to {signal.webhook.url_host}"
        if signal.entity_kind == "limit":
            return signal.entity_id
        if signal.seat is not None:
            return signal.seat.email
        if signal.budget is not None:
            if signal.budget.scope_kind == "org":
                return "organization total"
            if signal.budget.scope_kind == "team":
                return self.resolver.team_label(signal.entity_id)
            if signal.budget.scope_kind == "workspace":
                return self.resolver.workspace_label(signal.provider, signal.entity_id)
            return signal.entity_id
        return series_label(self.resolver, signal.provider, signal.entity_kind, signal.entity_id)


def _stack_detail(signal: Signal) -> str | None:
    """Details of the signals about imports, limits, models and the webhook."""
    if signal.sync is not None:
        return signal.sync.reason
    if signal.kind == "near_limit" and signal.limit_amount and signal.limit_used is not None:
        share = (signal.limit_used / signal.limit_amount * 100).quantize(Decimal("1"))
        amount = signal.limit_amount.quantize(Decimal("0.01"))
        return f"{share}% of the {amount} USD limit used, {signal.limit_note}"
    if signal.kind == "idle_seat" and signal.seat and signal.seat.last_active_at:
        return f"paid seat, last active {signal.seat.last_active_at.date().isoformat()}"
    if signal.kind == "unit_cost_up" and signal.unit_before and signal.unit_after:
        rise = ((signal.unit_after / signal.unit_before - 1) * 100).quantize(Decimal("1"))
        before = signal.unit_before.quantize(Decimal("0.01"))
        after = signal.unit_after.quantize(Decimal("0.01"))
        return f"cost per 1M tokens up {rise}% ({before} to {after} USD) at a steady volume"
    if signal.kind == "seat_no_limit":
        return "no spend limit for this member at the provider"
    if signal.kind == "model_retiring" and signal.retires_on is not None:
        return f"spends on {signal.model}, retired on {signal.retires_on.isoformat()}"
    if signal.webhook is not None and signal.webhook.last_failure_at is not None:
        last = signal.webhook.last_failure_at.strftime("%Y-%m-%d %H:%M UTC")
        return f"posts fail ({signal.webhook.last_error or 'error'}), last at {last}"
    return None


def detail_of(signal: Signal) -> str:
    if signal.anomaly is not None:
        return f"{signal.anomaly.kind}, {signal.anomaly.severity} severity"
    stack = _stack_detail(signal)
    if stack is not None:
        return stack
    if signal.alert is not None:
        if signal.alert.kind == "projection":
            return "projected over the budget"
        day = signal.alert.period_start
        if day is None:
            return f"{signal.alert.threshold}% of the budget"
        if signal.budget is not None and signal.budget.period == "week":
            return f"{signal.alert.threshold}% of the weekly budget, week of {day.isoformat()}"
        return f"{signal.alert.threshold}% of the daily budget on {day.isoformat()}"
    key = signal.key
    if signal.kind == "no_owner":
        return "no owner in the provider inventory or in Costura"
    if signal.kind == "no_limit":
        return "no spend limit at the provider"
    if signal.kind == "owner_left":
        return "its creator left the provider organization; the key still works"
    if signal.kind == "new_key" and key is not None and key.created_at is not None:
        return f"created {key.created_at.date().isoformat()}"
    if signal.kind == "idle_active" and signal.posture is not None:
        last = signal.posture.last_used_at
        return f"active, last used {last.date().isoformat()}" if last else "active, never used"
    return signal.kind.replace("_", " ")


def signal_out(view: SignalView, signal: Signal) -> schemas.SignalOut:
    owner = view.owner(signal)
    return schemas.SignalOut(
        kind=signal.kind,
        provider=signal.provider,
        entity_kind=signal.entity_kind,
        entity_id=signal.entity_id,
        label=view.label(signal),
        detail=detail_of(signal),
        dollars_at_risk=schemas.money(signal.dollars_at_risk) or "0.00",
        currency="USD",
        owner=owner.email if owner else None,
        owner_role=owner.role if owner else None,
        detected_at=signal.detected_at,
        reference=signal.reference,
        occurrences=view.history.get(signal_key(signal), 0),
    )


def closed_signal_out(closed: ClosedSignal) -> schemas.ClosedSignalOut:
    row = closed.event
    return schemas.ClosedSignalOut(
        kind=cast(SignalKindOut, row.kind),
        provider=row.provider,
        entity_kind=row.entity_kind,
        entity_id=row.entity_id,
        label=row.label,
        detail=row.detail,
        dollars_at_risk=schemas.money(row.dollars_at_risk) or "0.00",
        currency="USD",
        opened_at=row.opened_at,
        closed_at=row.closed_at or row.opened_at,
        hours_open=f"{closed.hours_open:.1f}",
    )


def inbox_signal_out(view: SignalView, item: InboxSignal) -> schemas.InboxSignalOut:
    return schemas.InboxSignalOut(
        **signal_out(view, item.signal).model_dump(),
        read_reference=read_reference(item.signal),
        read_at=item.read_at,
    )
