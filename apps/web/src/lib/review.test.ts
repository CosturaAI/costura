import { describe, expect, it } from "vitest";

import * as fx from "@/test/fixtures";

import { type ReviewData, reviewMarkdown, reviewSections, reviewTitle } from "./review";

const data: ReviewData = {
  scope: fx.PROVIDER,
  month: fx.summary.month,
  summary: fx.summary,
  projections: fx.projections,
  budgets: fx.budgetStatuses,
  movers: fx.movers,
  anomalies: fx.anomalies,
  signals: fx.signals,
};

describe("reviewSections", () => {
  it("tells the month in five sections from the same reads as the other pages", () => {
    const sections = reviewSections(data);
    expect(sections.map((s) => s.title)).toEqual([
      "Where the money went",
      "Against the plan",
      "Largest moves",
      "Anomalies",
      "Needs a person",
    ]);
    expect(sections[0]!.lines[0]).toBe("Spend: 56,056.12 USD.");
    expect(sections[0]!.lines[1]).toBe("+12.11% against July 2026 (50,000.00 USD).");
    expect(sections[1]!.lines[0]).toMatch(/^Budget: .* of .* USD \(\d+(\.\d+)?%\)/);
    expect(sections[2]!.lines).toHaveLength(3);
    expect(sections[3]!.lines[0]).toBe("3 detected this month: 3 open, 0 acknowledged or ignored.");
    expect(sections[4]!.lines[0]).toBe("3 open besides the anomalies, most money first:");
  });

  it("keeps the required sections when the optional reads failed", () => {
    const sections = reviewSections({
      ...data,
      projections: null,
      budgets: null,
      movers: null,
      anomalies: null,
      signals: null,
    });
    expect(sections.map((s) => s.title)).toEqual([
      "Where the money went",
      "Against the plan",
      "Anomalies",
      "Needs a person",
    ]);
    expect(sections[1]!.lines).toEqual(["No budget covers this scope."]);
    expect(sections[3]!.lines).toEqual(["Nothing besides the anomalies."]);
  });
});

describe("reviewMarkdown", () => {
  it("writes a title, a heading per section and a bullet per line", () => {
    const title = reviewTitle("Acme", "all", "2026-08");
    expect(title).toBe("Acme: August 2026 in review, all providers");
    expect(reviewMarkdown(title, [{ title: "Anomalies", lines: ["a", "b"] }])).toBe(
      "# Acme: August 2026 in review, all providers\n\n## Anomalies\n\n- a\n- b\n",
    );
  });
});
