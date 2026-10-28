import { describe, expect, it } from "vitest";

import * as fx from "@/test/fixtures";

import {
  coverageNote,
  partialCoverage,
  providerVerdict,
  rangeRunsPast,
  scopeBudget,
  scopeProjection,
} from "./overview";

const TODAY = new Date("2026-10-15T09:00:00Z");

describe("coverageNote", () => {
  it("names the last complete day only when it is before yesterday", () => {
    expect(coverageNote({ complete_through: "2026-10-14", data_stale: false }, TODAY)).toBeNull();
    expect(coverageNote({ complete_through: null, data_stale: false }, TODAY)).toBeNull();
    expect(coverageNote({ complete_through: "2026-10-12", data_stale: false }, TODAY)).toBe(
      "Data through Oct 12.",
    );
  });

  it("says when anomaly detection lags the data", () => {
    expect(
      coverageNote(
        { complete_through: "2026-10-14", data_stale: false, detection_through: "2026-10-10" },
        TODAY,
      ),
    ).toBe("Anomalies checked through Oct 10.");
  });

  it("warns when two accounts report the same organization", () => {
    expect(
      coverageNote(
        { complete_through: null, data_stale: false, duplicate_accounts: ["Main and Rotated"] },
        TODAY,
      ),
    ).toBe("Main and Rotated report the same organization; their spend may be counted twice.");
  });

  it("says when the last import failed", () => {
    expect(coverageNote({ complete_through: "2026-10-12", data_stale: true }, TODAY)).toBe(
      "Data through Oct 12. The last import failed.",
    );
    expect(coverageNote({ complete_through: "2026-10-14", data_stale: true }, TODAY)).toBe(
      "The last import failed.",
    );
  });
});

describe("partialCoverage", () => {
  it("is true when the comparison covers only part of the period", () => {
    expect(partialCoverage({ comparison_basis: "month_to_date" })).toBe(true);
    expect(partialCoverage({ comparison_basis: "full_month" })).toBe(false);
  });
});

describe("rangeRunsPast", () => {
  it("names the last complete day when a range ends after it", () => {
    expect(rangeRunsPast("2026-10-15", { complete_through: "2026-10-14" }, TODAY)).toBe(
      "2026-10-14",
    );
    expect(rangeRunsPast("2026-10-14", { complete_through: "2026-10-14" }, TODAY)).toBeNull();
    expect(rangeRunsPast("2026-10-14", { complete_through: "2026-10-12" }, TODAY)).toBe(
      "2026-10-12",
    );
    expect(rangeRunsPast("2026-10-15", { complete_through: null }, TODAY)).toBe("2026-10-14");
    expect(rangeRunsPast("2026-10-10", { complete_through: null }, TODAY)).toBeNull();
  });
});

describe("providerVerdict", () => {
  it("says whether the total matches the provider's own report", () => {
    expect(
      providerVerdict({
        provider_total: "10.00",
        provider_matches: true,
        provider_difference: "0.00",
      }),
    ).toEqual({ text: "matches provider", tone: "success" });
    expect(
      providerVerdict({
        provider_total: "10.00",
        provider_matches: false,
        provider_difference: "-2.50",
      }),
    ).toEqual({ text: "differs from provider by 2.50", tone: "critical" });
    expect(
      providerVerdict({ provider_total: null, provider_matches: null, provider_difference: null }),
    ).toEqual({ text: "provider check pending", tone: "neutral" });
  });
});

describe("scopeProjection", () => {
  const row = (provider: string, total: string, asOf: string) => ({
    ...fx.projections.projections[0]!,
    provider,
    projected_total: total,
    low: (Number(total) - 10).toFixed(2),
    high: (Number(total) + 10).toFixed(2),
    as_of_day: asOf,
    days: [{ day: "2026-08-20", expected: "5.00", low: "4.00", high: "6.00", samples: 4 }],
  });

  it("adds every provider and account of the scope", () => {
    const found = scopeProjection([
      row("anthropic", "6793.47", "2026-08-14"),
      row("openai", "3796.90", "2026-08-13"),
      row("openai", "309.24", "2026-08-14"),
    ]);
    expect(found).toMatchObject({
      projected_total: "10899.61",
      low: "10869.61",
      high: "10929.61",
      as_of_day: "2026-08-13",
    });
    expect(found?.days).toEqual([
      { day: "2026-08-20", expected: "15.00", low: "12.00", high: "18.00", samples: 4 },
    ]);
    expect(scopeProjection([])).toBeNull();
  });
});

describe("scopeBudget", () => {
  it("takes only an organization budget of the same provider scope", () => {
    const anthropic = fx.orgBudgetStatus;
    expect(scopeBudget([anthropic], anthropic.budget.provider)).toBe(anthropic);
    expect(scopeBudget([anthropic], "all")).toBeNull();
  });
});
