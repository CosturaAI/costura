/**
 * Pure chart model behind `DailySpendChart` and `BucketedSpendChart`: rows per bucket, the
 * projected values, and where the anomaly markers sit. No React, so every rule is unit-tested.
 */

import type { DailySeries, QueryValue } from "@/lib/api";
import type { DisplayProjection } from "@/lib/explore-display";

export const OTHER_KEY = "__other__";
export const PROJECTION_KEY = "__projection__";
export const PROJECTION_LOW_KEY = "__projection_low__";
export const PROJECTION_HIGH_KEY = "__projection_high__";
export const PROJECTION_BAND_KEY = "__projection_band__";
const MARKERS_KEY = "__markers__";
const DEFAULT_MARKER_RADIUS = 4;

export type Mode = "daily" | "cumulative";

export type Row = Record<string, number | string | Marker[]>;

/** One projected day: the expected amount and the band the samples span. */
type ProjectedBar = { day: string; expected: string; low: string; high: string };

export type Projection = {
  /** Last day that has data; days after it get the projected bar. */
  fromDay: string;
  /**
   * Per-day forecast from the stored projection. When absent, `dailyAverage` draws a flat bar
   * at the run rate (the summary's fallback before the scheduler has projected).
   */
  days?: ProjectedBar[];
  dailyAverage?: string;
};

/** The open anomalies of one day (or episode starting that day); links stay same-origin. */
import type { Marker } from "@/lib/ui-types";

export type BucketedSeriesData = {
  buckets: string[];
  series: {
    key: string | null;
    label: string;
    provider: string | null;
    values: QueryValue[];
    total: QueryValue;
  }[];
  other: QueryValue[] | null;
  total: QueryValue[];
};

type MarkerDot = {
  day: string;
  total: number;
  radius: number;
  emphasis: "primary" | "secondary";
};

type MarkerSummary = {
  count: number;
  days: number;
  openOnly: boolean;
  worst: Marker;
  worstCause: string;
};

const sum = (values: QueryValue[]) =>
  values.reduce<number>((total, value) => total + Number(value), 0);

/** A range query's buckets as the daily series the chart draws, future buckets zero-filled. */
export function bucketedAsDaily(
  data: BucketedSeriesData,
  futureBuckets: string[] = [],
): DailySeries {
  const pad = (values: QueryValue[]) => [...values.map(String), ...futureBuckets.map(() => "0")];
  return {
    month: "",
    dimension: "",
    source: "cost",
    days: [...data.buckets, ...futureBuckets],
    series: data.series.map((series) => ({
      ...series,
      values: pad(series.values),
      total: String(series.total),
    })),
    other: data.other ? pad(data.other) : null,
    total: pad(data.total),
    month_total: String(sum(data.total)),
  };
}

/**
 * One bar per dimension value: the total over the shown buckets times `scale`. The caller
 * passes untransformed totals and the scale of its display mode (1 / days for a daily
 * average), since a sum of per-bucket averages is not an average.
 */
export function dimensionTotals(data: BucketedSeriesData, scale = 1) {
  const rows = data.series.map((series, index) => ({
    key: `s${index}`,
    index: index as number | null,
    label: series.label,
    value: sum(series.values) * scale,
  }));
  if (data.other)
    rows.push({ key: OTHER_KEY, index: null, label: "other", value: sum(data.other) * scale });
  return rows;
}

export function markerList(row: Row): Marker[] {
  return Array.isArray(row[MARKERS_KEY]) ? (row[MARKERS_KEY] as Marker[]) : [];
}

export function safeMarkerHref(href: string | null | undefined): string | null {
  return href?.startsWith("/") && !href.startsWith("//") ? href : null;
}

/** Markers that end before the first shown bucket are out of range. */
export function clipMarkers(markers: Marker[], buckets: string[]): Marker[] {
  if (buckets.length === 0) return [];
  const first = buckets[0];
  return markers.filter((marker) => (marker.endDay ?? marker.day) >= first!);
}

/** The bucket a day falls in: the last bucket starting on or before it. */
export function markerBucket(day: string, buckets: string[]): string {
  for (let index = buckets.length - 1; index >= 0; index -= 1) {
    const bucket = buckets[index]!;
    if (day >= bucket) return bucket;
  }
  return buckets[0] ?? day;
}

/** One dot per bucket with markers: the largest radius, primary when any marker is. */
export function markerDots(rows: Row[]): MarkerDot[] {
  return rows.flatMap((row) => {
    const markers = markerList(row);
    if (markers.length === 0) return [];
    return [
      {
        day: String(row.day),
        total: Number(row.total),
        radius: markers.reduce(
          (largest, marker) => Math.max(largest, marker.radius ?? DEFAULT_MARKER_RADIUS),
          0,
        ),
        emphasis: markers.some((marker) => marker.emphasis === "primary")
          ? ("primary" as const)
          : ("secondary" as const),
      },
    ];
  });
}

