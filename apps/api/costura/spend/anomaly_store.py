"""What detection reads from and writes to `spend_anomalies`: the organization calibration, the
episodes already stored around the window, acknowledged days, the upsert of a run and the
retention purge."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from costura.models import SpendAnomaly
from costura.models.intelligence import (
    ANOMALY_SENSITIVITIES,
    AnomalySettings,
)
from costura.spend.anomaly_baseline import DEFAULT_CALIBRATION, Adjustments, Calibration
from costura.spend.anomaly_rules import Candidate, DetectionResult, PriorEpisodes
from costura.spend.daily import (
    CHILD_KINDS,
    SeriesByKind,
    daily_amounts,
)
from costura.spend.money import STORAGE_EXPONENT
from costura.spend.window import Window

DEFAULT_RETENTION_DAYS = 90


def purge_expired(
    session: Session,
    org_id: int,
    *,
    today: date | None = None,
) -> int:
    """Delete anomaly episodes outside the organization's documented retention window."""
    settings = session.get(AnomalySettings, org_id)
    retention_days = DEFAULT_RETENTION_DAYS if settings is None else settings.retention_days
    cutoff = (today or datetime.now(UTC).date()) - timedelta(days=retention_days)
    result = session.execute(
        delete(SpendAnomaly).where(
            SpendAnomaly.organization_id == org_id,
            SpendAnomaly.end_day < cutoff,
        )
    )
    session.commit()
    return result.rowcount or 0  # ty: ignore[unresolved-attribute]


def load_calibration(session: Session, org_id: int) -> Calibration:
    """The organization's settings, or the defaults when it never changed them."""
    row = session.get(AnomalySettings, org_id)
    if row is None:
        return DEFAULT_CALIBRATION
    return Calibration(
        sensitivity=row.sensitivity if row.sensitivity in ANOMALY_SENSITIVITIES else "normal",
        detect_spikes=True,
        detect_drops=row.detect_drops,
        detect_new_principals=row.detect_new_principals,
    )


def child_candidates(
    session: Session,
    org_id: int,
    provider: str,
    account_id: int,
    candidate: Candidate,
    start: date,
    end: date,
) -> dict[str, SeriesByKind]:
    parent = (
        None if candidate.series_kind == "org" else (candidate.series_kind, candidate.series_id)
    )
    return {
        child_kind: daily_amounts(
            session,
            org_id,
            provider,
            child_kind,
            start,
            end,
            parent=parent,
            account_id=account_id,
        )
        for child_kind in CHILD_KINDS[candidate.series_kind]
    }


def prior_anomalies(
    session: Session, org_id: int, provider: str, account_id: int, since: date, until: date
) -> dict[tuple[str, str], PriorEpisodes]:
    """Episodes stored for the days before the window (any status), so the suppression filter
    sees the previous month's tail. Rows inside the window are not read: the pass recomputes
    them from the data, so a re-run is a function of the data alone."""
    prior: dict[tuple[str, str], PriorEpisodes] = {}
    for series_kind, series_id, rule, day, end_day, peak in session.execute(
        select(
            SpendAnomaly.series_kind,
            SpendAnomaly.series_id,
            SpendAnomaly.kind,
            SpendAnomaly.day,
            SpendAnomaly.end_day,
            SpendAnomaly.max_impact,
        ).where(
            SpendAnomaly.organization_id == org_id,
            SpendAnomaly.provider == provider,
            SpendAnomaly.provider_account_id == account_id,
            SpendAnomaly.day >= since,
            SpendAnomaly.day < until,
        )
    ):
        by_day = prior.setdefault((series_kind, series_id), {}).setdefault(rule, {})
        for offset in range((end_day - day).days + 1):
            by_day[day + timedelta(days=offset)] = Decimal(peak)
    return prior


