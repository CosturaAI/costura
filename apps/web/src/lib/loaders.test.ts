import { beforeEach, describe, expect, it, vi } from "vitest";

import * as fx from "@/test/fixtures";

const mocks = vi.hoisted(() => ({
  usage: vi.fn(),
  query: vi.fn(),
  queries: vi.fn(),
  movers: vi.fn(),
  projection: vi.fn(),
  anomalies: vi.fn(),
  signals: vi.fn(),
  budgetStatuses: vi.fn(),
  setup: vi.fn(),
  org: vi.fn(),
  providers: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: mocks };
});

import { RANGE_MEASURES, filterLabels, loadExplore } from "./explore";
import { settledRecord, settledValue } from "./loaders";
import { loadOverviewDetails } from "./overview";

const view = {
  org: "acme",
  provider: "all",
  month: "2026-08",
  from: "2026-08-01",
  to: "2026-08-31",
  interval: "day" as const,
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.usage.mockResolvedValue(fx.usage);
  mocks.query.mockImplementation(async (_org: string, request: { measure: string }) => ({
    ...fx.spendQuery,
    measure: request.measure,
  }));
  mocks.queries.mockImplementation(
    async (_org: string, request: { measures: string[]; projection?: string }) => ({
      results: request.measures.map((measure) => ({
        ...fx.spendQuery,
        measure,
        projection:
          measure === "billed_usd" && request.projection === "linear" ? { mode: "linear" } : null,
      })),
    }),
  );
  mocks.movers.mockResolvedValue(fx.movers);
  mocks.projection.mockResolvedValue(fx.projections);
  mocks.anomalies.mockResolvedValue(fx.anomalies);
  mocks.signals.mockResolvedValue(fx.signals);
  mocks.budgetStatuses.mockResolvedValue(fx.budgetStatuses);
  mocks.setup.mockRejectedValue(new Error("down"));
  mocks.org.mockResolvedValue(fx.organization);
  mocks.providers.mockResolvedValue(fx.providers);
});

describe("loadOverviewDetails", () => {
  it("settles each card on its own and asks for the provider split only in the all scope", async () => {
    const details = await loadOverviewDetails(view);

    expect(details.setup).toBeNull();
    expect(details.keys?.rows.length).toBe(fx.spendQuery.series.length);
    expect(details.byProvider).not.toBeNull();
    expect(details.anomalies).toBe(fx.anomalies);
    expect(details.signals).toBe(fx.signals);
    expect(mocks.query).toHaveBeenCalledWith(
      "acme",
      expect.objectContaining({
        dimensions: ["provider"],
        compare: "previous_period",
        filters: {},
      }),
    );

    mocks.query.mockClear();
    const single = await loadOverviewDetails({ ...view, provider: "anthropic" });
    expect(single.byProvider).toBeNull();
    expect(mocks.query).not.toHaveBeenCalledWith(
      "acme",
      expect.objectContaining({ dimensions: ["provider"] }),
    );
    expect(mocks.query).toHaveBeenCalledWith(
      "acme",
      expect.objectContaining({ filters: { provider: "anthropic" } }),
    );
  });
});

describe("loadExplore", () => {
  const request = {
    org: "acme",
    provider: "openai",
    month: "2026-08",
    by: "api_key",
    top: 25,
    filters: {},
    start: "2026-08-01",
    end: "2026-08-31",
    interval: "day" as const,
    compare: "none" as const,
    projection: "linear" as const,
    lookback: 8,
    horizon: 4,
  };

  it("loads every measure in one request and keeps the billed series", async () => {
    const result = await loadExplore(request);

    expect(mocks.queries).toHaveBeenCalledTimes(1);
    expect(mocks.queries).toHaveBeenCalledWith(
      "acme",
      expect.objectContaining({
        measures: RANGE_MEASURES,
        projection: "linear",
        lookback: 8,
        horizon: 4,
        filters: { provider: "openai" },
      }),
    );
    expect(mocks.query).not.toHaveBeenCalled();
    expect(result.billed.measure).toBe("billed_usd");
    expect(result.byMeasure.get("tokens_total")?.measure).toBe("tokens_total");
    expect(result.usage.dimension).toBe("api_key");
    expect(result.providers).toBe(fx.providers);
  });

  it("labels filters from the matching row and keeps text matches verbatim", async () => {
    mocks.usage.mockResolvedValue({ ...fx.usage, rows: [{ ...fx.usage.rows[0], label: "Prod" }] });

    const chips = await filterLabels(
      "acme",
      "openai",
      { from: "2026-08-01", to: "2026-08-31" },
      {
        api_key: "k1",
        model: { op: "contains", values: ["gpt", "o3"] },
        workspace: { op: "is", values: [] },
      },
    );

    expect(chips).toEqual([
      { name: "api_key", clause: { op: "is", values: ["k1"] }, label: "Prod" },
      { name: "model", clause: { op: "contains", values: ["gpt", "o3"] }, label: "gpt, o3" },
      { name: "workspace", clause: { op: "is", values: [] }, label: "" },
    ]);
  });

  it("labels every value of a clause from one report, not one report per value", async () => {
    mocks.usage.mockResolvedValue({
      ...fx.usage,
      rows: [
        { ...fx.usage.rows[0], key: "k2", label: "Batch (k2)" },
        { ...fx.usage.rows[0], key: "k1", label: "Prod (k1)" },
      ],
    });
    const [chip] = await filterLabels(
      "acme",
      "openai",
      { from: "2026-08-01", to: "2026-08-31" },
      { api_key: { op: "one_of", values: ["k1", "k2", "k3"] } },
    );
    expect(mocks.usage).toHaveBeenCalledTimes(1);
    expect(mocks.usage).toHaveBeenCalledWith(
      "acme",
      "openai",
      { from: "2026-08-01", to: "2026-08-31" },
      "api_key",
      3,
      { api_key: { op: "one_of", values: ["k1", "k2", "k3"] } },
    );
    expect(chip!.label).toBe("Prod, Batch, k3");
  });
});

describe("settledRecord", () => {
  it("keeps each result under its name and never rejects", async () => {
    const result = await settledRecord({
      ok: Promise.resolve(1),
      bad: Promise.reject(new Error("boom")),
    });
    expect(settledValue(result.ok)).toBe(1);
    expect(settledValue(result.bad)).toBeNull();
    expect(result.bad.status).toBe("rejected");
  });
});
