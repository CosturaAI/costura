"""What normal looks like for one series: the median of the same weekday over the trailing weeks
(or of recent days when weekdays are too sparse), a MAD margin scaled by the sensitivity, and
a trend shift. Pure arithmetic; the sensitivity presets and calibration live here too."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from costura.spend.daily import (
    Series,
    first_day,
    median,
    value_on,
)

# Baseline.
BASELINE_WEEKS = 8

MIN_WEEKDAY_SAMPLES = 4

FALLBACK_DAYS = 28

# Non-zero days the trailing window needs before an intermittent series drops its zero days.
MIN_ACTIVE_SAMPLES = 4

MAD_SCALE = Decimal("1.4826")

MIN_ABSOLUTE_MARGIN = Decimal("5")

# Weekday samples needed for a slope, and the share of the median a slope may shift a sample.
MIN_TREND_SAMPLES = 6

TREND_SHIFT_CAP = Decimal("0.5")

# Expected amount to read instead of the observed one, for the days of an acknowledged
# episode: a confirmed anomaly is not evidence of a normal day.
Adjustments = dict[date, Decimal]


@dataclass(frozen=True)
class Thresholds:
    """Bound width, impact floor and trailing-week gates of one sensitivity level."""

    sensitivity: str
    mad_multiplier: Decimal
    relative_margin: Decimal
    impact_floor: Decimal
    # Multiples of the trailing 7-day average a day must clear to count as a rise or a fall.
    # They move with the bound: a gate tighter than the bound would make the bound moot.
    recent_ratio: Decimal
    drop_ratio: Decimal

    @property
    def recent_percent(self) -> Decimal:
        return ((self.recent_ratio - 1) * 100).quantize(Decimal("1"))

    @property
    def drop_percent(self) -> Decimal:
        return ((1 - self.drop_ratio) * 100).quantize(Decimal("1"))


# `normal` is the default calibration; `low` widens the bound and raises the floor,
# `high` narrows it.
THRESHOLDS: dict[str, Thresholds] = {
    "low": Thresholds(
        "low", Decimal("4"), Decimal("0.30"), Decimal("25"), Decimal("1.3"), Decimal("0.7")
    ),
    "normal": Thresholds(
        "normal", Decimal("3"), Decimal("0.20"), Decimal("10"), Decimal("1.2"), Decimal("0.8")
    ),
    "high": Thresholds(
        "high", Decimal("2.5"), Decimal("0.15"), Decimal("5"), Decimal("1.1"), Decimal("0.9")
    ),
}


DEFAULT_SENSITIVITY = "normal"

DEFAULT_THRESHOLDS = THRESHOLDS[DEFAULT_SENSITIVITY]


@dataclass(frozen=True)
class Calibration:
    """What one organization asked the detector to do; `anomaly_settings` without the row."""

    sensitivity: str = DEFAULT_SENSITIVITY
    detect_spikes: bool = True
    detect_drops: bool = True
    detect_new_principals: bool = True

    @property
    def thresholds(self) -> Thresholds:
        return THRESHOLDS.get(self.sensitivity, DEFAULT_THRESHOLDS)

    def runs(self, kind: str) -> bool:
        if kind == "spike":
            return self.detect_spikes
        if kind == "drop":
            return self.detect_drops
        if kind == "new_principal":
            return self.detect_new_principals
        return True


DEFAULT_CALIBRATION = Calibration()

# The stand-in baseline of a `new_principal`: a series younger than `MIN_HISTORY_DAYS` has no
# level to compare against, so every dollar it spends is its impact.
NEW_SERIES_BASELINE_METHOD = "new_series"


@dataclass(frozen=True)
class Baseline:
    expected: Decimal
    upper: Decimal
    method: str  # "weekday", "active_days" or "trailing"
    samples: int
    # Spread of the samples in money, the unit `Candidate.deviation` counts in.
    spread: Decimal = Decimal("0")
    sample_days: tuple[date, ...] = field(default=(), compare=False)

    @property
    def margin(self) -> Decimal:
        return self.upper - self.expected

    @property
    def lower(self) -> Decimal:
        """Mirror of the upper bound, never below zero."""
        return max(Decimal("0"), self.expected - self.margin)


NEW_SERIES_BASELINE = Baseline(
    expected=Decimal("0"),
    upper=Decimal("0"),
    method=NEW_SERIES_BASELINE_METHOD,
    samples=0,
)


@dataclass(frozen=True)
class BaselineDetail:
    """Every intermediate value behind a `Baseline`, for the evidence page."""

    method: str
    sample_days: list[date]
    # As observed in the series, and after the trend shift and the acknowledged-episode
    # replacement; the median and the MAD are computed from the second list.
    sample_amounts: list[Decimal]
    sample_values: list[Decimal]
    # Slope of the samples in USD per week, 0 when the series is too young for one.
    trend_per_week: Decimal
    thresholds: Thresholds
    median: Decimal
    mad: Decimal
    # The three candidate margins; `margin_rule` names the one `max` picked.
    margin_mad: Decimal
    margin_relative: Decimal
    margin_absolute: Decimal
    margin_rule: str  # "mad", "relative" or "absolute"

    @property
    def margin(self) -> Decimal:
        return max(self.margin_mad, self.margin_relative, self.margin_absolute)

    @property
    def upper(self) -> Decimal:
        return self.median + self.margin

    @property
    def lower(self) -> Decimal:
        return max(Decimal("0"), self.median - self.margin)

    @property
    def spread(self) -> Decimal:
        """The unit a deviation counts in: the scaled MAD, or the margin that fixed the bound
        when every sample is identical (a perfectly flat series has no MAD to divide by)."""
        scaled = MAD_SCALE * self.mad
        return scaled if scaled > 0 else self.margin

    @property
    def baseline(self) -> Baseline:
        return Baseline(
            expected=self.median,
            upper=self.upper,
            method=self.method,
            samples=len(self.sample_values),
            spread=self.spread,
            sample_days=tuple(self.sample_days),
        )


def trend_per_week(sample_days: list[date], values: list[Decimal], day: date) -> Decimal:
    """Theil-Sen slope in USD per week over weekly-spaced samples: the median of the slopes of
    every pair, which one outlying week cannot move. Zero when there are too few samples."""
    if len(values) < MIN_TREND_SAMPLES:
        return Decimal("0")
    weeks = [Decimal((day - sample_day).days) / 7 for sample_day in sample_days]
    slopes = [
        (values[i] - values[j]) / (weeks[j] - weeks[i])
        for i in range(len(values))
        for j in range(i + 1, len(values))
        if weeks[j] != weeks[i]
    ]
    return median(slopes) if slopes else Decimal("0")


def baseline_detail(
    series: Series,
    day: date,
    *,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
    adjustments: Adjustments | None = None,
) -> BaselineDetail | None:
    """Median and spread of the samples that describe `day` best, with every intermediate
    value. None for an empty series.

    Samples are the same weekday over the trailing weeks; the trailing 28 days when the series
    is too young for four of those; the non-zero days of the trailing 28 when the series runs
    only now and then, where a weekday median would sit at zero and call every active day an
    anomaly. Weekday samples are shifted along their own slope, so a series that grows every
    week is expected to keep growing. A day inside an acknowledged episode is read as that
    episode's expected amount, so a confirmed anomaly does not raise the bar for the next one.
    """
    start = first_day(series)
    if start is None:
        return None
    sample_days = [
        day - timedelta(days=7 * k)
        for k in range(1, BASELINE_WEEKS + 1)
        if day - timedelta(days=7 * k) >= start
    ]
    method = "weekday"
    if len(sample_days) < MIN_WEEKDAY_SAMPLES:
        sample_days = _trailing_days(day, start)
        method = "trailing"
    if not sample_days:
        return None
    amounts = [value_on(series, d) for d in sample_days]
    if _intermittent(amounts):
        active = [d for d in _trailing_days(day, start) if value_on(series, d) > 0]
        if len(active) >= MIN_ACTIVE_SAMPLES:
            sample_days, method = active, "active_days"
            amounts = [value_on(series, d) for d in sample_days]
    adjusted = [
        (adjustments or {}).get(sample_day, amount)
        for sample_day, amount in zip(sample_days, amounts, strict=True)
    ]
    slope = trend_per_week(sample_days, adjusted, day) if method == "weekday" else Decimal("0")
    values = _shifted(sample_days, adjusted, day, slope)
    expected = median(values)
    mad = median([abs(x - expected) for x in values])
    margins = {
        "mad": thresholds.mad_multiplier * MAD_SCALE * mad,
        "relative": thresholds.relative_margin * expected,
        "absolute": MIN_ABSOLUTE_MARGIN,
    }
    rule = max(margins, key=lambda name: (margins[name], name == "absolute", name == "relative"))
    return BaselineDetail(
        method=method,
        sample_days=sample_days,
        sample_amounts=amounts,
        sample_values=values,
        trend_per_week=slope,
        thresholds=thresholds,
        median=expected,
        mad=mad,
        margin_mad=margins["mad"],
        margin_relative=margins["relative"],
        margin_absolute=margins["absolute"],
        margin_rule=rule,
    )


def _trailing_days(day: date, start: date) -> list[date]:
    return [
        day - timedelta(days=k)
        for k in range(1, FALLBACK_DAYS + 1)
        if day - timedelta(days=k) >= start
    ]


def _intermittent(amounts: list[Decimal]) -> bool:
    """True when the samples say nothing about an active day: half of them or more are zero,
    so their median sits at or near zero while the series does spend when it runs."""
    zeros = sum(1 for amount in amounts if amount <= 0)
    return bool(amounts) and zeros * 2 >= len(amounts)


def _shifted(
    sample_days: list[date], values: list[Decimal], day: date, slope: Decimal
) -> list[Decimal]:
    """Each sample carried along `slope` to `day`, by at most half the raw median so a steep
    slope cannot invent a level the series never reached."""
    if slope == 0:
        return list(values)
    cap = TREND_SHIFT_CAP * median(values)
    moved = []
    for sample_day, value in zip(sample_days, values, strict=True):
        weeks = Decimal((day - sample_day).days) / 7
        shift = slope * weeks
        shift = max(-cap, min(cap, shift))
        moved.append(max(Decimal("0"), value + shift))
    return moved


def compute_baseline(
    series: Series,
    day: date,
    *,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
    adjustments: Adjustments | None = None,
) -> Baseline | None:
    """The `Baseline` the detector compares against; see `baseline_detail`."""
    detail = baseline_detail(
        series,
        day,
        thresholds=thresholds,
        adjustments=adjustments,
    )
    return None if detail is None else detail.baseline
