"""The detection rules as pure arithmetic over daily series: baselines, the checks of each rule
family, episodes and severity. Nothing here reads or writes the database, so every
flag can be reproduced from the numbers stored next to it."""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from costura.models import SpendAnomaly
from costura.models.intelligence import (
    PRINCIPAL_KINDS,
)
from costura.spend.anomaly_baseline import (
    BASELINE_WEEKS,
    DEFAULT_CALIBRATION,
    DEFAULT_THRESHOLDS,
    FALLBACK_DAYS,
    NEW_SERIES_BASELINE,
    Adjustments,
    Baseline,
    Calibration,
    Thresholds,
    compute_baseline,
)
from costura.spend.daily import (
    Series,
    SeriesByKind,
    first_day,
    trailing_samples,
    value_on,
)
from costura.spend.money import STORAGE_EXPONENT, to_percent
from costura.spend.window import Window

# Noise filters.
AMOUNT_FLOOR = Decimal("5")

ORG_SHARE_FLOOR = Decimal("0.005")

RECENT_DAYS = 7

SUPPRESSION_DAYS = 7

MIN_HISTORY_DAYS = 12

# Drops: a series worth watching for absence, a day the provider has
# finished reporting, and a fall the trailing week agrees with.
DROP_EXPECTED_FLOOR = Decimal("20")

# Days that must have passed since the day itself: the provider reports with up to a day of
# lag, so only the day before yesterday is complete enough to call an absence.
DROP_SETTLE_DAYS = 2

# New principals: a key or login with no history that already carries this
# share of the organization's day, and at least this much money.
NEW_PRINCIPAL_SHARE = Decimal("0.05")

NEW_PRINCIPAL_FLOOR = Decimal("25")

# Episodes: after this many days the new level is the level.
EPISODE_MAX_DAYS = 28

# Severity: total money, or a deviation in units of the series' own spread,
# which is what ranks a small spike on a flat series above a big spike on a noisy one.
SEVERITY_HIGH_IMPACT = Decimal("500")

SEVERITY_MEDIUM_IMPACT = Decimal("50")

SEVERITY_HIGH_DEVIATION = Decimal("10")

SEVERITY_MEDIUM_DEVIATION = Decimal("5")

# Scope: the top principals by trailing spend, keys and
# OAuth accounts ranked together.
TOP_KEYS = 25

ROOT_CAUSE_LIMIT = 5
SHARE_EXPONENT = Decimal("0.0001")

HISTORY_DAYS = max(7 * BASELINE_WEEKS, 335)

# Below this expected amount a percentage says nothing; the API returns null.
PERCENT_FLOOR = Decimal("1")

# Largest impact of the episodes already found in a series, by day. A candidate within 7 days
# of one is kept only when it deviates more than that one did.
RecentAnomalies = dict[date, Decimal]

# The same, per rule kind: a spike does not silence a later drop.
PriorEpisodes = dict[str, RecentAnomalies]


SHARE = Decimal("0.000001")

DEVIATION = Decimal("0.01")


def anomaly_scope(row: SpendAnomaly) -> tuple[str, dict[str, str]]:
    """Return the canonical Explore grouping and filters that reproduce an anomaly scope."""
    filters = {
        "provider": row.provider,
        "provider_account": str(row.provider_account_id),
    }
    if row.series_kind in PRINCIPAL_KINDS:
        filters[row.series_kind] = row.series_id
    return ("workspace" if row.series_kind == "org" else row.series_kind), filters


@dataclass(frozen=True)
class Check:
    """One noise filter applied to a candidate: what was observed against which threshold."""

    name: str
    passed: bool
    observed: Decimal | None
    threshold: Decimal | None
    reason: str  # the sentence stored when the check fails


