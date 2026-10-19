import { describe, expect, it } from "vitest";

import type { SpendQuery } from "@/lib/api";

import { applyExploreDisplay, bucketDayCoverage, transformValues } from "./explore-display";

const query: SpendQuery = {
  measure: "billed_usd",
  dimensions: ["model"],
  start: "2026-01-29",
  end: "2026-02-10",
  interval: "month",
  source: "allocated",
  buckets: ["2026-01-29", "2026-02-01"],
  series: [
    {
      keys: { model: "a" },
      labels: { model: "A" },
      provider: "openai",
      values: ["30", "100"],
      total: "130",
    },
  ],
  other: ["6", "10"],
  total: ["36", "110"],
  comparison: null,
  projection: {
    mode: "linear",
    lookback: 8,
    horizon: 2,
    buckets: ["2026-03-01", "2026-04-01"],
    anchor: "110",
    values: ["120", "150"],
  },
};

describe("Explore display transforms", () => {
  it("keeps the first delta bucket and differences every later bucket", () => {
    expect(transformValues(["8", "13", "9"], "delta", [1, 1, 1])).toEqual([8, 5, -4]);
  });

  it("counts partial first and last calendar buckets", () => {
    expect(bucketDayCoverage(query.buckets, query.start, query.end)).toEqual([3, 10]);
    expect(applyExploreDisplay(query, "daily_average").total).toEqual([12, 11]);
    expect(applyExploreDisplay(query, "daily_average_x30").total).toEqual([360, 330]);
  });

  it("transforms series, other and future projection without mutating the response", () => {
    const displayed = applyExploreDisplay(query, "delta");

    expect(displayed.series[0]!.values).toEqual([30, 70]);
    expect(displayed.other).toEqual([6, 4]);
    expect(displayed.total).toEqual([36, 74]);
    expect(displayed.projection).toMatchObject({
      anchor: 74,
      values: [10, 30],
    });
    expect(query.series[0]!.values).toEqual(["30", "100"]);
  });

  it("averages the comparison over its own bucket days", () => {
    const displayed = applyExploreDisplay(
      {
        ...query,
        comparison: {
          start: "2025-12-29",
          end: "2026-01-10",
          buckets: ["2025-12-29", "2026-01-01"],
          series: [{ ...query.series[0]!, values: ["9", "20"], total: "29" }],
          other: null,
          total: ["9", "20"],
        },
      },
      "daily_average",
    );

    expect(displayed.comparison).toMatchObject({
      series: [{ values: [3, 2], total: 5 }],
      other: null,
      total: [3, 2],
    });
  });

  it("keeps totals and the projection as sent, and no projection stays none", () => {
    const displayed = applyExploreDisplay(query, "total");
    expect(displayed.total).toEqual([36, 110]);
    expect(displayed.projection).toMatchObject({ anchor: 110, values: [120, 150] });

    expect(applyExploreDisplay({ ...query, projection: null }, "delta").projection).toBeNull();
  });
});
