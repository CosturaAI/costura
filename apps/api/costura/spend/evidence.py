"""Everything behind one stored anomaly, recomputed from the data at read time.

The detector's arithmetic (`spend.anomalies`) is deterministic over the daily series, so the
evidence page can show the exact samples, the median and MAD, the margin rule that fixed the
upper bound and the verdict of every noise filter. Recomputing also reveals when the day's
data changed after detection (a re-sync): the recomputed baseline then differs from the
stored one and the page says so instead of hiding it.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from costura.models import (
    ProviderSyncRun,
    SpendAllocatedLine,
    SpendAnomaly,
    SpendCostLine,
    SpendUsageLine,
)
from costura.models.allocation import ALLOCATION_ENDPOINT
from costura.models.intelligence import ORG_SERIES_ID, AnomalyKind, AnomalyStatus
from costura.models.sync import SyncRunStatus
from costura.providers.registry import specs
from costura.spend.allocation_check import allocation_covers
from costura.spend.anomaly_baseline import NEW_SERIES_BASELINE, BaselineDetail, baseline_detail
from costura.spend.anomaly_rules import (
    HISTORY_DAYS,
    RECENT_DAYS,
    SUPPRESSION_DAYS,
    Check,
    EvaluationContext,
    evaluate_checks,
)
from costura.spend.anomaly_store import load_calibration
from costura.spend.daily import Series, SeriesByKind, daily_amounts, trailing_samples, value_on
from costura.spend.decomposition import SWITCH_LOOKBACK_DAYS, Decomposition, decompose
from costura.spend.dimensions import KEY_DEFAULT_WORKSPACE, KEY_NO_MODEL
from costura.spend.filters import Filters, line_where
from costura.spend.inventory import InventoryResolver
from costura.spend.sql import utc_day
from costura.spend.usage import TOKEN_COLUMNS, UsageRow, usage_report
from costura.spend.window import Window

# Runs that rewrite the day's amounts; a succeeded one after `detected_at` means the stored
# figures may no longer match the data. Control-total runs store the provider's figure for
# reconcile and touch no line, so they are not listed.
DATA_ENDPOINTS = frozenset(
    {endpoint for spec in specs() for endpoint in spec.data_endpoints} | {ALLOCATION_ENDPOINT}
)

# Dimensions worth a full table for an anomaly of each kind: the principals and the model are
# the detector's root causes; the workspace is context the page adds for the organization.
DAY_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "org": ("api_key", "account", "model", "workspace"),
    "api_key": ("model",),
    "account": ("model",),
}

HISTORY_LIMIT = 20
RUNS_LIMIT = 20
MILLION = Decimal("1000000")
PRICE = Decimal("0.0001")


@dataclass(frozen=True)
class DayRow:
    dimension: str
    # The usage row's key (external id or None for a sentinel row such as unallocated cost).
    key: str | None
    label: str
    amount: Decimal | None
    tokens: dict[str, int]
    request_count: int
    cost_per_million: Decimal | None
    # Mean amount over the 7 days before the anomaly day, None when the row has no series.
    trailing_average: Decimal | None
    delta: Decimal | None
    # True when the row had no spend in the eight weeks before the day.
    new: bool


@dataclass(frozen=True)
class DayBreakdown:
    dimension: str
    rows: list[DayRow]


@dataclass(frozen=True)
class UsageTotals:
    amount: Decimal
    tokens: dict[str, int]
    request_count: int

    @property
    def total_tokens(self) -> int:
        return sum(self.tokens.values())

    @property
    def cost_per_million(self) -> Decimal | None:
        return cost_per_million(self.amount, self.total_tokens)


@dataclass(frozen=True)
class UnitEconomics:
    """The series on the day against the mean of its baseline sample days."""

    day: UsageTotals
    baseline: UsageTotals
    sample_days: int


@dataclass(frozen=True)
class RunSummary:
    id: int
    endpoint: str
    status: SyncRunStatus
    started_at: datetime
    finished_at: datetime | None
    rows_upserted: int


@dataclass(frozen=True)
class DataQuality:
    runs: list[RunSummary]
    cost_lines: int
    usage_lines: int
    allocated_lines: int
    unallocated_amount: Decimal
    changed_since_detection: bool


@dataclass(frozen=True)
class HistoryItem:
    id: int
    kind: AnomalyKind
    day: date
    actual: Decimal
    impact: Decimal
    status: AnomalyStatus


@dataclass
class Evidence:
    baseline: BaselineDetail | None
    actual_now: Decimal
    checks: list[Check]
    # The anomaly's own daily series over the eight weeks ending on the day.
    series: Series = field(default_factory=dict)
    breakdowns: list[DayBreakdown] = field(default_factory=list)
    unit_economics: UnitEconomics | None = None
    data_quality: DataQuality | None = None
    history: list[HistoryItem] = field(default_factory=list)
    decomposition: Decomposition | None = None

    def matches_stored(self, row: SpendAnomaly) -> bool:
        """True when the recomputed actual, expected and upper bound equal the stored ones
        to the cent."""
        if self.baseline is None:
            return False
        cent = Decimal("0.01")
        return (
            self.actual_now.quantize(cent) == Decimal(row.actual).quantize(cent)
            and self.baseline.median.quantize(cent) == Decimal(row.expected).quantize(cent)
            and self.baseline.upper.quantize(cent) == Decimal(row.upper_bound).quantize(cent)
        )


def cost_per_million(amount: Decimal | None, tokens: int) -> Decimal | None:
    if amount is None or tokens <= 0:
        return None
    return (amount / Decimal(tokens) * MILLION).quantize(PRICE)


def series_filters(row: SpendAnomaly) -> Filters:
    """The Explore filter that isolates the anomaly's series; empty for the org total."""
    if row.series_kind == "org":
        return {}
    return {row.series_kind: row.series_id}


