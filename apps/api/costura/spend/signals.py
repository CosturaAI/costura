from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from costura.models import (
    AnomalySettings,
    ProviderApiKey,
    ProviderLimit,
    ProviderUser,
    SpendAllocatedLine,
    SpendAnomaly,
    SpendBudget,
    SpendBudgetAlert,
    WebhookDestination,
)
from costura.models.budget import PERSON_BUDGET_PROVIDER
from costura.spend.inventory import InventoryResolver
from costura.spend.posture import KeyPosture, PostureReader
from costura.spend.scope import ALL, provider_clause
from costura.spend.snoozes import active_snoozes
from costura.spend.sync_health import SyncHealth, unhealthy_accounts
from costura.spend.taxonomy import catalog_entry

SignalKind = Literal[
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
SIGNAL_LIMIT = 200
IDLE_DAYS = 30
NEW_KEY_DAYS = 7
SPEND_DAYS = 30
ACTIVE_KEY_STATUS = "active"
PERSONAL_KEY_PROVIDERS = frozenset({"anthropic"})


@dataclass(frozen=True)
class PostureThresholds:
    idle_days: int = IDLE_DAYS
    new_key_days: int = NEW_KEY_DAYS


@dataclass(frozen=True)
class Signal:
    kind: SignalKind
    provider: str
    entity_kind: str
    entity_id: str
    dollars_at_risk: Decimal
    detected_at: datetime
    reference: str
    anomaly: SpendAnomaly | None = None
    budget: SpendBudget | None = None
    alert: SpendBudgetAlert | None = None
    key: ProviderApiKey | None = None
    posture: KeyPosture | None = None
    sync: SyncHealth | None = None
    webhook: WebhookDestination | None = None
    model: str | None = None
    retires_on: date | None = None
    limit_amount: Decimal | None = None
    limit_used: Decimal | None = None
    limit_note: str | None = None
    seat: ProviderUser | None = None
    unit_before: Decimal | None = None
    unit_after: Decimal | None = None


def org_thresholds(session: Session, org_id: int) -> PostureThresholds:
    saved = session.get(AnomalySettings, org_id)
    if saved is None:
        return PostureThresholds()
    return PostureThresholds(idle_days=saved.idle_days, new_key_days=saved.new_key_days)


def collect_signals(
    session: Session,
    org_id: int,
    provider: str,
    *,
    today: date | None = None,
    thresholds: PostureThresholds | None = None,
    anomaly_limit: int | None = SIGNAL_LIMIT,
) -> list[Signal]:
    """Every open signal, most money first. Anomalies stop at `anomaly_limit` for display;
    webhook delivery passes None so an anomaly ranked past it is still posted."""
    today = today or datetime.now(UTC).date()
    signals = [
        *anomaly_signals(session, org_id, provider, limit=anomaly_limit),
        *budget_signals(session, org_id, provider, f"{today.year}-{today.month:02d}"),
        *sync_signals(session, org_id, provider, today),
        *webhook_signals(session, org_id, provider),
        *model_signals(session, org_id, provider, today),
        *limit_signals(session, org_id, provider),
        *seat_signals(session, org_id, provider, today, thresholds or PostureThresholds()),
        *unit_cost_signals(session, org_id, provider, today),
        *posture_signals(session, org_id, provider, today, thresholds or PostureThresholds()),
    ]
    return sort_signals(signals)


def sort_signals(signals: list[Signal]) -> list[Signal]:
    return sorted(signals, key=lambda s: (-s.dollars_at_risk, -s.detected_at.timestamp()))


def anomaly_signals(
    session: Session, org_id: int, provider: str, *, limit: int | None = SIGNAL_LIMIT
) -> list[Signal]:
    statement = (
        select(SpendAnomaly)
        .where(
            SpendAnomaly.organization_id == org_id,
            provider_clause(SpendAnomaly.provider, provider),
            SpendAnomaly.status == "open",
        )
        .order_by(SpendAnomaly.total_impact.desc(), SpendAnomaly.id)
    )
    rows = session.scalars(statement if limit is None else statement.limit(limit))
    return [
        Signal(
            kind="anomaly",
            provider=row.provider,
            entity_kind=row.series_kind,
            entity_id=row.series_id,
            dollars_at_risk=Decimal(row.total_impact),
            detected_at=row.detected_at,
            reference=str(row.id),
            anomaly=row,
        )
        for row in rows
    ]


def budget_signals(session: Session, org_id: int, provider: str, month: str) -> list[Signal]:
    scope = provider_clause(SpendBudget.provider, provider)
    if provider == ALL:
        scope = or_(scope, SpendBudget.provider == PERSON_BUDGET_PROVIDER)
    first = date.fromisoformat(f"{month}-01")
    week_of_first = first - timedelta(days=first.weekday())
    rows = session.execute(
        select(SpendBudgetAlert, SpendBudget)
        .join(SpendBudget, SpendBudget.id == SpendBudgetAlert.budget_id)
        .where(
            SpendBudget.organization_id == org_id,
            scope,
            or_(
                SpendBudgetAlert.month == month,
                and_(
                    SpendBudget.period == "week",
                    SpendBudgetAlert.period_start.between(week_of_first, first),
                ),
            ),
        )
        .order_by(SpendBudgetAlert.triggered_at)
    ).all()
    latest: dict[int, tuple[SpendBudgetAlert, SpendBudget]] = {}
    for alert, budget in rows:
        latest[budget.id] = (alert, budget)
    return [
        Signal(
            kind="budget",
            provider=budget.provider,
            entity_kind=budget.scope_kind,
            entity_id=budget.scope_id,
            dollars_at_risk=max(
                Decimal("0"), max(alert.spent, alert.projected or Decimal("0")) - alert.amount
            ),
            detected_at=alert.triggered_at,
            reference=str(budget.id),
            budget=budget,
            alert=alert,
        )
        for alert, budget in latest.values()
    ]


def sync_signals(session: Session, org_id: int, provider: str, today: date) -> list[Signal]:
    """One signal per connected account whose cost import needs a person; it closes on the
    next succeeded import."""
    return [
        Signal(
            kind="sync_stale",
            provider=health.account.provider,
            entity_kind="provider_account",
            entity_id=str(health.account.id),
            dollars_at_risk=health.dollars_at_risk,
            detected_at=health.detected_at,
            reference=str(health.account.id),
            sync=health,
        )
        for health in unhealthy_accounts(session, org_id, provider, today)
    ]


def seat_signals(
    session: Session, org_id: int, provider: str, today: date, thresholds: PostureThresholds
) -> list[Signal]:
    """Paid seats nobody uses (no activity for `idle_days`; a seat whose provider reports no
    activity at all is left alone) and members without a spend limit where the provider
    reports one per member. No money: a seat's price is not in the inventory."""
    users = session.scalars(
        select(ProviderUser).where(
            ProviderUser.organization_id == org_id,
            provider_clause(ProviderUser.provider, provider),
            ProviderUser.kind == "user",
            ProviderUser.missing_since.is_(None),
            ProviderUser.pending_removal_at.is_(None),
        )
    )
    snoozed = active_snoozes(session, org_id, provider, today)
    signals: list[Signal] = []
    for user in users:
        kinds: list[SignalKind] = []
        last = user.last_active_at
        if last is not None and (today - last.date()).days >= thresholds.idle_days:
            kinds.append("idle_seat")
        if user.limit_reported and user.spend_limit is None:
            kinds.append("seat_no_limit")
        for kind in kinds:
            if (kind, user.provider, user.external_id) in snoozed:
                continue
            signals.append(
                Signal(
                    kind=kind,
                    provider=user.provider,
                    entity_kind="user",
                    entity_id=user.external_id,
                    dollars_at_risk=Decimal("0"),
                    detected_at=user.last_seen_at,
                    reference=user.external_id,
                    seat=user,
                )
            )
    return signals


UNIT_RECENT_DAYS = 7
UNIT_BASE_DAYS = 28
UNIT_RISE = Decimal("1.3")
UNIT_FLOOR = Decimal("5")
PER_MILLION = Decimal("1000000")


def unit_cost_signals(session: Session, org_id: int, provider: str, today: date) -> list[Signal]:
    """Keys whose cost per million tokens over the last 7 days is 30% or more above the 28
    days before, at a volume within half to twice the usual: the price per token moved, not
    the use (a model switch or a new mix). Money is the extra paid over the 7 days."""
    recent_start = today - timedelta(days=UNIT_RECENT_DAYS)
    base_start = recent_start - timedelta(days=UNIT_BASE_DAYS)
    day = func.date_trunc("day", SpendAllocatedLine.period_start)
    recent = SpendAllocatedLine.period_start >= datetime.combine(
        recent_start, datetime.min.time(), UTC
    )
    rows = session.execute(
        select(
            SpendAllocatedLine.provider,
            SpendAllocatedLine.api_key_id,
            func.sum(SpendAllocatedLine.amount).filter(recent),
            func.sum(SpendAllocatedLine.tokens).filter(recent),
            func.sum(SpendAllocatedLine.amount).filter(~recent),
            func.sum(SpendAllocatedLine.tokens).filter(~recent),
            func.max(day),
        )
        .where(
            SpendAllocatedLine.organization_id == org_id,
            provider_clause(SpendAllocatedLine.provider, provider),
            SpendAllocatedLine.api_key_id.is_not(None),
            SpendAllocatedLine.period_start
            >= datetime.combine(base_start, datetime.min.time(), UTC),
            SpendAllocatedLine.period_start < datetime.combine(today, datetime.min.time(), UTC),
        )
        .group_by(SpendAllocatedLine.provider, SpendAllocatedLine.api_key_id)
    ).all()
    signals: list[Signal] = []
    for line_provider, key_id, amount7, tokens7, amount28, tokens28, last in rows:
        if key_id is None or not tokens7 or not tokens28 or amount7 is None or amount28 is None:
            continue
        amount7, amount28 = Decimal(amount7), Decimal(amount28)
        if amount7 < UNIT_FLOOR:
            continue
        weekly = Decimal(tokens28) / (UNIT_BASE_DAYS // UNIT_RECENT_DAYS)
        volume = Decimal(tokens7) / weekly if weekly else Decimal("0")
        if not Decimal("0.5") <= volume <= Decimal("2"):
            continue
        before = amount28 / Decimal(tokens28) * PER_MILLION
        after = amount7 / Decimal(tokens7) * PER_MILLION
        if before <= 0 or after < before * UNIT_RISE:
            continue
        signals.append(
            Signal(
                kind="unit_cost_up",
                provider=line_provider,
                entity_kind="api_key",
                entity_id=key_id,
                dollars_at_risk=((after - before) / PER_MILLION * Decimal(tokens7)).quantize(
                    Decimal("0.01")
                ),
                detected_at=last or datetime.now(UTC),
                reference=f"unit|{key_id}",
                unit_before=before,
                unit_after=after,
            )
        )
    return signals


NEAR_LIMIT = Decimal("0.8")


def limit_signals(session: Session, org_id: int, provider: str) -> list[Signal]:
    """Provider limits that cut requests off, at 80% used or more: an OpenRouter key's own
    limit, and the budgets a provider reports (GitHub). Money is what is left before the
    limit."""
    signals: list[Signal] = []
    keys = session.scalars(
        select(ProviderApiKey).where(
            ProviderApiKey.organization_id == org_id,
            provider_clause(ProviderApiKey.provider, provider),
            ProviderApiKey.status == ACTIVE_KEY_STATUS,
            ProviderApiKey.missing_since.is_(None),
            ProviderApiKey.spend_limit > 0,
            ProviderApiKey.limit_remaining.is_not(None),
        )
    )
    for key in keys:
        amount, remaining = key.spend_limit, key.limit_remaining
        if amount is None or remaining is None:
            continue
        used = amount - remaining
        if used / amount < NEAR_LIMIT:
            continue
        signals.append(
            Signal(
                kind="near_limit",
                provider=key.provider,
                entity_kind="api_key",
                entity_id=key.external_id,
                dollars_at_risk=max(Decimal("0"), remaining),
                detected_at=key.last_seen_at,
                reference=f"key|{key.external_id}",
                key=key,
                limit_amount=amount,
                limit_used=used,
                limit_note=f"resets {key.limit_reset}" if key.limit_reset else "hard limit",
            )
        )
    limits = session.scalars(
        select(ProviderLimit).where(
            ProviderLimit.organization_id == org_id,
            provider_clause(ProviderLimit.provider, provider),
            ProviderLimit.amount > 0,
            ProviderLimit.consumed.is_not(None),
        )
    )
    for limit in limits:
        if limit.consumed is None or limit.consumed / limit.amount < NEAR_LIMIT:
            continue
        signals.append(
            Signal(
                kind="near_limit",
                provider=limit.provider,
                entity_kind="limit",
                entity_id=limit.scope_name or limit.product or limit.external_id,
                dollars_at_risk=max(Decimal("0"), limit.amount - limit.consumed),
                detected_at=limit.last_seen_at,
                reference=f"limit|{limit.external_id}",
                limit_amount=limit.amount,
                limit_used=limit.consumed,
                limit_note=f"{limit.enforcement} limit",
            )
        )
    return signals


RETIRING_DAYS = 60
RECENT_USE_DAYS = 7


def model_signals(session: Session, org_id: int, provider: str, today: date) -> list[Signal]:
    """One signal per key still spending on a model the catalog retires within 60 days;
    it closes after a week without spend on that model."""
    start = datetime.combine(today - timedelta(days=SPEND_DAYS), datetime.min.time(), UTC)
    rows = session.execute(
        select(
            SpendAllocatedLine.provider,
            SpendAllocatedLine.api_key_id,
            SpendAllocatedLine.model,
            func.sum(SpendAllocatedLine.amount),
            func.max(SpendAllocatedLine.period_start),
        )
        .where(
            SpendAllocatedLine.organization_id == org_id,
            provider_clause(SpendAllocatedLine.provider, provider),
            SpendAllocatedLine.period_start >= start,
            SpendAllocatedLine.api_key_id.is_not(None),
            SpendAllocatedLine.model.is_not(None),
        )
        .group_by(
            SpendAllocatedLine.provider, SpendAllocatedLine.api_key_id, SpendAllocatedLine.model
        )
    ).all()
    signals: list[Signal] = []
    for line_provider, key_id, model, amount, last in rows:
        if key_id is None or model is None:
            continue
        entry = catalog_entry(model)
        retires = entry.retired_on if entry else None
        if retires is None or not today <= retires <= today + timedelta(days=RETIRING_DAYS):
            continue
        if last is None or last.date() < today - timedelta(days=RECENT_USE_DAYS) or not amount:
            continue
        signals.append(
            Signal(
                kind="model_retiring",
                provider=line_provider,
                entity_kind="api_key",
                entity_id=key_id,
                dollars_at_risk=Decimal(amount),
                detected_at=last,
                reference=f"{key_id}|{model}",
                model=model,
                retires_on=retires,
            )
        )
    return signals


def webhook_signals(session: Session, org_id: int, provider: str) -> list[Signal]:
    """The organization's webhook while its newest post failed; under `all` only, since the
    destination serves every provider."""
    if provider != ALL:
        return []
    row = session.get(WebhookDestination, org_id)
    if row is None or row.last_failure_at is None:
        return []
    if row.last_success_at is not None and row.last_success_at >= row.last_failure_at:
        return []
    return [
        Signal(
            kind="webhook_failing",
            provider=ALL,
            entity_kind="webhook",
            entity_id=row.url_host,
            dollars_at_risk=Decimal("0"),
            detected_at=row.last_failure_at,
            reference=row.url_host,
            webhook=row,
        )
    ]


def posture_signals(
    session: Session, org_id: int, provider: str, today: date, thresholds: PostureThresholds
) -> list[Signal]:
    keys = list(
        session.scalars(
            select(ProviderApiKey).where(
                ProviderApiKey.organization_id == org_id,
                provider_clause(ProviderApiKey.provider, provider),
                ProviderApiKey.status == ACTIVE_KEY_STATUS,
                ProviderApiKey.missing_since.is_(None),
            )
        )
    )
    if not keys:
        return []
    resolver = InventoryResolver(session, org_id, provider)
    reader = PostureReader(session, org_id, resolver, keys)
    spend = key_spend(session, org_id, keys, today)
    snoozed = active_snoozes(session, org_id, provider, today)
    signals: list[Signal] = []
    for key in keys:
        facts = reader.of(key)
        for kind in posture_gaps(key, facts, today, thresholds):
            if (kind, key.provider, key.external_id) in snoozed:
                continue
            signals.append(
                Signal(
                    kind=kind,
                    provider=key.provider,
                    entity_kind="api_key",
                    entity_id=key.external_id,
                    dollars_at_risk=spend.get((key.provider, key.external_id), Decimal("0")),
                    detected_at=key.last_seen_at,
                    reference=key.external_id,
                    key=key,
                    posture=facts,
                )
            )
    return signals


def posture_gaps(
    key: ProviderApiKey, facts: KeyPosture, today: date, thresholds: PostureThresholds
) -> list[SignalKind]:
    gaps: list[SignalKind] = []
    if facts.owner is None:
        gaps.append("no_owner")
    if key.limit_reported and key.spend_limit is None:
        gaps.append("no_limit")
    personal = key.provider in PERSONAL_KEY_PROVIDERS and key.principal_type == "user"
    if facts.creator_left and not personal:
        gaps.append("owner_left")
    created = key.created_at.date() if key.created_at else None
    if created is not None and (today - created).days < thresholds.new_key_days:
        gaps.append("new_key")
    idle_since = facts.last_used_at.date() if facts.last_used_at else created
    if idle_since is not None and (today - idle_since).days >= thresholds.idle_days:
        gaps.append("idle_active")
    return gaps


def key_spend(
    session: Session, org_id: int, keys: list[ProviderApiKey], today: date
) -> dict[tuple[str, str], Decimal]:
    start = datetime.combine(today - timedelta(days=SPEND_DAYS), datetime.min.time(), tzinfo=UTC)
    rows = session.execute(
        select(
            SpendAllocatedLine.provider,
            SpendAllocatedLine.api_key_id,
            func.sum(SpendAllocatedLine.amount),
        )
        .where(
            SpendAllocatedLine.organization_id == org_id,
            SpendAllocatedLine.provider.in_({key.provider for key in keys}),
            SpendAllocatedLine.api_key_id.in_({key.external_id for key in keys}),
            SpendAllocatedLine.period_start >= start,
        )
        .group_by(SpendAllocatedLine.provider, SpendAllocatedLine.api_key_id)
    )
    return {
        (line_provider, api_key_id): Decimal(total)
        for line_provider, api_key_id, total in rows
        if api_key_id is not None and total is not None
    }
