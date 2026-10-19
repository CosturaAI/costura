"""Bounded time-range queries over billed cost and provider usage counters.

The query engine keeps the source choice of the existing daily and usage reports: billed
money reads allocated lines when allocation covers the whole window and otherwise falls back
to cost lines; BYOK money, tokens and web-search requests read usage lines.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from costura.errors import InvalidInput
from costura.providers.registry import ALL
from costura.spend.dimensions import (
    group_label,
)
from costura.spend.inventory import InventoryResolver
from costura.spend.query_contract import (
    COMPARISONS,
    INTERVALS,
    Accumulation,
    Identity,
    LinearProjection,
    QueryComparison,
    QueryProjection,
    QueryResult,
    QuerySeries,
    QuerySpec,
    bucket_plan,
)
from costura.spend.query_readers import (
    FactRead,
    fact_source,
    read_facts,
)
from costura.spend.window import Window, comparison_window


def query_spend(
    session: Session, *, org_id: int, spec: QuerySpec, today: date | None = None
) -> QueryResult:
    """Run one validated query. Dates are inclusive; buckets are zero-filled."""
    buckets, current_index, first_offsets = bucket_plan(spec.start, spec.end, spec.interval)
    current_window = _window(spec.start, spec.end)
    source = fact_source(session, org_id, spec, current_window)
    resolver = InventoryResolver(session, org_id, ALL)
    current_read = read_facts(session, org_id, spec, current_window, source, resolver)
    current = _aggregate(current_read.values, current_index, len(buckets))

    comparison_read: FactRead | None = None
    comparison_values: dict[Identity, list[Decimal]] = {}
    comparison_start: date | None = None
    comparison_end: date | None = None
    comparison_buckets: list[date] = []
    if spec.compare != "none":
        comparison_start, comparison_end = _comparison_dates(
            spec, current_read, today or datetime.now(UTC).date()
        )
        comparison_window = _window(comparison_start, comparison_end)
        comparison_source = fact_source(session, org_id, spec, comparison_window)
        comparison_read = read_facts(
            session, org_id, spec, comparison_window, comparison_source, resolver
        )
        span = (spec.end - spec.start).days + 1
        comparison_index = {
            comparison_start + timedelta(days=offset): current_index[
                spec.start + timedelta(days=min(offset, span - 1))
            ]
            for offset in range((comparison_end - comparison_start).days + 1)
        }
        comparison_values = _aggregate(comparison_read.values, comparison_index, len(buckets))
        comparison_buckets = [comparison_start + timedelta(days=offset) for offset in first_offsets]

    ranked = sorted(current.items(), key=lambda item: (-sum(item[1]), item[0]))
    selected_ids = [identity for identity, _ in ranked[: spec.top]]
    series = [
        _series(identity, current[identity], current_read, comparison_read, spec, resolver)
        for identity in selected_ids
    ]
    other = _other(current, selected_ids, len(buckets))
    total = _total(current, len(buckets))

    comparison = None
    if comparison_start is not None and comparison_end is not None:
        comparison_series = [
            _series(
                identity,
                comparison_values.get(identity, [Decimal("0")] * len(buckets)),
                comparison_read or current_read,
                current_read,
                spec,
                resolver,
            )
            for identity in selected_ids
        ]
        comparison = QueryComparison(
            start=comparison_start,
            end=comparison_end,
            buckets=comparison_buckets,
            series=comparison_series,
            other=_other(comparison_values, selected_ids, len(buckets)),
            total=_total(comparison_values, len(buckets)),
        )

    projection = None
    if spec.projection == "linear":
        linear = linear_projection(total, lookback=spec.lookback, horizon=spec.horizon)
        projection = QueryProjection(
            mode="linear",
            lookback=spec.lookback,
            horizon=spec.horizon,
            buckets=projection_bucket_dates(spec.end, spec.interval, len(linear.values)),
            anchor=linear.anchor,
            values=linear.values,
        )

    return QueryResult(
        measure=spec.measure,
        dimensions=spec.dimensions,
        start=spec.start,
        end=spec.end,
        interval=spec.interval,
        source=source,
        buckets=buckets,
        series=series,
        other=other,
        total=total,
        comparison=comparison,
        projection=projection,
    )


def _series(
    identity: Identity,
    values: list[Decimal],
    primary: FactRead,
    secondary: FactRead | None,
    spec: QuerySpec,
    resolver: InventoryResolver,
) -> QuerySeries:
    providers = primary.providers.get(identity, set()) | (
        secondary.providers.get(identity, set()) if secondary else set()
    )
    keys: dict[str, str | None] = {}
    labels: dict[str, str] = {}
    for dimension, group in zip(spec.dimensions, identity, strict=True):
        key = group[1]
        keys[dimension] = None if key.startswith("__") else key
        labels[dimension] = (
            key if dimension == "cost_type" else group_label(resolver, dimension, group)
        )
    return QuerySeries(
        keys=keys,
        labels=labels,
        provider=next(iter(providers)) if len(providers) == 1 else None,
        values=values,
    )


def _aggregate(
    daily: dict[Identity, dict[date, Decimal]],
    index: dict[date, int],
    size: int,
) -> dict[Identity, list[Decimal]]:
    result: dict[Identity, list[Decimal]] = {}
    for identity, days in daily.items():
        values = [Decimal("0")] * size
        for day, value in days.items():
            bucket = index.get(day)
            if bucket is not None:
                values[bucket] += value
        result[identity] = values
    return result


def _other(
    grouped: dict[Identity, list[Decimal]], selected: list[Identity], size: int
) -> list[Decimal] | None:
    omitted = [values for identity, values in grouped.items() if identity not in selected]
    if not omitted:
        return None
    values = [Decimal("0")] * size
    for row in omitted:
        for index, value in enumerate(row):
            values[index] += value
    return values


def _total(grouped: dict[Identity, list[Decimal]], size: int) -> list[Decimal]:
    values = [Decimal("0")] * size
    for row in grouped.values():
        for index, value in enumerate(row):
            values[index] += value
    return values


def linear_projection(
    values: list[Decimal],
    *,
    lookback: int,
    horizon: int,
    accumulation: Accumulation = "incremental",
) -> LinearProjection:
    """Project non-negative values with ordinary least squares over recent buckets."""
    recent = [Decimal(value) for value in values[-lookback:]]
    if accumulation == "cumulative":
        running = Decimal("0")
        recent = [(running := running + value) for value in recent]
    if len(recent) < 2:
        return LinearProjection(accumulation=accumulation, anchor=None, values=[])
    count = Decimal(len(recent))
    xs = [Decimal(index) for index in range(len(recent))]
    x_mean = sum(xs) / count
    y_mean = sum(recent) / count
    denominator = sum((x - x_mean) ** 2 for x in xs)
    slope = (
        Decimal("0")
        if denominator == 0
        else sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, recent, strict=True)) / denominator
    )
    projected = [
        max(Decimal("0"), y_mean + slope * (Decimal(len(recent) + index) - x_mean))
        for index in range(horizon)
    ]
    return LinearProjection(
        accumulation=accumulation,
        anchor=recent[-1],
        values=projected,
    )


def projection_bucket_dates(end: date, interval: str, count: int) -> list[date]:
    """Return future bucket starts after an inclusive query end date."""
    if interval == "day":
        first = end + timedelta(days=1)
        return [first + timedelta(days=index) for index in range(count)]
    if interval == "week":
        first = end + timedelta(days=7 - end.weekday())
        return [first + timedelta(days=7 * index) for index in range(count)]
    if interval == "month":
        first = date(end.year + (end.month == 12), end.month % 12 + 1, 1)
        return [
            date(
                first.year + (first.month - 1 + index) // 12,
                (first.month - 1 + index) % 12 + 1,
                1,
            )
            for index in range(count)
        ]
    raise InvalidInput(f"interval must be one of {INTERVALS}")


def _comparison_dates(spec: QuerySpec, current: FactRead, today: date) -> tuple[date, date]:
    days = (spec.end - spec.start).days + 1
    if spec.compare == "previous_period":
        window = _window(spec.start, spec.end)
        month = f"{spec.start.year}-{spec.start.month:02d}"
        through = None
        if window == Window.for_month(month) and spec.start <= today <= spec.end:
            through = max(
                (day for daily in current.values.values() for day, value in daily.items() if value),
                default=spec.start,
            )
        before = comparison_window(window, month, through=through)
        return before.start.date(), before.last_day
    if spec.compare == "previous_year":
        try:
            start = spec.start.replace(year=spec.start.year - 1)
        except ValueError:
            start = spec.start.replace(year=spec.start.year - 1, day=28)
        return start, start + timedelta(days=days - 1)
    raise InvalidInput(f"compare must be one of {COMPARISONS}")


def _window(start: date, end: date) -> Window:
    return Window(
        start=datetime.combine(start, datetime.min.time(), tzinfo=UTC),
        end=datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=UTC),
    )


__all__ = [
    "QueryResult",
    "QuerySpec",
    "linear_projection",
    "projection_bucket_dates",
    "query_spend",
]