def anomaly_evidence(
    session: Session, row: SpendAnomaly, resolver: InventoryResolver | None = None
) -> Evidence:
    org_id, provider, day = row.organization_id, row.provider, row.day
    # One inventory load and one allocation decision serve every breakdown of the day.
    resolver = resolver or InventoryResolver(session, org_id, provider)
    allocated = allocation_covers(session, org_id, provider, _day_window(day))
    history_start = day - timedelta(days=HISTORY_DAYS)
    # Through the episode's last day: the chart draws the whole run, the checks read `day`.
    end = row.end_day + timedelta(days=1)
    own = daily_amounts(session, org_id, provider, row.series_kind, history_start, end).get(
        ORG_SERIES_ID if row.series_kind == "org" else row.series_id, {}
    )
    org_series = (
        own
        if row.series_kind == "org"
        else daily_amounts(session, org_id, provider, "org", history_start, end).get(
            ORG_SERIES_ID, {}
        )
    )
    calibration = load_calibration(session, org_id)
    # A `new_principal` fired because the series has no history, so there is no baseline to
    # show; its checks read the organization's day instead.
    detail = (
        None
        if row.kind == "new_principal"
        else baseline_detail(own, day, thresholds=calibration.thresholds)
    )
    actual_now = value_on(own, day)
    checks: list[Check] = []
    if detail is not None or row.kind == "new_principal":
        checks = evaluate_checks(
            day,
            actual_now,
            EvaluationContext(
                own,
                detail.baseline if detail is not None else NEW_SERIES_BASELINE,
                value_on(org_series, day),
                _recent_anomalies(session, row),
                kind=row.kind,
                thresholds=calibration.thresholds,
                today=datetime.now(UTC).date(),
            ),
        )
    evidence = Evidence(baseline=detail, actual_now=actual_now, checks=checks, series=own)
    filters = series_filters(row)
    evidence.breakdowns = [
        _breakdown(session, row, dimension, filters, history_start, resolver, allocated)
        for dimension in DAY_DIMENSIONS.get(row.series_kind, ())
    ]
    evidence.unit_economics = _unit_economics(session, row, filters, own, detail)
    evidence.decomposition = _decomposition(session, row, filters, detail)
    evidence.data_quality = _data_quality(session, row, filters)
    evidence.history = _history(session, row)
    return evidence


def _recent_anomalies(session: Session, row: SpendAnomaly) -> dict[date, Decimal]:
    """Episodes of the same series and the same rule that cover a day in the suppression
    window before this one, mapped to their largest impact."""
    rows = session.execute(
        select(SpendAnomaly.day, SpendAnomaly.end_day, SpendAnomaly.max_impact).where(
            SpendAnomaly.organization_id == row.organization_id,
            SpendAnomaly.provider == row.provider,
            SpendAnomaly.series_kind == row.series_kind,
            SpendAnomaly.series_id == row.series_id,
            SpendAnomaly.kind == row.kind,
            SpendAnomaly.end_day >= row.day - timedelta(days=SUPPRESSION_DAYS),
            SpendAnomaly.day < row.day,
        )
    ).all()
    recent: dict[date, Decimal] = {}
    for day, end_day, peak in rows:
        for offset in range((end_day - day).days + 1):
            recent[day + timedelta(days=offset)] = Decimal(peak)
    return recent