@dataclass
class Candidate:
    """One episode of one series: the day it started, the baseline held for its whole run,
    and the amount of each day it covers."""

    series_kind: str
    series_id: str
    day: date
    actual: Decimal
    baseline: Baseline
    kind: str = "spike"
    # Amounts of the days after the first, ascending; empty for a one-day episode.
    later_amounts: list[Decimal] = field(default_factory=list)
    # True when the episode's last day is the last day the pass evaluated.
    ongoing: bool = False
    root_causes: list[dict[str, object]] = field(default_factory=list)
    # Organization spend of the provider from the first of the month to `end_day`, inclusive.
    month_to_date: Decimal = Decimal("0")

    @property
    def amounts(self) -> list[Decimal]:
        return [self.actual, *self.later_amounts]

    @property
    def duration_days(self) -> int:
        return len(self.amounts)

    @property
    def end_day(self) -> date:
        return self.day + timedelta(days=self.duration_days - 1)

    @property
    def falling(self) -> bool:
        return self.kind == "drop"

    def day_impact(self, amount: Decimal) -> Decimal:
        """Distance from the expected amount, always a magnitude: money spent above the
        baseline for a spike, money missing from it for a drop."""
        expected = self.baseline.expected
        return expected - amount if self.falling else amount - expected

    @property
    def impact(self) -> Decimal:
        return self.day_impact(self.actual)

    @property
    def total_actual(self) -> Decimal:
        return sum(self.amounts, Decimal("0"))

    @property
    def total_expected(self) -> Decimal:
        return self.baseline.expected * self.duration_days

    @property
    def total_impact(self) -> Decimal:
        return sum((self.day_impact(amount) for amount in self.amounts), Decimal("0"))

    @property
    def max_impact(self) -> Decimal:
        return max(self.day_impact(amount) for amount in self.amounts)

    @property
    def impact_share(self) -> Decimal | None:
        """Total impact as a ratio of the organization's month-to-date spend; None when that
        total is zero."""
        if self.month_to_date <= 0:
            return None
        return (self.total_impact / self.month_to_date).quantize(SHARE, rounding=ROUND_HALF_UP)

    @property
    def impact_percent(self) -> Decimal | None:
        if self.baseline.expected < PERCENT_FLOOR:
            return None
        return to_percent(self.impact / self.baseline.expected * 100)

    @property
    def deviation(self) -> Decimal | None:
        """The worst day's impact in units of the series' spread; None for a `new_principal`,
        which has no history to spread."""
        spread = self.baseline.spread
        if self.kind == "new_principal" or spread <= 0:
            return None
        return (self.max_impact / spread).quantize(DEVIATION, rounding=ROUND_HALF_UP)

    @property
    def severity(self) -> str:
        deviation = self.deviation
        total = self.total_impact
        if total >= SEVERITY_HIGH_IMPACT or (
            deviation is not None
            and deviation >= SEVERITY_HIGH_DEVIATION
            and self.max_impact >= SEVERITY_MEDIUM_IMPACT
        ):
            return "high"
        if total >= SEVERITY_MEDIUM_IMPACT or (
            deviation is not None and deviation >= SEVERITY_MEDIUM_DEVIATION
        ):
            return "medium"
        return "low"


@dataclass
class DetectionResult:
    run_id: int
    window: Window
    evaluated_days: int = 0
    series_count: int = 0
    found: list[Candidate] = field(default_factory=list)
    inserted: int = 0
    updated: int = 0
    removed: int = 0


@dataclass(frozen=True)
class EvaluationContext:
    """Everything one rule evaluation reads besides the day and its amount: the series, the
    baseline, the organization's total that day, the recent episodes and the thresholds."""

    series: Series
    baseline: Baseline
    org_total: Decimal
    recent_anomalies: RecentAnomalies
    kind: str = "spike"
    thresholds: Thresholds = DEFAULT_THRESHOLDS
    today: date | None = None


def evaluate_checks(
    day: date,
    actual: Decimal,
    context: EvaluationContext,
) -> list[Check]:
    """Every filter the rule applies to a candidate, in the order the detector reads them.
    `recent_anomalies` holds the largest impact of the episodes already found in the series,
    by day; a candidate within 7 days of one is kept only when it deviates more."""
    series, baseline = context.series, context.baseline
    if context.kind == "drop":
        checks = _drop_checks(
            series, day, actual, baseline, context.org_total, context.thresholds, context.today
        )
    elif context.kind == "new_principal":
        checks = _new_principal_checks(series, day, actual, context.org_total)
    else:
        checks = _spike_checks(series, day, actual, baseline, context.org_total, context.thresholds)
    impact = baseline.expected - actual if context.kind == "drop" else actual - baseline.expected
    checks.append(_suppression(day, impact, context.recent_anomalies))
    return checks


