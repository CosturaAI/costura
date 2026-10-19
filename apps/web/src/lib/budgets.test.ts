import { describe, expect, it } from "vitest";

import * as fx from "@/test/fixtures";

import {
  alertSentence,
  budgetPeriod,
  budgetTone,
  currentPeriodLabel,
  parseThresholds,
} from "./budgets";

describe("parseThresholds", () => {
  it("accepts comma or space separated whole percentages and keeps the API default on empty", () => {
    expect(parseThresholds("50, 80, 100")).toEqual([50, 80, 100]);
    expect(parseThresholds("90 60")).toEqual([90, 60]);
    expect(parseThresholds("   ")).toBeNull();
  });

  it("rejects fractions and values outside 1..200", () => {
    expect(parseThresholds("50.5")).toBeUndefined();
    expect(parseThresholds("0, 50")).toBeUndefined();
    expect(parseThresholds("250")).toBeUndefined();
    expect(parseThresholds("abc")).toBeUndefined();
  });
});

describe("budgetTone", () => {
  it("is critical past 100% or when the projection exceeds, warning after a lower threshold", () => {
    expect(budgetTone(fx.orgBudgetStatus)).toBe("warning");
    expect(budgetTone(fx.workspaceBudgetStatus)).toBe("critical");
    expect(budgetTone({ ...fx.orgBudgetStatus, percent: "104.00" })).toBe("critical");
    expect(
      budgetTone({ ...fx.orgBudgetStatus, percent: "12.00", highest_crossed: null, alerts: [] }),
    ).toBe("neutral");
  });
});

describe("alertSentence", () => {
  it("words threshold and projection alerts with the day, label and amounts", () => {
    expect(alertSentence(fx.thresholdAlert)).toBe(
      "Aug 9: Platform crossed 80% (8,120.00 of 10,000.00)",
    );
    expect(alertSentence(fx.projectionAlert)).toBe(
      "Aug 9: Platform is projected to end the month at 11,800.00, above the 10,000.00 budget",
    );
  });
});

describe("budget periods", () => {
  it("names the day or week a day or week budget reads, and the day an alert crossed", () => {
    const weekly = {
      ...fx.orgBudgetStatus,
      budget: { ...fx.orgBudget, period: "week" as const },
      period_start: "2026-08-17",
      period_end: "2026-08-24",
    };
    expect(currentPeriodLabel(weekly)).toBe("week of Aug 17");
    expect(currentPeriodLabel(fx.orgBudgetStatus)).toBeNull();
    expect(
      alertSentence({ ...fx.thresholdAlert, period_start: "2026-08-11", threshold: 100 }),
    ).toContain("crossed 100% on Aug 11");
    expect(budgetPeriod("day").per).toBe("a day");
  });
});