def _day_window(day: date) -> Window:
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return Window(start=start, end=start + timedelta(days=1))


def _breakdown(
    session: Session,
    row: SpendAnomaly,
    dimension: str,
    filters: Filters,
    history_start: date,
    resolver: InventoryResolver,
    allocated: bool,
) -> DayBreakdown:
    report = usage_report(
        session,
        org_id=row.organization_id,
        provider=row.provider,
        window=_day_window(row.day),
        dimension=dimension,
        filters=filters,
        resolver=resolver,
        allocated=allocated,
    )
    parent = None if row.series_kind == "org" else (row.series_kind, row.series_id)
    series_by_id: SeriesByKind = daily_amounts(
        session,
        row.organization_id,
        row.provider,
        dimension,
        history_start,
        row.day,
        parent=parent,
    )
    rows = [_day_row(dimension, usage, series_by_id, row.day) for usage in report.rows]
    rows.sort(
        key=lambda r: (
            -(r.delta if r.delta is not None else Decimal("-1")),
            -(r.amount or Decimal("0")),
            r.label,
        )
    )
    return DayBreakdown(dimension=dimension, rows=rows)


def _series_key(dimension: str, key: str | None) -> str | None:
    """The `daily_amounts` id of a usage row: sentinels for the rows without a natural id."""
    if key is not None:
        return key
    if dimension == "workspace":
        return KEY_DEFAULT_WORKSPACE
    if dimension == "model":
        return KEY_NO_MODEL
    return None


def _day_row(dimension: str, usage: UsageRow, series_by_id: SeriesByKind, day: date) -> DayRow:
    series_key = _series_key(dimension, usage.key)
    series: Series | None = series_by_id.get(series_key) if series_key is not None else None
    trailing: Decimal | None = None
    delta: Decimal | None = None
    new = False
    if series_key is not None:
        history = series or {}
        recent = trailing_samples(history, day, RECENT_DAYS) if history else []
        trailing = sum(recent, Decimal("0")) / RECENT_DAYS
        new = not any(amount > 0 for d, amount in history.items() if d < day)
        if usage.amount is not None:
            delta = usage.amount - trailing
    return DayRow(
        dimension=dimension,
        key=usage.key,
        label=usage.label,
        amount=usage.amount,
        tokens=dict(usage.tokens),
        request_count=usage.request_count,
        cost_per_million=cost_per_million(usage.amount, usage.total_tokens),
        trailing_average=trailing,
        delta=delta,
        new=new,
    )


def _usage_by_day(
    session: Session, row: SpendAnomaly, filters: Filters, start: date, end: date
) -> dict[date, tuple[dict[str, int], int]]:
    """Token totals and request counts of the series per day in `[start, end)`."""
    window = Window(
        start=datetime(start.year, start.month, start.day, tzinfo=UTC),
        end=datetime(end.year, end.month, end.day, tzinfo=UTC),
    )
    day_col = utc_day(SpendUsageLine.period_start)
    sums = [func.coalesce(func.sum(getattr(SpendUsageLine, name)), 0) for name in TOKEN_COLUMNS]
    requests = func.coalesce(func.sum(SpendUsageLine.request_count), 0)
    result: dict[date, tuple[dict[str, int], int]] = {}
    for record in session.execute(
        select(day_col, *sums, requests)
        .where(*line_where(SpendUsageLine, row.organization_id, row.provider, window, filters))
        .group_by(day_col)
    ).all():
        tokens = {name: int(value) for name, value in zip(TOKEN_COLUMNS, record[1:-1], strict=True)}
        result[record[0]] = (tokens, int(record[-1]))
    return result


