import { describe, expect, it } from "vitest";

import type { Run } from "@/lib/api";
import * as fx from "@/test/fixtures";

import { ageLabel, freshness, freshnessBand, freshnessTone } from "./freshness";

const NOW = new Date("2026-10-15T12:00:00Z");
const base = fx.runs[0] as Run;

function costRun(startedAt: string, status: Run["status"] = "succeeded"): Run {
  return { ...base, endpoint: "cost_report", status, started_at: startedAt };
}

describe("freshness by data age", () => {
  it("is green while the newest cost sync is under two days old", () => {
    const state = freshness([costRun("2026-10-14T06:00:00Z")]);
    expect(freshnessTone(state, NOW)).toBe("success");
    expect(ageLabel(state, NOW)).toBeNull();
    expect(freshnessBand([costRun("2026-10-14T06:00:00Z")], NOW)).toBeNull();
  });

  it("turns amber past two days and red past three, saying how old", () => {
    const amber = [costRun("2026-10-13T06:00:00Z")];
    expect(freshnessTone(freshness(amber), NOW)).toBe("warning");
    expect(freshnessBand(amber, NOW)).toBe("Spend data is 2 days old.");
    const red = [costRun("2026-10-10T06:00:00Z")];
    expect(freshnessTone(freshness(red), NOW)).toBe("critical");
    expect(ageLabel(freshness(red), NOW)).toBe("5 days old");
  });

  it("turns red on a failed latest run and names it in the band", () => {
    const runs = [costRun("2026-10-15T06:00:00Z", "failed"), costRun("2026-10-14T06:00:00Z")];
    expect(freshnessTone(freshness(runs), NOW)).toBe("critical");
    expect(freshnessBand(runs, NOW)).toBe("1 sync job failed on the latest run.");
  });

  it("stays neutral and silent before the first sync", () => {
    expect(freshnessTone(freshness([]), NOW)).toBe("neutral");
    expect(freshnessBand([], NOW)).toBeNull();
  });
});

describe("a failed current month", () => {
  it("stays failed when the previous month succeeded after it", () => {
    const run = (window: string, status: Run["status"], started: string): Run => ({
      ...base,
      endpoint: "cost_report",
      status,
      started_at: started,
      window_start: `${window}-01T00:00:00Z`,
    });
    const runs = [
      run("2026-09", "succeeded", "2026-10-15T06:05:00Z"),
      run("2026-10", "failed", "2026-10-15T06:00:00Z"),
      run("2026-09", "succeeded", "2026-10-14T06:05:00Z"),
      run("2026-10", "succeeded", "2026-10-14T06:00:00Z"),
    ];
    const state = freshness(runs);
    expect(state.failed).toBe(1);
    expect(freshnessTone(state, NOW)).toBe("critical");
  });
});

describe("the most stale account sets the freshness", () => {
  it("dates the data by the account that synced longest ago and names it", () => {
    const runs = [
      {
        ...costRun("2026-10-15T06:00:00Z"),
        provider: "openai",
        provider_account_id: 2,
        provider_account_label: "OpenAI",
      },
      {
        ...costRun("2026-10-10T06:00:00Z"),
        provider: "anthropic",
        provider_account_id: 1,
        provider_account_label: "Anthropic",
      },
    ];
    expect(freshnessTone(freshness(runs), NOW)).toBe("critical");
    expect(freshnessBand(runs, NOW)).toBe("Spend data for Anthropic is 5 days old.");
  });
});
