"""CSV rendering of a spend query result."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from fastapi import Response

from costura.api.presenters.spend import csv_response, csv_text, query_value_out
from costura.spend.query import QueryResult
from costura.spend.query_contract import QuerySeries


def query_csv(result: QueryResult, measure: str, start: str, end: str, interval: str) -> Response:
    """The query result in long form: one row per bucket and series."""
    header = ["bucket", "series_type"]
    for dimension in result.dimensions:
        header.extend([f"{dimension}_key", f"{dimension}_label"])
    header.extend(["provider", "value"])
    rows = _period_rows(result, "", result.buckets, result.series, result.other, result.total)
    if result.comparison is not None:
        comparison = result.comparison
        rows += _period_rows(
            result,
            "comparison_",
            comparison.buckets,
            comparison.series,
            comparison.other,
            comparison.total,
        )
    if result.projection is not None:
        for bucket, value in zip(result.projection.buckets, result.projection.values, strict=True):
            rows.append(_aggregate_row(result, bucket, "projection", value))
    return csv_response(f"costura-{measure}-{start}-{end}-{interval}.csv", header, rows)


def _period_rows(
    result: QueryResult,
    prefix: str,
    buckets: Sequence[date],
    series: Sequence[QuerySeries],
    other: Sequence[Decimal] | None,
    total: Sequence[Decimal],
) -> list[list[object]]:
    rows: list[list[object]] = []
    for index, bucket in enumerate(buckets):
        for line in series:
            row: list[object] = [bucket.isoformat(), f"{prefix}series"]
            for dimension in result.dimensions:
                row.extend(
                    [
                        csv_text(line.keys.get(dimension) or ""),
                        csv_text(line.labels.get(dimension) or ""),
                    ]
                )
            row.extend([line.provider or "", query_value_out(result.measure, line.values[index])])
            rows.append(row)
        if other is not None:
            rows.append(_aggregate_row(result, bucket, f"{prefix}other", other[index]))
        rows.append(_aggregate_row(result, bucket, f"{prefix}total", total[index]))
    return rows


def _aggregate_row(result: QueryResult, bucket: date, kind: str, value: Decimal) -> list[object]:
    return [
        bucket.isoformat(),
        kind,
        *[""] * (len(result.dimensions) * 2 + 1),
        query_value_out(result.measure, value),
    ]
