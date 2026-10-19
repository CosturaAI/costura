"""The query interface: what a caller may ask (`QuerySpec`, validated on construction against
the bounds below) and what it gets back (`QueryResult`)."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from costura.errors import InvalidInput
from costura.spend import FILTER_KEYS, SERIES_DIMENSIONS
from costura.spend.dimensions import (
    GroupKey,
)
from costura.spend.filters import (
    Filters,
    normalize_filters,
)
from costura.spend.taxonomy import TOKEN_TYPE

Accumulation = Literal["incremental", "cumulative"]

MEASURES: tuple[str, ...] = (
    "billed_usd",
    "byok_usd",
    "tokens_total",
    "tokens_input",
    "tokens_output",
    "tokens_cache_read",
    "tokens_cache_write",
    "requests_web_search",
    "requests",
)


INTERVALS = ("day", "week", "month")

COMPARISONS = ("none", "previous_period", "previous_year")

PROJECTIONS = ("none", "linear")

QUERY_DIMENSIONS = tuple(d for d in SERIES_DIMENSIONS if d != "none")

MAX_DIMENSIONS = 3

MAX_TOP = 200

MAX_RANGE_DAYS = 3660

MAX_BUCKETS = 366

Identity = tuple[GroupKey, ...]


@dataclass(frozen=True)
class QuerySpec:
    measure: str
    dimensions: tuple[str, ...]
    filters: Filters
    start: date
    end: date
    interval: str
    top: int
    compare: str = "none"
    projection: str = "none"
    lookback: int = 8
    horizon: int = 4

    def __post_init__(self) -> None:
        object.__setattr__(self, "filters", normalize_filters(self.filters))
        self._check_shape()
        self._check_measure_fit()
        self._check_range()
        self._check_options()

    def _check_shape(self) -> None:
        if self.measure not in MEASURES:
            raise InvalidInput(f"measure must be one of {MEASURES}")
        if len(self.dimensions) > MAX_DIMENSIONS:
            raise InvalidInput(f"dimensions accepts at most {MAX_DIMENSIONS} values")
        if len(set(self.dimensions)) != len(self.dimensions):
            raise InvalidInput("dimensions must not repeat")
        unknown_dimensions = {value for value in self.dimensions if value not in QUERY_DIMENSIONS}
        if unknown_dimensions:
            raise InvalidInput(f"unknown dimensions {sorted(unknown_dimensions)}")
        unknown_filters = {value for value in self.filters if value not in FILTER_KEYS}
        if unknown_filters:
            raise InvalidInput(f"unknown filters {sorted(unknown_filters)}")

    def _check_measure_fit(self) -> None:
        used = (*self.dimensions, *self.filters)
        if self.measure != "billed_usd" and "cost_type" in used:
            raise InvalidInput("cost_type is available only for billed_usd")
        if TOKEN_TYPE in used and not (
            self.measure == "billed_usd" or self.measure.startswith("tokens_")
        ):
            raise InvalidInput("token_type is available only for billed_usd and tokens")

    def _check_range(self) -> None:
        if self.start > self.end:
            raise InvalidInput("start must be on or before end")
        if (self.end - self.start).days + 1 > MAX_RANGE_DAYS:
            raise InvalidInput(f"date range must not exceed {MAX_RANGE_DAYS} days")
        if self.interval not in INTERVALS:
            raise InvalidInput(f"interval must be one of {INTERVALS}")
        if len(bucket_plan(self.start, self.end, self.interval)[0]) > MAX_BUCKETS:
            raise InvalidInput(f"query must not produce more than {MAX_BUCKETS} buckets")

    def _check_options(self) -> None:
        if not 1 <= self.top <= MAX_TOP:
            raise InvalidInput(f"top must be between 1 and {MAX_TOP}")
        if self.compare not in COMPARISONS:
            raise InvalidInput(f"compare must be one of {COMPARISONS}")
        if self.projection not in PROJECTIONS:
            raise InvalidInput(f"projection must be one of {PROJECTIONS}")
        if not 2 <= self.lookback <= 90:
            raise InvalidInput("lookback must be between 2 and 90")
        if not 1 <= self.horizon <= 31:
            raise InvalidInput("horizon must be between 1 and 31")


@dataclass
class QuerySeries:
    keys: dict[str, str | None]
    labels: dict[str, str]
    provider: str | None
    values: list[Decimal]

    @property
    def total(self) -> Decimal:
        return sum(self.values, Decimal("0"))


@dataclass
class QueryComparison:
    start: date
    end: date
    buckets: list[date]
    series: list[QuerySeries]
    other: list[Decimal] | None
    total: list[Decimal]


@dataclass
class LinearProjection:
    accumulation: Accumulation
    anchor: Decimal | None
    values: list[Decimal]


@dataclass
class QueryProjection:
    mode: Literal["linear"]
    lookback: int
    horizon: int
    buckets: list[date]
    anchor: Decimal | None
    values: list[Decimal]


@dataclass
class QueryResult:
    measure: str
    dimensions: tuple[str, ...]
    start: date
    end: date
    interval: str
    source: str
    buckets: list[date]
    series: list[QuerySeries]
    other: list[Decimal] | None
    total: list[Decimal]
    comparison: QueryComparison | None
    projection: QueryProjection | None = None


def bucket_plan(
    start: date, end: date, interval: str
) -> tuple[list[date], dict[date, int], list[int]]:
    if interval not in INTERVALS:
        raise InvalidInput(f"interval must be one of {INTERVALS}")
    buckets: list[date] = []
    first_offsets: list[int] = []
    indexes: dict[date, int] = {}
    previous: tuple[int, ...] | None = None
    cursor = start
    while cursor <= end:
        current = _bucket_key(cursor, interval)
        if current != previous:
            buckets.append(cursor)
            first_offsets.append((cursor - start).days)
            previous = current
        indexes[cursor] = len(buckets) - 1
        cursor += timedelta(days=1)
    return buckets, indexes, first_offsets


def _bucket_key(day: date, interval: str) -> tuple[int, ...]:
    if interval == "day":
        return (day.toordinal(),)
    if interval == "week":
        iso = (day - timedelta(days=day.weekday())).isocalendar()
        return (iso.year, iso.week)
    return (day.year, day.month)
