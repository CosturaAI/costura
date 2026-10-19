"""Month-end projection per series: month-to-date plus the weekday median of each remaining
day, with a band from the same samples.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from costura import accounts
from costura.models import ProviderSyncRun, SpendProjection
from costura.models.intelligence import ORG_SERIES_ID, PROJECTION_SERIES_KINDS
from costura.providers.http import stored_exception_text
from costura.spend.anomaly_rules import top_keys
from costura.spend.daily import Series, daily_amounts, first_day, median, value_on
from costura.spend.money import STORAGE_EXPONENT
from costura.spend.scope import provider_clause
from costura.spend.window import Window

PROJECTION_ENDPOINT = "projection"
# The expected amount is the median of the same weekday over these weeks.
PROJECTION_WEEKS = 4
# The band looks further back: p10 and p90 need enough samples not to collapse to one day.
BAND_WEEKS = 8
BAND_MIN_SAMPLES = 6
P_LOW = Decimal("0.1")
P_HIGH = Decimal("0.9")
HISTORY_DAYS = 7 * BAND_WEEKS


@dataclass(frozen=True)
class ProjectedDay:
    day: date
    expected: Decimal
    low: Decimal
    high: Decimal
    samples: int


@dataclass
class Projection:
    series_kind: str
    series_id: str
    month: str
    as_of_day: date
    mtd: Decimal
    days: list[ProjectedDay]

    @property
    def projected_total(self) -> Decimal:
        return self.mtd + sum((d.expected for d in self.days), Decimal("0"))

    @property
    def low(self) -> Decimal:
        return self.mtd + sum((d.low for d in self.days), Decimal("0"))

    @property
    def high(self) -> Decimal:
        return self.mtd + sum((d.high for d in self.days), Decimal("0"))


@dataclass
class ProjectionResult:
    run_id: int
    window: Window
    as_of_day: date | None = None
    projections: list[Projection] = field(default_factory=list)


def project(series: Series, window: Window, as_of: date) -> Projection | None:
    """Projection of one series for the month of `window`, given data through `as_of`.

    None when the series has no amount in the month so far. Each remaining day takes the
    median of the same weekday over the previous 4 weeks (zero-filled; a day before the
    series' first day is not a sample). The band is the p10 and p90 of the same weekday over
    the previous 8 weeks when at least 6 such samples exist, otherwise the min and max of the
    4-week samples: with 4 values p90 is the largest one, and a single outlier week would set
    the upper band for every future day of that weekday.
    """
    month_start = window.start.date()
    month_end = window.end.date()
    mtd = sum((amount for d, amount in series.items() if month_start <= d <= as_of), Decimal("0"))
    if mtd == 0:
        return None
    start = first_day(series) or as_of
    days: list[ProjectedDay] = []
    day = as_of + timedelta(days=1)
    while day < month_end:
        # Only days known through as_of are samples; for a day more than a week out the
        # nearest same weekday is itself in the future.
        def weekday_samples(weeks: int, day: date = day) -> list[Decimal]:
            return [
                value_on(series, day - timedelta(days=7 * k))
                for k in range(1, weeks + 1)
                if start <= day - timedelta(days=7 * k) <= as_of
            ]

        samples = weekday_samples(PROJECTION_WEEKS)
        band_samples = weekday_samples(BAND_WEEKS)
        if samples:
            expected = median(samples)
            if len(band_samples) >= BAND_MIN_SAMPLES:
                low, high = percentile(band_samples, P_LOW), percentile(band_samples, P_HIGH)
            else:
                band_samples = samples
                low, high = min(samples), max(samples)
        else:
            expected = low = high = Decimal("0")
            band_samples = []
        days.append(
            ProjectedDay(
                day=day,
                expected=expected.quantize(STORAGE_EXPONENT),
                low=low.quantize(STORAGE_EXPONENT),
                high=high.quantize(STORAGE_EXPONENT),
                samples=len(band_samples),
            )
        )
        day += timedelta(days=1)
    return Projection(
        series_kind="",
        series_id="",
        month=month_start.strftime("%Y-%m"),
        as_of_day=as_of,
        mtd=mtd.quantize(STORAGE_EXPONENT),
        days=days,
    )


def percentile(values: list[Decimal], p: Decimal) -> Decimal:
    """Linear interpolation between the two nearest ranks (numpy's default): with 6 samples
    p10 sits between the first and second smallest, p90 between the two largest."""
    ordered = sorted(values)
    if not ordered:
        return Decimal("0")
    position = p * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def run_projection(
    session: Session,
    org_id: int,
    provider: str,
    window: Window,
    *,
    today: date | None = None,
    currency: str = "USD",
    account_id: int | None = None,
) -> ProjectionResult:
    """Store the projection of every series of one account for the month of `window`.

    A closed month (today outside the window) or a month without data removes the stored
    rows and projects nothing. Records a `provider_sync_runs` row with endpoint `projection`.
    Without `account_id`, every account of the provider is projected in turn and the result
    lists all their series.
    """
    today = today or datetime.now(UTC).date()
    if account_id is None:
        ids = [a.id for a in accounts.list_accounts(session, org_id, provider)]
        if not ids:
            ids = [accounts.ensure_default_account(session, org_id, provider).id]
            session.commit()
        results = [
            run_projection(
                session, org_id, provider, window, today=today, currency=currency, account_id=i
            )
            for i in ids
        ]
        if len(results) == 1:
            return results[0]
        merged = ProjectionResult(run_id=results[-1].run_id, window=window)
        for r in results:
            merged.projections.extend(r.projections)
            if r.as_of_day is not None and (
                merged.as_of_day is None or r.as_of_day > merged.as_of_day
            ):
                merged.as_of_day = r.as_of_day
        return merged
    run = ProviderSyncRun(
        organization_id=org_id,
        provider=provider,
        provider_account_id=account_id,
        endpoint=PROJECTION_ENDPOINT,
        window_start=window.start,
        window_end=window.end,
    )
    session.add(run)
    session.commit()
    result = ProjectionResult(run_id=run.id, window=window)
    try:
        month = window.start.strftime("%Y-%m")
        session.execute(
            delete(SpendProjection).where(
                SpendProjection.organization_id == org_id,
                SpendProjection.provider == provider,
                SpendProjection.provider_account_id == account_id,
                SpendProjection.month == month,
            )
        )
        if window.start.date() <= today < window.end.date():
            result.projections = _project_all(
                session, org_id, provider, window, result, account_id, today
            )
            for projection in result.projections:
                session.add(
                    SpendProjection(
                        organization_id=org_id,
                        provider=provider,
                        provider_account_id=account_id,
                        series_kind=projection.series_kind,
                        series_id=projection.series_id,
                        month=projection.month,
                        as_of_day=projection.as_of_day,
                        mtd=projection.mtd,
                        projected_total=projection.projected_total,
                        low=projection.low,
                        high=projection.high,
                        currency=currency,
                        days=[
                            {
                                "day": d.day.isoformat(),
                                "expected": str(d.expected),
                                "low": str(d.low),
                                "high": str(d.high),
                                "samples": d.samples,
                            }
                            for d in projection.days
                        ],
                    )
                )
        run.status = "succeeded"
        run.finished_at = datetime.now(UTC)
        run.rows_upserted = len(result.projections)
        session.commit()
    except Exception as exc:
        session.rollback()
        run.status = "failed"
        run.finished_at = datetime.now(UTC)
        run.error = stored_exception_text(exc)
        session.commit()
        raise
    return result


def _project_all(
    session: Session,
    org_id: int,
    provider: str,
    window: Window,
    result: ProjectionResult,
    account_id: int,
    today: date,
) -> list[Projection]:
    """Every series of one account projected from the last complete day: today's report is
    still filling, so a day on or after `today` is neither month-to-date nor a sample."""
    month_start = window.start.date()
    month_end = window.end.date()
    history_start = month_start - timedelta(days=HISTORY_DAYS)
    loaded = {
        kind: daily_amounts(
            session, org_id, provider, kind, history_start, month_end, account_id=account_id
        )
        for kind in PROJECTION_SERIES_KINDS
    }
    org_series = loaded["org"].get(ORG_SERIES_ID, {})
    in_month = [
        d
        for d, amount in org_series.items()
        if month_start <= d < min(month_end, today) and amount > 0
    ]
    if not in_month:
        return []
    as_of = max(in_month)
    result.as_of_day = as_of
    loaded["api_key"] = top_keys(loaded["api_key"])
    projections: list[Projection] = []
    for kind in PROJECTION_SERIES_KINDS:
        for series_id, series in sorted(loaded[kind].items()):
            projection = project(series, window, as_of)
            if projection is None:
                continue
            projection.series_kind = kind
            projection.series_id = series_id
            projections.append(projection)
    return projections


def stored_projected_total(
    session: Session, org_id: int, provider: str, month: str, kind: str, series_id: str
) -> Decimal | None:
    """The projected month total of one series summed over every account of the provider;
    None when no account stored a projection for it."""
    total = session.scalar(
        select(func.sum(SpendProjection.projected_total)).where(
            SpendProjection.organization_id == org_id,
            SpendProjection.provider == provider,
            SpendProjection.month == month,
            SpendProjection.series_kind == kind,
            SpendProjection.series_id == series_id,
        )
    )
    return None if total is None else Decimal(total)


def stored_projections(
    session: Session, org_id: int, provider: str, month: str, series_kind: str
) -> list[SpendProjection]:
    """The projections the `project` step stored for `month`, largest first."""
    return list(
        session.scalars(
            select(SpendProjection)
            .where(
                SpendProjection.organization_id == org_id,
                provider_clause(SpendProjection.provider, provider),
                SpendProjection.month == month,
                SpendProjection.series_kind == series_kind,
            )
            .order_by(SpendProjection.projected_total.desc(), SpendProjection.series_id)
        )
    )
