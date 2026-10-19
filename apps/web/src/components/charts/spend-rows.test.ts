import { describe, expect, it } from "vitest";

import type { DailySeries } from "@/lib/api";

import {
  PROJECTION_BAND_KEY,
  PROJECTION_KEY,
  bucketedAsDaily,
  buildRows,
  clipMarkers,
  dimensionTotals,
  markerBucket,
  markerDots,
  markerList,
  safeMarkerHref,
  summarizeMarkers,
} from "./spend-rows";

const series: DailySeries = {
  month: "2026-09",
  dimension: "model",
  source: "cost",
  days: ["2026-09-01", "2026-09-02", "2026-09-03"],
  series: [{ key: "a", label: "A", provider: "openai", values: ["1", "2", "0"], total: "3" }],
  other: ["0.5", "0.5", "0"],
  total: ["1.5", "2.5", "0"],
  month_total: "4",
};

describe("buildRows", () => {
  it("adds series and other per day, and running sums in cumulative mode", () => {
    expect(buildRows(series, "daily", null).map((row) => row.total)).toEqual([1.5, 2.5, 0]);
    const cumulative = buildRows(series, "cumulative", null);
    expect(cumulative.map((row) => row.total)).toEqual([1.5, 4, 4]);
    expect(cumulative.map((row) => row.s0)).toEqual([1, 3, 3]);
  });

  it("projects stored forecasts with a band and falls back to the daily average", () => {
    const stored = buildRows(series, "daily", {
      fromDay: "2026-09-02",
      days: [{ day: "2026-09-03", expected: "2", low: "1", high: "5" }],
    });
    expect(stored[2]![PROJECTION_KEY]).toBe(2);
    expect(stored[2]![PROJECTION_BAND_KEY]).toBe(3);
    expect(stored[1]![PROJECTION_KEY]).toBeUndefined();

    const cumulative = buildRows(series, "cumulative", {
      fromDay: "2026-09-02",
      dailyAverage: "2",
    });
    expect(cumulative[2]![PROJECTION_KEY]).toBe(6);
  });

  it("attaches each marker to the bucket its first day falls in", () => {
    const rows = buildRows(series, "daily", null, [
      { day: "2026-09-02", endDay: "2026-09-03", label: "episode" },
    ]);
    expect(rows.map((row) => markerList(row).length)).toEqual([0, 1, 0]);
  });
});

describe("markers", () => {
  it("finds the bucket, clips markers before the range and keeps links same-origin", () => {
    expect(markerBucket("2026-09-10", ["2026-09-01", "2026-09-08"])).toBe("2026-09-08");
    expect(markerBucket("2026-08-30", ["2026-09-01"])).toBe("2026-09-01");
    expect(
      clipMarkers(
        [
          { day: "2026-08-20", label: "gone" },
          { day: "2026-08-30", endDay: "2026-09-02", label: "spans in" },
        ],
        ["2026-09-01"],
      ).map((marker) => marker.label),
    ).toEqual(["spans in"]);
    expect(clipMarkers([{ day: "2026-09-01", label: "x" }], [])).toEqual([]);
    expect(safeMarkerHref("/anomalies/1")).toBe("/anomalies/1");
    expect(safeMarkerHref("//evil.example")).toBeNull();
    expect(safeMarkerHref("https://evil.example")).toBeNull();
  });

  it("sizes one dot per bucket and summarizes the worst anomaly", () => {
    const rows = buildRows(series, "daily", null, [
      { day: "2026-09-01", label: "small", radius: 3, impact: "1", kind: "open" },
      {
        day: "2026-09-01",
        label: "org",
        radius: 5,
        emphasis: "primary",
        impact: "9",
        note: "org +9; A +1",
        count: 2,
        kind: "open",
      },
    ]);
    expect(markerDots(rows)).toEqual([
      { day: "2026-09-01", total: 1.5, radius: 5, emphasis: "primary" },
    ]);
    const summary = summarizeMarkers(rows.flatMap(markerList));
    expect(summary).toMatchObject({ count: 3, days: 2, openOnly: true, worstCause: "org +9" });
    expect(summarizeMarkers([])).toBeNull();
  });
});

describe("bucketed data", () => {
  const bucketed = {
    buckets: ["2026-09-01", "2026-09-08"],
    series: [{ key: "a", label: "A", provider: null, values: [1, "2"], total: 3 }],
    other: [0.5, 0.5],
    total: [1.5, 2.5],
  };

  it("zero-fills future buckets in the daily shape", () => {
    const daily = bucketedAsDaily(bucketed, ["2026-09-15"]);
    expect(daily.days).toEqual(["2026-09-01", "2026-09-08", "2026-09-15"]);
    expect(daily.series[0]!.values).toEqual(["1", "2", "0"]);
    expect(daily.other).toEqual(["0.5", "0.5", "0"]);
    expect(daily.month_total).toBe("4");
  });

  it("totals each dimension value and the other bucket", () => {
    expect(dimensionTotals(bucketed)).toEqual([
      { key: "s0", index: 0, label: "A", value: 3 },
      { key: "__other__", index: null, label: "other", value: 1 },
    ]);
  });
});