def _spike_checks(
    series: Series,
    day: date,
    actual: Decimal,
    baseline: Baseline,
    org_total: Decimal,
    thresholds: Thresholds,
) -> list[Check]:
    floor = thresholds.impact_floor
    org_floor = org_total * ORG_SHARE_FLOOR
    recent = trailing_samples(series, day, RECENT_DAYS)
    recent_average = sum(recent, Decimal("0")) / RECENT_DAYS
    return [
        Check(
            "above_upper_bound",
            actual > baseline.upper,
            actual,
            baseline.upper,
            "within upper bound",
        ),
        Check(
            "amount_floor",
            actual >= AMOUNT_FLOOR,
            actual,
            AMOUNT_FLOOR,
            f"below {AMOUNT_FLOOR} USD",
        ),
        Check(
            "impact_floor",
            actual - baseline.expected >= floor,
            actual - baseline.expected,
            floor,
            f"impact below {floor} USD",
        ),
        Check(
            "organization_share",
            not (org_total > 0 and actual < org_floor),
            actual,
            org_floor if org_total > 0 else None,
            "below 0.5% of the organization total",
        ),
        Check(
            "recent_average",
            actual > recent_average * thresholds.recent_ratio,
            actual,
            recent_average * thresholds.recent_ratio,
            f"not {thresholds.recent_percent}% above the trailing 7-day average",
        ),
        Check(
            "previous_day",
            actual > value_on(series, day - timedelta(days=1)),
            actual,
            value_on(series, day - timedelta(days=1)),
            "not above the previous day",
        ),
        _history(series, day),
    ]


def _drop_checks(
    series: Series,
    day: date,
    actual: Decimal,
    baseline: Baseline,
    org_total: Decimal,
    thresholds: Thresholds,
    today: date | None,
) -> list[Check]:
    floor = thresholds.impact_floor
    recent = trailing_samples(series, day, RECENT_DAYS)
    recent_average = sum(recent, Decimal("0")) / RECENT_DAYS
    settled = Decimal((today - day).days) if today is not None else None
    return [
        Check(
            "below_lower_bound",
            actual < baseline.lower,
            actual,
            baseline.lower,
            "within lower bound",
        ),
        Check(
            "expected_floor",
            baseline.expected >= DROP_EXPECTED_FLOOR,
            baseline.expected,
            DROP_EXPECTED_FLOOR,
            f"expected below {DROP_EXPECTED_FLOOR} USD",
        ),
        Check(
            "impact_floor",
            baseline.expected - actual >= floor,
            baseline.expected - actual,
            floor,
            f"impact below {floor} USD",
        ),
        Check(
            "complete_day",
            settled is not None and settled >= DROP_SETTLE_DAYS,
            settled,
            Decimal(DROP_SETTLE_DAYS),
            "the provider may still report this day",
        ),
        Check(
            "provider_reported",
            org_total > 0,
            org_total,
            Decimal("0"),
            "the provider reported nothing for the organization that day",
        ),
        Check(
            "recent_average",
            actual < recent_average * thresholds.drop_ratio,
            actual,
            recent_average * thresholds.drop_ratio,
            f"not {thresholds.drop_percent}% below the trailing 7-day average",
        ),
        _history(series, day),
    ]


def _new_principal_checks(
    series: Series, day: date, actual: Decimal, org_total: Decimal
) -> list[Check]:
    start = first_day(series)
    history = Decimal((day - start).days) if start is not None else None
    share_floor = org_total * NEW_PRINCIPAL_SHARE
    return [
        Check(
            "new_series",
            history is not None and history < MIN_HISTORY_DAYS,
            history,
            Decimal(MIN_HISTORY_DAYS),
            f"more than {MIN_HISTORY_DAYS} days of history",
        ),
        Check(
            "new_principal_floor",
            actual >= NEW_PRINCIPAL_FLOOR,
            actual,
            NEW_PRINCIPAL_FLOOR,
            f"below {NEW_PRINCIPAL_FLOOR} USD",
        ),
        Check(
            "new_principal_share",
            org_total > 0 and actual >= share_floor,
            actual,
            share_floor if org_total > 0 else None,
            "below 5% of the organization total",
        ),
    ]


def _history(series: Series, day: date) -> Check:
    start = first_day(series)
    return Check(
        "history",
        start is not None and (day - start).days >= MIN_HISTORY_DAYS,
        Decimal((day - start).days) if start is not None else None,
        Decimal(MIN_HISTORY_DAYS),
        f"fewer than {MIN_HISTORY_DAYS} days of history",
    )