def acknowledged_adjustments(
    session: Session, org_id: int, provider: str, account_id: int, since: date, until: date
) -> dict[tuple[str, str], Adjustments]:
    """Every day of every acknowledged episode in the history window, mapped to the expected
    amount of that episode. A user who confirmed an anomaly said the day was not normal, so
    the baseline of the days that sample it reads the expectation instead of the outlier."""
    adjustments: dict[tuple[str, str], Adjustments] = {}
    for kind, series_id, day, end_day, expected in session.execute(
        select(
            SpendAnomaly.series_kind,
            SpendAnomaly.series_id,
            SpendAnomaly.day,
            SpendAnomaly.end_day,
            SpendAnomaly.expected,
        ).where(
            SpendAnomaly.organization_id == org_id,
            SpendAnomaly.provider == provider,
            SpendAnomaly.provider_account_id == account_id,
            SpendAnomaly.status == "acknowledged",
            SpendAnomaly.day >= since,
            SpendAnomaly.day < until,
        )
    ):
        series = adjustments.setdefault((kind, series_id), {})
        for offset in range((end_day - day).days + 1):
            series[day + timedelta(days=offset)] = Decimal(expected)
    return adjustments


def store_detection(
    session: Session,
    org_id: int,
    provider: str,
    window: Window,
    result: DetectionResult,
    currency: str,
    account_id: int,
) -> None:
    existing = {
        (row.series_kind, row.series_id, row.day): row
        for row in session.scalars(
            select(SpendAnomaly).where(
                SpendAnomaly.organization_id == org_id,
                SpendAnomaly.provider == provider,
                SpendAnomaly.provider_account_id == account_id,
                SpendAnomaly.day >= window.start.date(),
                SpendAnomaly.day < window.end.date(),
            )
        )
    }
    seen: set[tuple[str, str, date]] = set()
    for candidate in result.found:
        key = (candidate.series_kind, candidate.series_id, candidate.day)
        seen.add(key)
        values = {
            "kind": candidate.kind,
            "end_day": candidate.end_day,
            "ongoing": candidate.ongoing,
            "duration_days": candidate.duration_days,
            "actual": candidate.actual.quantize(STORAGE_EXPONENT),
            "expected": candidate.baseline.expected.quantize(STORAGE_EXPONENT),
            "upper_bound": candidate.baseline.upper.quantize(STORAGE_EXPONENT),
            # A new principal has no history, so it has no level to fall below either.
            "lower_bound": None
            if candidate.kind == "new_principal"
            else candidate.baseline.lower.quantize(STORAGE_EXPONENT),
            "baseline_method": candidate.baseline.method,
            "baseline_samples": candidate.baseline.samples,
            "impact": candidate.impact.quantize(STORAGE_EXPONENT),
            "impact_percent": candidate.impact_percent,
            "impact_share": candidate.impact_share,
            "total_actual": candidate.total_actual.quantize(STORAGE_EXPONENT),
            "total_expected": candidate.total_expected.quantize(STORAGE_EXPONENT),
            "total_impact": candidate.total_impact.quantize(STORAGE_EXPONENT),
            "max_impact": candidate.max_impact.quantize(STORAGE_EXPONENT),
            "deviation": candidate.deviation,
            "severity": candidate.severity,
            "currency": currency,
            "unit": currency,
            "root_causes": candidate.root_causes,
        }
        row = existing.get(key)
        if row is None:
            session.add(
                SpendAnomaly(
                    organization_id=org_id,
                    provider=provider,
                    provider_account_id=account_id,
                    series_kind=candidate.series_kind,
                    series_id=candidate.series_id,
                    day=candidate.day,
                    status="open",
                    **values,
                )
            )
            result.inserted += 1
        else:
            for name, value in values.items():
                setattr(row, name, value)
            result.updated += 1
    stale = [row.id for key, row in existing.items() if key not in seen and row.status == "open"]
    if stale:
        session.execute(delete(SpendAnomaly).where(SpendAnomaly.id.in_(stale)))
        result.removed = len(stale)
    session.flush()
