import type {
  ExploreDisplay,
  QueryInterval,
  QueryProjection,
  QueryValue,
  SpendQuery,
} from "@/lib/api";

const DAY_MS = 86_400_000;

export type DisplayProjection = Pick<
  QueryProjection,
  "mode" | "lookback" | "horizon" | "buckets"
> & {
  anchor: number | null;
  values: number[];
};

type DisplayQuery = Omit<SpendQuery, "projection"> & {
  projection: DisplayProjection | null;
};

/**
 * Apply an Explore display mode without mutating the API result. The first bucket has no
 * previous bucket in the range, so delta starts at the second bucket instead of showing the
 * first bucket's whole value as a change.
 */
export function applyExploreDisplay(query: SpendQuery, display: ExploreDisplay): DisplayQuery {
  const skip = display === "delta" ? 1 : 0;
  const coverage = bucketDayCoverage(query.buckets, query.start, query.end);
  const convert = (values: QueryValue[]) => transformValues(values, display, coverage).slice(skip);
  const total = convert(query.total);
  const comparisonCoverage =
    query.comparison === null
      ? []
      : bucketDayCoverage(query.comparison.buckets, query.comparison.start, query.comparison.end);
  const convertComparison = (values: QueryValue[]) =>
    transformValues(values, display, comparisonCoverage).slice(skip);

  return {
    ...query,
    start: skip > 0 ? (query.buckets[1] ?? query.start) : query.start,
    buckets: query.buckets.slice(skip),
    series: query.series.map((series) => {
      const values = convert(series.values);
      return { ...series, values, total: values.reduce((sum, value) => sum + value, 0) };
    }),
    other: query.other === null ? null : convert(query.other),
    total,
    comparison:
      query.comparison === null
        ? null
        : {
            ...query.comparison,
            buckets: query.comparison.buckets.slice(skip),
            series: query.comparison.series.map((series) => {
              const values = convertComparison(series.values);
              return { ...series, values, total: values.reduce((sum, value) => sum + value, 0) };
            }),
            other:
              query.comparison.other === null ? null : convertComparison(query.comparison.other),
            total: convertComparison(query.comparison.total),
          },
    projection: transformProjection(
      query.projection ?? null,
      display,
      query.interval,
      total.at(-1) ?? null,
    ),
  };
}

export function transformValues(
  values: QueryValue[],
  display: ExploreDisplay,
  coverage: number[],
): number[] {
  const numeric = values.map(Number);
  if (display === "total") return numeric;
  if (display === "delta") {
    return numeric.map((value, index) => (index === 0 ? value : value - numeric[index - 1]!));
  }
  const multiplier = display === "daily_average_x30" ? 30 : 1;
  return numeric.map((value, index) => (value / (coverage[index] ?? 1)) * multiplier);
}

/** Inclusive day coverage for each API bucket, including partial edge buckets. */
export function bucketDayCoverage(buckets: string[], start: string, end: string): number[] {
  return buckets.map((bucket, index) => {
    const bucketStart = index === 0 ? start : bucket;
    const next = buckets[index + 1];
    const bucketEnd = next ? addDays(next, -1) : end;
    return Math.max(daysBetween(bucketStart, bucketEnd) + 1, 1);
  });
}

function transformProjection(
  projection: QueryProjection | null,
  display: ExploreDisplay,
  interval: QueryInterval,
  displayedAnchor: number | null,
): DisplayProjection | null {
  if (projection === null) return null;
  const values = projection.values.map(Number);
  let transformed: number[];
  if (display === "delta") {
    const anchor = projection.anchor === null ? null : Number(projection.anchor);
    transformed = values.map((value, index) =>
      index === 0 ? value - (anchor ?? 0) : value - values[index - 1]!,
    );
  } else if (display === "daily_average" || display === "daily_average_x30") {
    const multiplier = display === "daily_average_x30" ? 30 : 1;
    transformed = values.map(
      (value, index) =>
        (value / futureBucketDays(projection.buckets[index]!, interval)) * multiplier,
    );
  } else {
    transformed = values;
  }
  return { ...projection, anchor: displayedAnchor, values: transformed };
}

function futureBucketDays(bucket: string, interval: QueryInterval): number {
  if (interval === "day") return 1;
  if (interval === "week") return 7;
  const day = parseDay(bucket);
  return new Date(Date.UTC(day.getUTCFullYear(), day.getUTCMonth() + 1, 0)).getUTCDate();
}

function daysBetween(from: string, to: string): number {
  return Math.round((parseDay(to).getTime() - parseDay(from).getTime()) / DAY_MS);
}

function addDays(value: string, days: number): string {
  const date = parseDay(value);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function parseDay(value: string): Date {
  return new Date(`${value}T00:00:00Z`);
}
