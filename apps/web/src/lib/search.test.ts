import { describe, expect, it } from "vitest";

import { queryCsvUrl } from "./query-export";
import { filtersFrom, parseFilterParam } from "./search";

describe("filter query clauses", () => {
  it("parses repeated clauses and existence operators", () => {
    expect(
      filtersFrom({
        f: ["model:is_not:gpt-4o", "provider_account:exists:"],
      }),
    ).toEqual({
      model: { op: "is_not", values: ["gpt-4o"] },
      provider_account: { op: "exists", values: [] },
    });
  });

  it("ignores malformed clauses and plain filter parameters", () => {
    expect(
      filtersFrom({
        model: "gpt-4o",
        f: ["unknown:is:value", "model:unknown:value", "model:is_not:", "model:is:gpt-5"],
      }),
    ).toEqual({ model: { op: "is", values: ["gpt-5"] } });
    expect(parseFilterParam("workspace:not_exists:")).toEqual({
      dimension: "workspace",
      clause: { op: "not_exists", values: [] },
    });
    expect(parseFilterParam("tag:team:is:Backend")).toBeNull();
  });

  it("serializes clauses as repeatable f parameters in CSV links", () => {
    const url = new URL(
      queryCsvUrl({
        measure: "billed_usd",
        dimensions: ["model"],
        start: "2026-09-01",
        end: "2026-09-30",
        interval: "day",
        filters: {
          model: { op: "is_not", values: ["gpt-4o"] },
          workspace: { op: "one_of", values: ["Backend", "Platform"] },
          provider: "anthropic",
        },
      }),
      "http://web.test",
    );

    expect(url.searchParams.getAll("f")).toEqual([
      "model:is_not:gpt-4o",
      "workspace:one_of:Backend,Platform",
    ]);
    expect(url.searchParams.get("provider")).toBe("anthropic");
  });

  it("carries top and the projection settings only when a projection is asked for", () => {
    const base = {
      measure: "billed_usd",
      start: "2026-09-01",
      end: "2026-09-30",
      interval: "week",
    };
    const projected = new URL(
      queryCsvUrl({ ...base, top: 5, projection: "linear", lookback: 8, horizon: 4 }),
      "http://web.test",
    );
    expect(Object.fromEntries(projected.searchParams)).toEqual({
      ...base,
      dimensions: "",
      compare: "none",
      top: "5",
      projection: "linear",
      lookback: "8",
      horizon: "4",
    });

    const flat = new URL(
      queryCsvUrl({ ...base, projection: "none", lookback: 8 }),
      "http://web.test",
    );
    expect(flat.searchParams.has("projection")).toBe(false);
    expect(flat.searchParams.has("lookback")).toBe(false);
  });
});