def _unit_economics(
    session: Session,
    row: SpendAnomaly,
    filters: Filters,
    own: Series,
    detail: BaselineDetail | None,
) -> UnitEconomics | None:
    if detail is None or not detail.sample_days:
        return None
    start = min(detail.sample_days)
    usage = _usage_by_day(session, row, filters, start, row.day + timedelta(days=1))
    empty = dict.fromkeys(TOKEN_COLUMNS, 0)
    day_tokens, day_requests = usage.get(row.day, (dict(empty), 0))
    day_totals = UsageTotals(
        amount=value_on(own, row.day), tokens=day_tokens, request_count=day_requests
    )
    count = len(detail.sample_days)
    summed = dict(empty)
    requests = 0
    amount = Decimal("0")
    for sample_day in detail.sample_days:
        tokens, day_requests = usage.get(sample_day, (empty, 0))
        for name in TOKEN_COLUMNS:
            summed[name] += tokens[name]
        requests += day_requests
        amount += value_on(own, sample_day)
    baseline = UsageTotals(
        amount=amount / count,
        tokens={name: value // count for name, value in summed.items()},
        request_count=requests // count,
    )
    return UnitEconomics(day=day_totals, baseline=baseline, sample_days=count)


def _decomposition(
    session: Session, row: SpendAnomaly, filters: Filters, detail: BaselineDetail | None
) -> Decomposition | None:
    if detail is None or not detail.sample_days:
        return None
    start = min(min(detail.sample_days), row.day - timedelta(days=SWITCH_LOOKBACK_DAYS))
    window = Window(
        start=datetime(start.year, start.month, start.day, tzinfo=UTC),
        end=datetime(row.day.year, row.day.month, row.day.day, tzinfo=UTC) + timedelta(days=1),
    )
    day_col = utc_day(SpendAllocatedLine.period_start)
    by_day: dict[date, dict[str, tuple[Decimal, int]]] = {}
    for line_day, model, amount, tokens in session.execute(
        select(
            day_col,
            SpendAllocatedLine.model,
            func.coalesce(func.sum(SpendAllocatedLine.amount), 0),
            func.coalesce(func.sum(SpendAllocatedLine.tokens), 0),
        )
        .where(*line_where(SpendAllocatedLine, row.organization_id, row.provider, window, filters))
        .group_by(day_col, SpendAllocatedLine.model)
    ):
        by_day.setdefault(line_day, {})[model or KEY_NO_MODEL] = (Decimal(amount), int(tokens))
    return decompose(by_day, row.day, detail.sample_days)


def _data_quality(session: Session, row: SpendAnomaly, filters: Filters) -> DataQuality:
    window = _day_window(row.day)
    runs = session.scalars(
        select(ProviderSyncRun)
        .where(
            ProviderSyncRun.organization_id == row.organization_id,
            ProviderSyncRun.provider == row.provider,
            ProviderSyncRun.window_start <= window.start,
            ProviderSyncRun.window_end > window.start,
        )
        .order_by(ProviderSyncRun.started_at.desc(), ProviderSyncRun.id.desc())
        .limit(RUNS_LIMIT)
    ).all()
    detected_at = row.detected_at
    changed = any(
        run.endpoint in DATA_ENDPOINTS
        and run.status == "succeeded"
        and run.finished_at is not None
        and run.finished_at > detected_at
        for run in runs
    )

    def count(table: type[SpendCostLine] | type[SpendUsageLine] | type[SpendAllocatedLine]) -> int:
        return int(
            session.scalar(
                select(func.count())
                .select_from(table)
                .where(*line_where(table, row.organization_id, row.provider, window, filters))
            )
            or 0
        )

    unallocated = session.scalar(
        select(func.coalesce(func.sum(SpendAllocatedLine.amount), 0)).where(
            *line_where(SpendAllocatedLine, row.organization_id, row.provider, window, filters),
            SpendAllocatedLine.unallocated_reason.is_not(None),
        )
    )
    return DataQuality(
        runs=[
            RunSummary(
                id=run.id,
                endpoint=run.endpoint,
                status=run.status,
                started_at=run.started_at,
                finished_at=run.finished_at,
                rows_upserted=run.rows_upserted,
            )
            for run in runs
        ],
        cost_lines=count(SpendCostLine),
        usage_lines=count(SpendUsageLine),
        allocated_lines=count(SpendAllocatedLine),
        unallocated_amount=Decimal(unallocated or 0),
        changed_since_detection=changed,
    )


def _history(session: Session, row: SpendAnomaly) -> list[HistoryItem]:
    rows = session.scalars(
        select(SpendAnomaly)
        .where(
            SpendAnomaly.organization_id == row.organization_id,
            SpendAnomaly.provider == row.provider,
            SpendAnomaly.series_kind == row.series_kind,
            SpendAnomaly.series_id == row.series_id,
            SpendAnomaly.id != row.id,
        )
        .order_by(SpendAnomaly.day.desc(), SpendAnomaly.id.desc())
        .limit(HISTORY_LIMIT)
    ).all()
    return [
        HistoryItem(
            id=other.id,
            kind=other.kind,
            day=other.day,
            actual=Decimal(other.actual),
            impact=Decimal(other.impact),
            status=other.status,
        )
        for other in rows
    ]