def _suppression(day: date, impact: Decimal, recent_anomalies: RecentAnomalies) -> Check:
    peaks = [
        recent_anomalies[day - timedelta(days=k)]
        for k in range(1, SUPPRESSION_DAYS + 1)
        if day - timedelta(days=k) in recent_anomalies
    ]
    return Check(
        "suppression",
        not peaks or impact > max(peaks),
        impact,
        max(peaks) if peaks else None,
        "not above another anomaly in the same series within 7 days",
    )


def rejection_reason(
    series: Series,
    day: date,
    actual: Decimal,
    baseline: Baseline,
    *,
    org_total: Decimal,
    recent_anomalies: RecentAnomalies,
    kind: str = "spike",
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
    today: date | None = None,
) -> str | None:
    """The first filter that rejects a candidate, or None when it is an anomaly."""
    for check in evaluate_checks(
        day,
        actual,
        EvaluationContext(
            series,
            baseline,
            org_total,
            recent_anomalies,
            kind=kind,
            thresholds=thresholds,
            today=today,
        ),
    ):
        if not check.passed:
            return check.reason
    return None


def evaluate_series(
    kind: str,
    series_id: str,
    series: Series,
    days: list[date],
    org_series: Series,
    prior_anomalies: PriorEpisodes,
    *,
    calibration: Calibration = DEFAULT_CALIBRATION,
    adjustments: Adjustments | None = None,
    today: date | None = None,
) -> list[Candidate]:
    """Episodes of one series over `days` (ascending).

    A day that continues the open episode extends it against the baseline of its first day; a
    day that does not closes the episode and may open another, which then has to deviate more
    than any episode of the same rule in the previous 7 days.
    """
    found: list[Candidate] = []
    impacts = {rule: dict(by_day) for rule, by_day in prior_anomalies.items()}
    open_episode: Candidate | None = None
    rules = [rule for rule in ("spike", "drop", "new_principal") if calibration.runs(rule)]
    for day in days:
        actual = value_on(series, day)
        if open_episode is not None:
            if _continues(open_episode, series, day, actual, org_series, today):
                open_episode.later_amounts.append(actual)
                continue
            _record(open_episode, impacts)
            open_episode = None
        for rule in rules:
            if kind not in PRINCIPAL_KINDS and rule == "new_principal":
                continue
            baseline = _rule_baseline(
                rule,
                series,
                day,
                calibration,
                adjustments,
            )
            if baseline is None:
                continue
            reason = rejection_reason(
                series,
                day,
                actual,
                baseline,
                org_total=value_on(org_series, day),
                recent_anomalies=impacts.get(rule, {}),
                kind=rule,
                thresholds=calibration.thresholds,
                today=today,
            )
            if reason is None:
                open_episode = Candidate(kind, series_id, day, actual, baseline, kind=rule)
                found.append(open_episode)
                break
    if open_episode is not None:
        _record(open_episode, impacts)
        open_episode.ongoing = bool(days) and open_episode.end_day == days[-1]
    return found


def _rule_baseline(
    rule: str,
    series: Series,
    day: date,
    calibration: Calibration,
    adjustments: Adjustments | None,
) -> Baseline | None:
    """A `new_principal` has no history to describe, so its expected amount is zero and both
    bounds sit there; the other rules read the series' baseline."""
    if rule == "new_principal":
        return NEW_SERIES_BASELINE
    return compute_baseline(
        series,
        day,
        thresholds=calibration.thresholds,
        adjustments=adjustments,
    )


def _continues(
    episode: Candidate,
    series: Series,
    day: date,
    actual: Decimal,
    org_series: Series,
    today: date | None,
) -> bool:
    """Whether `day` is still the same episode, against the baseline frozen on its first day.
    Only the bound is re-read: the filters that ask what is new (the previous day, the
    trailing average, the suppression window) belong to the day an episode opens."""
    if episode.duration_days >= EPISODE_MAX_DAYS:
        return False
    if episode.kind == "spike":
        return actual > episode.baseline.upper
    if episode.kind == "drop":
        settled = today is None or (today - day).days >= DROP_SETTLE_DAYS
        return settled and actual < episode.baseline.lower
    start = first_day(series)
    org_total = value_on(org_series, day)
    return (
        start is not None
        and (day - start).days < MIN_HISTORY_DAYS
        and actual >= NEW_PRINCIPAL_FLOOR
        and org_total > 0
        and actual >= org_total * NEW_PRINCIPAL_SHARE
    )


