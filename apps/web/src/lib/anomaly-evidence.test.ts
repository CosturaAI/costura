import { describe, expect, it } from "vitest";

import * as fx from "@/test/fixtures";
import type { UnitEconomics, UsageTotals } from "./api";
import {
  changedSentence,
  checkValue,
  checksVerdict,
  economicsMoves,
  economicsSentence,
  tokenMix,
} from "./anomaly-evidence";

const evidence = fx.anomalyEvidence;
const baseline = evidence.baseline!;
const economics = evidence.unit_economics!;

describe("anomaly evidence", () => {
  it("formats day and money checks", () => {
    expect(checkValue({ ...evidence.checks[0]!, name: "history" }, "12.4")).toBe("12 days");
    expect(checkValue(evidence.checks[0]!, "12.50")).toBe("12.50");
    expect(checkValue(evidence.checks[0]!, null)).toBe("-");
  });

  it("describes empty, all-held and failing checks", () => {
    expect(checksVerdict([], null)).toMatch(/cannot be recomputed/);
    expect(checksVerdict(evidence.checks, baseline)).toMatch(/8 of 8 checks hold/);
    const failing = [{ ...evidence.checks[0]!, passed: false }];
    expect(checksVerdict(failing, baseline)).toMatch(/failing: above the upper bound/);
  });

  it("names only fields that changed after detection", () => {
    expect(changedSentence(baseline)).toBeNull();
    expect(
      changedSentence({
        ...baseline,
        matches_stored: false,
        actual_now: "1500.00",
        median: "700.00",
        upper_bound: "1000.00",
      }),
    ).toMatch(/spent.*expected.*upper bound/);
  });

  it("handles unknown, one-sided and infinite economics", () => {
    const none: UnitEconomics = {
      day: { ...economics.day, total_tokens: 0, request_count: 0, cost_per_million: null },
      baseline: {
        ...economics.baseline,
        total_tokens: 0,
        request_count: 0,
        cost_per_million: null,
      },
      sample_days: 0,
    };
    expect(economicsSentence(none)).toMatch(/No usage report/);

    const oneSided = {
      ...none,
      day: { ...none.day, total_tokens: 10, cost_per_million: null },
    };
    expect(economicsSentence(oneSided)).toMatch(/went from nothing/);

    const fromZero = {
      ...economics,
      baseline: { ...economics.baseline, total_tokens: 0 },
    };
    expect(economicsMoves(fromZero)[0]!.ratio).toBe(Infinity);
    expect(economicsSentence(fromZero)).toMatch(/went from nothing/);
  });

  it("selects volume or price as the largest move", () => {
    expect(economicsSentence(economics)).toMatch(/Price moved most|Volume moved most/);
    const priceMove = {
      ...economics,
      day: { ...economics.day, total_tokens: 182_000_000, cost_per_million: "30" },
    };
    expect(economicsSentence(priceMove)).toMatch(/Price moved most/);
  });

  it("returns zero token mix for no usage and percentages otherwise", () => {
    const totals: UsageTotals = { ...economics.day, total_tokens: 0, tokens: {} };
    expect(tokenMix(totals).every((row) => row.percent === 0)).toBe(true);
    const mix = tokenMix(economics.day);
    expect(mix.find((row) => row.label === "Input")!.percent).toBeGreaterThan(0);
  });
});
