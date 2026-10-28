import { describe, expect, it } from "vitest";

import type { QueryMeasure, SpendQuery, Usage } from "@/lib/api";
import { changePercent } from "@/lib/format";

import {
  queryChartData,
  queryTotal,
  queryUsage,
  rangeUsage,
  rowKey,
  scopedFilters,
  spendQuery,
} from "./spend-query";

function query(measure: QueryMeasure, totals: Record<string, string>): SpendQuery {
  const entries = Object.entries(totals);
  return {
    measure,
    dimensions: ["model"],
    start: "2026-09-01",
    end: "2026-09-02",
    interval: "day",
    source: "allocated",
    buckets: ["2026-09-01", "2026-09-02"],
    series: entries.map(([key, total]) => ({
      keys: { model: key },
      labels: { model: key.toUpperCase() },
      provider: "openai",
      values: [total, "0"],
      total,
    })),
    other: null,
    total: [entries.reduce((sum, [, total]) => sum + Number(total), 0).toFixed(2), "0"],
    comparison: null,
    projection: null,
  };
}

const metadata: Usage = {
  dimension: "model",
  allocated: true,
  cost_total: "4.00",
  rows: [
    {
      key: "a",
      label: "A",
      provider: "openai",
      details: { family: "gpt" },
      amount: "3.00",
      share: "75.00",
      byok_amount: null,
      tokens: { reasoning_tokens: 7 },
      total_tokens: 10,
      web_search_requests: 0,
      person: null,
      provider_account_id: 4,
      provider_account_label: "prod",
    },
  ],
};

describe("spendQuery", () => {
  it("defaults to billed USD and adds the provider only under a concrete scope", () => {
    const base = { dimensions: ["model"], start: "a", end: "b", interval: "day" as const };
    expect(spendQuery({ provider: "all", ...base })).toEqual({
      measure: "billed_usd",
      ...base,
      filters: {},
    });
    expect(
      spendQuery({ provider: "openai", measure: "tokens_total", filters: { model: "x" }, ...base }),
    ).toMatchObject({ measure: "tokens_total", filters: { model: "x", provider: "openai" } });
    expect(scopedFilters("all", { model: "x" })).toEqual({ model: "x" });
  });
});

describe("totals", () => {
  it("sums buckets to cents and reports change only against a non-zero previous figure", () => {
    expect(queryTotal(query("billed_usd", { a: "1.005", b: "2" }))).toBe("3.00");
    expect(changePercent("150", "100")).toBe("50.00");
    expect(changePercent("150", "0")).toBeNull();
    expect(changePercent("150", null)).toBeNull();
    expect(rowKey(null, null, "total")).toBe("scope:total");
  });
});

describe("queryChartData", () => {
  it("appends the provider to a label that repeats across providers", () => {
    const base = query("billed_usd", { a: "3", b: "1" });
    const twins: SpendQuery = {
      ...base,
      series: base.series.map((s, i) => ({
        ...s,
        provider: i === 0 ? "anthropic" : "openai",
        keys: { person: null },
        labels: { person: "(api key request)" },
      })),
    };
    expect(queryChartData(twins, "person").series.map((s) => s.label)).toEqual([
      "(api key request) Anthropic",
      "(api key request) OpenAI",
    ]);
    expect(queryChartData(base, "model").series.map((s) => s.label)).toEqual(["A", "B"]);
  });

  it("keeps the first series and folds the rest into other", () => {
    const chart = queryChartData(query("billed_usd", { a: "3", b: "1", c: "2" }), "model", 1);
    expect(chart.series.map((series) => series.label)).toEqual(["A"]);
    expect(chart.other).toEqual([3, 0]);
    expect(queryChartData(query("billed_usd", { a: "3" }), "model").other).toBeNull();
  });
});

describe("usage rows", () => {
  it("enriches billed rows with the month report and computes shares", () => {
    const usage = queryUsage(query("billed_usd", { a: "3", b: "1" }), "model", metadata);
    expect(usage).toMatchObject({ dimension: "model", allocated: true, cost_total: "4.00" });
    expect(usage.rows[0]).toMatchObject({
      key: "a",
      amount: "3.00",
      share: "75.00",
      details: { family: "gpt" },
      provider_account_label: "prod",
    });
    expect(usage.rows[1]).toMatchObject({ key: "b", share: "25.00", details: {} });
  });

  it("joins every measure per row and falls back to tokens when nothing is billed", () => {
    const byMeasure = new Map<QueryMeasure, SpendQuery>([
      ["billed_usd", query("billed_usd", { a: "3" })],
      ["tokens_total", query("tokens_total", { a: "10", b: "5" })],
      ["tokens_input", query("tokens_input", { a: "6" })],
      ["byok_usd", query("byok_usd", { a: "0.5" })],
    ]);
    const usage = rangeUsage("model", metadata, byMeasure);
    expect(usage.rows).toHaveLength(1);
    expect(usage.rows[0]).toMatchObject({
      amount: "3.00",
      share: "100.00",
      byok_amount: "0.50",
      total_tokens: 10,
      tokens: { uncached_input_tokens: 6, reasoning_tokens: 7 },
    });

    byMeasure.set("billed_usd", query("billed_usd", {}));
    const tokensOnly = rangeUsage("model", metadata, byMeasure);
    expect(tokensOnly.rows.map((row) => [row.key, row.amount, row.total_tokens])).toEqual([
      ["a", null, 10],
      ["b", null, 5],
    ]);
    expect(tokensOnly.allocated).toBe(false);
  });

  it("takes the counters of a row missing from a token top N from the usage report", () => {
    const byMeasure = new Map<QueryMeasure, SpendQuery>([
      ["billed_usd", query("billed_usd", { a: "3", c: "1" })],
      ["tokens_total", query("tokens_total", { c: "4" })],
    ]);
    const rows = rangeUsage("model", metadata, byMeasure).rows;
    expect(rows.map((row) => [row.key, row.total_tokens])).toEqual([
      ["a", 10],
      ["c", 4],
    ]);
  });
});