def _record(episode: Candidate, impacts: dict[str, RecentAnomalies]) -> None:
    """Register every day of a closed episode with its largest impact, so the suppression
    filter of the next candidate of the same rule compares against the whole run."""
    peak = episode.max_impact
    by_day = impacts.setdefault(episode.kind, {})
    for offset in range(episode.duration_days):
        by_day[episode.day + timedelta(days=offset)] = peak


def root_causes(
    children: dict[str, SeriesByKind],
    day: date,
    *,
    falling: bool = False,
    sample_days: Sequence[date] = (),
) -> list[dict[str, object]]:
    """Top contributors on `day` by delta versus their average on the anomaly's own baseline
    days (their trailing 7-day average when the anomaly has none, a new series); the ones that
    fell furthest when `falling` (a drop of the parent series). Each carries `share`: its delta
    over the summed delta of every child of its kind, since averages add up where medians do
    not, so the shares of one kind cover the whole change."""
    ranked: list[dict[str, object]] = []
    for child_kind, by_id in children.items():
        deltas: dict[str, tuple[Decimal, Decimal, Decimal]] = {}
        for child_id, series in by_id.items():
            actual = value_on(series, day)
            if sample_days:
                baseline = sum((value_on(series, d) for d in sample_days), Decimal("0")) / len(
                    sample_days
                )
            else:
                recent = trailing_samples(series, day, RECENT_DAYS)
                baseline = sum(recent, Decimal("0")) / RECENT_DAYS
            deltas[child_id] = (actual, baseline, actual - baseline)
        change = sum((delta for _, _, delta in deltas.values()), Decimal("0"))
        for child_id, (actual, baseline, delta) in deltas.items():
            if (delta >= 0) if falling else (delta <= 0):
                continue
            share = delta / change if change != 0 and (change < 0) == falling else None
            ranked.append(
                {
                    "kind": child_kind,
                    "id": child_id,
                    "actual": str(actual.quantize(STORAGE_EXPONENT)),
                    "baseline": str(baseline.quantize(STORAGE_EXPONENT)),
                    "delta": str(delta.quantize(STORAGE_EXPONENT)),
                    "share": None if share is None else str(share.quantize(SHARE_EXPONENT)),
                }
            )
    sign = 1 if falling else -1
    ranked.sort(
        key=lambda row: (sign * Decimal(str(row["delta"])), str(row["kind"]), str(row["id"]))
    )
    return ranked[:ROOT_CAUSE_LIMIT]


def principal_days(
    days: list[date],
    series: Series,
    eligibility: Mapping[date, Collection[tuple[str, str]]],
    key: tuple[str, str],
) -> list[date]:
    """Days this principal is evaluated on: the ones where it ranks in the top 25 by trailing
    spend, plus the ones where it is too young to have any trailing spend at all, which is
    where the `new_principal` rule lives."""
    start = first_day(series)
    return [
        day
        for day in days
        if key in eligibility[day]
        or (start is not None and start <= day and (day - start).days < MIN_HISTORY_DAYS)
    ]


def month_to_date(org_series: Series, month_start: date, day: date) -> Decimal:
    """Organization spend from `month_start` to `day`, both inclusive."""
    return sum(
        (amount for d, amount in org_series.items() if month_start <= d <= day), Decimal("0")
    )


def top_keys(by_key: SeriesByKind) -> SeriesByKind:
    ranked = sorted(by_key.items(), key=lambda kv: (-sum(kv[1].values(), Decimal("0")), kv[0]))
    return dict(ranked[:TOP_KEYS])


def eligible_keys_by_day[K](
    by_key: dict[K, Series], days: list[date], *, limit: int = TOP_KEYS
) -> dict[date, set[K]]:
    """Top series for each day using only spend in `[day - 28 days, day)`; the detector
    passes every principal (keys and OAuth accounts) under one ranking.

    The current day and later data never affect eligibility. Equal trailing totals are ordered
    by series id so repeated runs choose the same set.
    """
    result: dict[date, set[K]] = {}
    for day in days:
        start = day - timedelta(days=FALLBACK_DAYS)
        ranked = sorted(
            (
                (
                    sum(
                        (
                            amount
                            for sample_day, amount in series.items()
                            if start <= sample_day < day
                        ),
                        Decimal("0"),
                    ),
                    series_id,
                )
                for series_id, series in by_key.items()
            ),
            key=lambda item: (-item[0], item[1]),
        )
        result[day] = {series_id for amount, series_id in ranked[:limit] if amount > 0}
    return result