/** The one-line summary under the chart: how many anomalies, on how many days, the worst. */
export function summarizeMarkers(markers: Marker[]): MarkerSummary | null {
  if (markers.length === 0) return null;
  const worst = [...markers].sort((a, b) => Number(b.impact ?? 0) - Number(a.impact ?? 0))[0]!;
  return {
    count: markers.reduce((total, marker) => total + (marker.count ?? 1), 0),
    days: markers.length,
    openOnly: markers.every((marker) => marker.kind === "open"),
    worst,
    worstCause: worst.note?.split(";")[0] ?? worst.label,
  };
}

/**
 * One chart row per day; cumulative mode carries running sums. Projected days get the expected
 * amount and low/high estimates as canonical values. `__projection_band__` is the visual
 * distance from expected to high. An anomaly episode stays one dot on its first bucket and
 * retains its range in the tooltip.
 */
export function buildRows(
  data: DailySeries,
  mode: Mode,
  projection: Projection | null,
  markers: Marker[] = [],
  futureProjection: DisplayProjection | null = null,
): Row[] {
  const running = new Map<string, number>();
  let cumulativeTotal = 0;
  let cumulativeExpected = 0;
  let cumulativeLow = 0;
  let cumulativeHigh = 0;
  const elapsed = projection ? data.days.indexOf(projection.fromDay) + 1 : 0;
  const average = projection?.dailyAverage ? Number.parseFloat(projection.dailyAverage) : 0;
  const byDay = new Map((projection?.days ?? []).map((d) => [d.day, d]));
  const markersByBucket = new Map<string, Marker[]>();
  if (data.days.length > 0) {
    for (const marker of markers) {
      const bucket = markerBucket(marker.day, data.days);
      markersByBucket.set(bucket, [...(markersByBucket.get(bucket) ?? []), marker]);
    }
  }
  const futureByDay = new Map(
    (futureProjection?.buckets ?? []).map((day, index) => [
      day,
      futureProjection?.values[index] ?? 0,
    ]),
  );
  const futureAnchorDay =
    futureProjection && data.days.length > futureProjection.buckets.length
      ? data.days[data.days.length - futureProjection.buckets.length - 1]
      : null;
  const rows: Row[] = [];
  data.days.forEach((day, i) => {
    const row: Row = { day };
    let dayTotal = 0;
    const add = (key: string, value: number) => {
      dayTotal += value;
      const next = (running.get(key) ?? 0) + value;
      running.set(key, next);
      row[key] = mode === "daily" ? value : next;
    };
    data.series.forEach((s, si) => add(`s${si}`, Number.parseFloat(s.values[i] ?? "0")));
    if (data.other) add(OTHER_KEY, Number.parseFloat(data.other[i] ?? "0"));
    cumulativeTotal += dayTotal;
    row.total = mode === "daily" ? dayTotal : cumulativeTotal;
    if (projection && day > projection.fromDay) {
      const forecast = byDay.get(day);
      if (forecast) {
        const expected = Number.parseFloat(forecast.expected);
        const low = Number.parseFloat(forecast.low);
        const high = Number.parseFloat(forecast.high);
        cumulativeExpected += expected;
        cumulativeLow += low;
        cumulativeHigh += high;
        if (mode === "daily") {
          row[PROJECTION_KEY] = expected;
          row[PROJECTION_LOW_KEY] = low;
          row[PROJECTION_HIGH_KEY] = high;
          row[PROJECTION_BAND_KEY] = Math.max(high - expected, 0);
        } else {
          row[PROJECTION_KEY] = cumulativeTotal + cumulativeExpected;
          row[PROJECTION_LOW_KEY] = cumulativeTotal + cumulativeLow;
          row[PROJECTION_HIGH_KEY] = cumulativeTotal + cumulativeHigh;
          row[PROJECTION_BAND_KEY] = Math.max(cumulativeHigh - cumulativeExpected, 0);
        }
      } else if (projection.dailyAverage) {
        row[PROJECTION_KEY] =
          mode === "daily" ? average : average * (i + 1 - elapsed) + cumulativeTotal;
      }
    }
    if (futureProjection && day === futureAnchorDay && futureProjection.anchor !== null) {
      row[PROJECTION_KEY] = futureProjection.anchor;
    } else if (futureByDay.has(day)) {
      row[PROJECTION_KEY] = futureByDay.get(day)!;
    }
    const bucketMarkers = markersByBucket.get(day);
    if (bucketMarkers?.length) row[MARKERS_KEY] = bucketMarkers;
    rows.push(row);
  });
  return rows;
}
