"""Response shaping for the anomaly routes."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from costura.api import schemas
from costura.api.presenters.common import series_label
from costura.models import SpendAnomaly
from costura.spend.anomaly_baseline import BASELINE_WEEKS
from costura.spend.anomaly_queries import ALERT_ITEMS, Inbox
from costura.spend.anomaly_rules import anomaly_scope
from costura.spend.anomaly_store import AnomalySettings
from costura.spend.decomposition import Decomposition
from costura.spend.evidence import Evidence, UsageTotals
from costura.spend.explanation import Driver, explain
from costura.spend.inventory import InventoryResolver
from costura.spend.owners import (
    Assignments,
    Owner,
    anomaly_owners,
    load_assignments,
    organization_owners,
    owners_gap,
)


@dataclass
class AnomalyView:
    """What every anomaly of one response shares: the inventory names and the organization
    owners, loaded once."""

    session: Session
    resolver: InventoryResolver
    org_owners: list[Owner]
    assignments: Assignments


def _money_or_zero(value: Decimal | None) -> str:
    return schemas.money(value) or "0.00"


def _usage_totals_out(totals: UsageTotals) -> schemas.UsageTotalsOut:
    return schemas.UsageTotalsOut(
        amount=_money_or_zero(totals.amount),
        tokens=totals.tokens,
        total_tokens=totals.total_tokens,
        request_count=totals.request_count,
        cost_per_million=None
        if totals.cost_per_million is None
        else f"{totals.cost_per_million:.4f}",
    )


def _evidence_out(evidence: Evidence, row: SpendAnomaly) -> schemas.EvidenceOut:
    detail = evidence.baseline
    baseline = None
    if detail is not None:
        baseline = schemas.BaselineEvidenceOut(
            method=detail.method,
            samples=[
                schemas.BaselineSampleOut(
                    day=d.isoformat(),
                    amount=_money_or_zero(amount),
                    value=_money_or_zero(value),
                    adjusted=amount != value,
                )
                for d, amount, value in zip(
                    detail.sample_days,
                    detail.sample_amounts,
                    detail.sample_values,
                    strict=True,
                )
            ],
            trend_per_week=_money_or_zero(detail.trend_per_week),
            sensitivity=detail.thresholds.sensitivity,
            lower_bound=_money_or_zero(detail.lower),
            median=_money_or_zero(detail.median),
            mad=_money_or_zero(detail.mad),
            margin_mad=_money_or_zero(detail.margin_mad),
            margin_relative=_money_or_zero(detail.margin_relative),
            margin_absolute=_money_or_zero(detail.margin_absolute),
            margin_rule=detail.margin_rule,
            margin=_money_or_zero(detail.margin),
            upper_bound=_money_or_zero(detail.upper),
            stored_actual=_money_or_zero(row.actual),
            stored_expected=_money_or_zero(row.expected),
            stored_upper_bound=_money_or_zero(row.upper_bound),
            actual_now=_money_or_zero(evidence.actual_now),
            matches_stored=evidence.matches_stored(row),
        )
    quality = evidence.data_quality
    assert quality is not None
    return schemas.EvidenceOut(
        baseline=baseline,
        checks=[
            schemas.CheckOut(
                name=check.name,
                passed=check.passed,
                observed=schemas.money(check.observed),
                threshold=schemas.money(check.threshold),
                reason=check.reason,
            )
            for check in evidence.checks
        ],
        breakdowns=[
            schemas.DayBreakdownOut(
                dimension=breakdown.dimension,
                rows=[
                    schemas.DayRowOut(
                        key=day_row.key,
                        label=day_row.label,
                        amount=schemas.money(day_row.amount),
                        tokens=day_row.tokens,
                        request_count=day_row.request_count,
                        cost_per_million=None
                        if day_row.cost_per_million is None
                        else f"{day_row.cost_per_million:.4f}",
                        trailing_average=schemas.money(day_row.trailing_average),
                        delta=schemas.money(day_row.delta),
                        new=day_row.new,
                    )
                    for day_row in breakdown.rows
                ],
            )
            for breakdown in evidence.breakdowns
        ],
        unit_economics=None
        if evidence.unit_economics is None
        else schemas.UnitEconomicsOut(
            day=_usage_totals_out(evidence.unit_economics.day),
            baseline=_usage_totals_out(evidence.unit_economics.baseline),
            sample_days=evidence.unit_economics.sample_days,
        ),
        decomposition=_decomposition_out(evidence.decomposition),
        data_quality=schemas.DataQualityOut(
            runs=[
                schemas.RunSummaryOut(
                    id=run.id,
                    endpoint=run.endpoint,
                    status=run.status,
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                    rows_upserted=run.rows_upserted,
                )
                for run in quality.runs
            ],
            cost_lines=quality.cost_lines,
            usage_lines=quality.usage_lines,
            allocated_lines=quality.allocated_lines,
            unallocated_amount=_money_or_zero(quality.unallocated_amount),
            changed_since_detection=quality.changed_since_detection,
        ),
        history=[
            schemas.HistoryItemOut(
                id=item.id,
                kind=item.kind,
                day=item.day.isoformat(),
                actual=_money_or_zero(item.actual),
                impact=_money_or_zero(item.impact),
                status=item.status,
            )
            for item in evidence.history
        ],
    )


def explanation_of(view: AnomalyView, row: SpendAnomaly, split: Decomposition | None = None) -> str:
    resolver = view.resolver
    drivers = [
        Driver(
            kind=str(c["kind"]),
            label=series_label(resolver, row.provider, str(c["kind"]), str(c["id"])),
            share=None if c.get("share") is None else Decimal(str(c["share"])),
        )
        for c in row.root_causes
    ]
    return explain(
        kind=row.kind,
        label=series_label(resolver, row.provider, row.series_kind, row.series_id),
        impact=Decimal(row.impact),
        impact_percent=None if row.impact_percent is None else Decimal(row.impact_percent),
        actual=Decimal(row.actual),
        impact_share=None if row.impact_share is None else Decimal(row.impact_share),
        drivers=drivers,
        split=split,
    )


def _anomaly(view: AnomalyView, row: SpendAnomaly) -> schemas.AnomalyOut:
    resolver = view.resolver
    investigate_by, investigate_filters = anomaly_scope(row)
    return schemas.AnomalyOut(
        explanation=explanation_of(view, row),
        id=row.id,
        provider=row.provider,
        provider_account_id=row.provider_account_id,
        provider_account_label=view.resolver.provider_account_label(row.provider_account_id),
        series_kind=row.series_kind,
        series_id=row.series_id,
        label=series_label(resolver, row.provider, row.series_kind, row.series_id),
        kind=row.kind,
        day=row.day.isoformat(),
        end_day=row.end_day.isoformat(),
        ongoing=row.ongoing,
        duration_days=row.duration_days,
        actual=schemas.money(row.actual) or "0.00",
        expected=schemas.money(row.expected) or "0.00",
        upper_bound=schemas.money(row.upper_bound) or "0.00",
        lower_bound=schemas.money(row.lower_bound),
        baseline_method=row.baseline_method,
        baseline_samples=row.baseline_samples,
        impact=schemas.money(row.impact) or "0.00",
        impact_percent=None if row.impact_percent is None else f"{row.impact_percent:.2f}",
        impact_share=None if row.impact_share is None else f"{row.impact_share * 100:.2f}",
        total_actual=schemas.money(row.total_actual) or "0.00",
        total_expected=schemas.money(row.total_expected) or "0.00",
        total_impact=schemas.money(row.total_impact) or "0.00",
        max_impact=schemas.money(row.max_impact) or "0.00",
        deviation=None if row.deviation is None else f"{row.deviation:.2f}",
        severity=row.severity,
        currency=row.currency,
        unit=row.unit,
        status=row.status,
        status_reason=row.status_reason,
        status_changed_by=row.status_changed_by,
        status_changed_at=row.status_changed_at,
        root_causes=[
            schemas.RootCauseOut(
                kind=str(c["kind"]),
                id=str(c["id"]),
                label=series_label(resolver, row.provider, str(c["kind"]), str(c["id"])),
                actual=schemas.money(Decimal(str(c["actual"]))) or "0.00",
                baseline=schemas.money(Decimal(str(c["baseline"]))) or "0.00",
                delta=schemas.money(Decimal(str(c["delta"]))) or "0.00",
                share=percent_of(c.get("share")),
            )
            for c in row.root_causes
        ],
        owners=[
            schemas.OwnerOut(email=o.email, role=o.role, source=o.source, note=o.note)
            for o in anomaly_owners(resolver, row, view.org_owners, view.assignments)
        ],
        owners_gap=owners_gap(resolver, row, view.assignments),
        investigate=schemas.AnomalyInvestigateOut(
            by=investigate_by,
            filters=investigate_filters,
            measure="billed_usd",
        ),
        detected_at=row.detected_at,
        updated_at=row.updated_at,
    )


def _anomaly_settings_out(row: AnomalySettings | None) -> schemas.AnomalySettingsOut:
    if row is None:
        return schemas.AnomalySettingsOut(
            sensitivity="normal",
            detect_drops=True,
            detect_new_principals=True,
            retention_days=90,
            idle_days=30,
            new_key_days=7,
        )
    sensitivity = row.sensitivity if row.sensitivity in ("low", "normal", "high") else "normal"
    return schemas.AnomalySettingsOut(
        sensitivity=sensitivity,  # type: ignore[arg-type]
        detect_drops=row.detect_drops,
        detect_new_principals=row.detect_new_principals,
        retention_days=row.retention_days,
        idle_days=row.idle_days,
        new_key_days=row.new_key_days,
    )


def _cents(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.01"))
    return f"{rounded if rounded != 0 else Decimal('0.00'):.2f}"


def _decomposition_out(split: Decomposition | None) -> schemas.DecompositionOut | None:
    if split is None:
        return None
    return schemas.DecompositionOut(
        change=_cents(split.change),
        volume=_cents(split.volume),
        mix=_cents(split.mix),
        price=_cents(split.price),
        top_model=split.top_model,
        top_share_baseline=f"{split.top_share_baseline * 100:.2f}",
        top_share_day=f"{split.top_share_day * 100:.2f}",
        switch_day=None if split.switch_day is None else split.switch_day.isoformat(),
    )


def percent_of(share: object) -> str | None:
    if share is None:
        return None
    return f"{Decimal(str(share)) * 100:.2f}"


def anomaly_view(session: Session, org_id: int, provider: str) -> AnomalyView:
    return AnomalyView(
        session=session,
        resolver=InventoryResolver(session, org_id, provider),
        org_owners=organization_owners(session, org_id),
        assignments=load_assignments(session, org_id, provider),
    )


def inbox_out(
    view: AnomalyView,
    box: Inbox,
    signals: Sequence[schemas.InboxSignalOut] = (),
    signals_shown: int = ALERT_ITEMS,
) -> schemas.AlertsOut:
    """The anomaly inbox plus the budget and gap signals: every unread one counts, the newest
    `signals_shown` most-money-first are listed."""
    unread: dict[str, int] = {"anomaly": box.unread_count} if box.unread_count else {}
    for signal in signals:
        if signal.read_at is None:
            unread[signal.kind] = unread.get(signal.kind, 0) + 1
    return schemas.AlertsOut(
        opted_in=box.opted_in,
        unread_count=sum(unread.values()),
        items=[
            schemas.AlertItemOut(**_anomaly(view, row).model_dump(), read_at=seen)
            for row, seen in box.items
        ],
        signals=list(signals[:signals_shown]),
        unread_by_kind=unread,
    )


def same_day_out(
    resolver: InventoryResolver, rows: list[SpendAnomaly]
) -> list[schemas.SameDayAnomalyOut]:
    return [
        schemas.SameDayAnomalyOut(
            id=other.id,
            kind=other.kind,
            series_kind=other.series_kind,
            series_id=other.series_id,
            label=series_label(resolver, other.provider, other.series_kind, other.series_id),
            impact=schemas.money(other.impact) or "0.00",
            status=other.status,
        )
        for other in rows
    ]


def series_points_out(evidence: Evidence, row: SpendAnomaly) -> list[schemas.SeriesPointOut]:
    """Eight weeks ending on the anomaly day through the episode's last day, baseline
    samples marked: the days the evidence card lists."""
    start = row.day - timedelta(days=7 * BASELINE_WEEKS)
    sample_days = set(evidence.baseline.sample_days) if evidence.baseline else set()
    return [
        schemas.SeriesPointOut(
            day=d.isoformat(),
            amount=schemas.money(evidence.series.get(d, Decimal("0"))) or "0.00",
            baseline_sample=d in sample_days,
        )
        for d in (start + timedelta(days=k) for k in range((row.end_day - start).days + 1))
    ]
