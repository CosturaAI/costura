import { describe, expect, it } from "vitest";

import { activeTokenTypes, drillDownHref, entityHref, idHint, splitLabel } from "./dimensions";
import {
  formatCompactUsd,
  formatDate,
  formatDateTime,
  formatDayRange,
  formatDayShort,
  formatDelta,
  formatDuration,
  formatMinute,
  formatMonth,
  formatPercent,
  formatRelative,
  formatSignedUsd,
  formatTokens,
  formatUsd,
} from "./format";

describe("formatCompactUsd", () => {
  it("abbreviates thousands and millions for axis labels", () => {
    expect(formatCompactUsd("56056.12")).toBe("$56.1K");
    expect(formatCompactUsd(1250000)).toBe("$1.3M");
    expect(formatCompactUsd(950)).toBe("$950.00");
    expect(formatCompactUsd(null)).toBe("-");
  });
});

describe("formatDelta", () => {
  it("signs the change and returns null without a baseline", () => {
    expect(formatDelta("12.11")).toBe("+12.11%");
    expect(formatDelta(-3)).toBe("-3.00%");
    expect(formatDelta("0")).toBe("0.00%");
    expect(formatDelta(null)).toBeNull();
    expect(formatDelta("nan")).toBeNull();
  });
});

describe("formatSignedUsd", () => {
  it("signs a rise and keeps the minus of a fall", () => {
    expect(formatSignedUsd("12.5")).toBe("+12.50");
    expect(formatSignedUsd("-12.5")).toBe("-12.50");
    expect(formatSignedUsd("0")).toBe("0.00");
    expect(formatSignedUsd(null)).toBe("-");
  });
});

describe("month and day labels", () => {
  it("spells the month and shortens days", () => {
    expect(formatMonth("2026-08")).toBe("August 2026");
    expect(formatMonth("2026-13")).toBe("2026-13");
    expect(formatDayShort("2026-08-07")).toBe("Aug 7");
    expect(formatDayShort("bogus")).toBe("bogus");
    expect(formatDayRange("2026-08-01", "2026-08-14")).toBe("Aug 1 to Aug 14");
    expect(formatDayRange("2026-08-01", "2026-08-01")).toBe("Aug 1");
  });
});

describe("dimensions", () => {
  it("splits provider labels into name and id", () => {
    expect(splitLabel("batch-ingest (apikey_redacted_2)")).toEqual({
      name: "batch-ingest",
      id: "apikey_redacted_2",
    });
    expect(splitLabel("(default workspace)")).toEqual({ name: "(default workspace)", id: null });
    expect(splitLabel("claude-sonnet-5")).toEqual({ name: "claude-sonnet-5", id: null });
  });

  it("shrinks a 64-hex key hash to its last four characters and keeps short ids whole", () => {
    expect(idHint("0fe3d4a1".repeat(8))).toBe("...d4a1");
    expect(idHint("apikey_redacted_2")).toBe("apikey_redacted_2");
  });

  it("builds drill-down links only for rows with a provider id", () => {
    expect(drillDownHref("api_key", "k1")).toBe("/explore?by=model&f=api_key%3Ais%3Ak1");
    expect(drillDownHref("workspace", "w1")).toBe("/explore?by=person&f=workspace%3Ais%3Aw1");
    expect(drillDownHref("workspace", "w1", "api_key")).toBe(
      "/explore?by=api_key&f=workspace%3Ais%3Aw1",
    );
    expect(drillDownHref("api_key", null)).toBeNull();
    // Creator rows are accounts: they drill into the models that account's keys used.
    expect(drillDownHref("creator", "u1")).toBe("/explore?by=model&f=account%3Ais%3Au1");
    expect(drillDownHref("colour", "x")).toBeNull();
    // Provider rows drill into its people, kept as a filter on the same scope.
    expect(drillDownHref("provider", "openrouter")).toBe(
      "/explore?by=person&f=provider%3Ais%3Aopenrouter",
    );
  });

  it("opens entity pages by id alone; the page resolves the provider", () => {
    expect(entityHref("api_key", "k1")).toBe("/keys/k1");
    expect(entityHref("creator", "u1")).toBe("/accounts/u1");
    expect(entityHref("model", "m1")).toBe("/models/m1");
    expect(entityHref("api_key", null)).toBeNull();
    expect(entityHref("provider", "anthropic")).toBeNull();
    // Accounts with an e-mail identity open the person page across providers; a person row
    // without one is an account nobody owns and keeps the provider account page.
    expect(entityHref("account", "u1", "a@x.io")).toBe("/people/a%40x.io");
    expect(entityHref("creator", "u1", "a@x.io")).toBe("/people/a%40x.io");
    expect(entityHref("account", "svc", null)).toBe("/accounts/svc");
    expect(entityHref("person", "a@x.io", "a@x.io")).toBe("/people/a%40x.io");
    expect(entityHref("person", "svc_eval", null)).toBe("/accounts/svc_eval");
  });

  it("keeps only the token counters some row carries", () => {
    const anthropic = { uncached_input_tokens: 10, cache_creation_5m_tokens: 2, output_tokens: 3 };
    const openrouter = { uncached_input_tokens: 5, reasoning_tokens: 4, output_tokens: 1 };
    expect(activeTokenTypes([anthropic]).map((t) => t.key)).toEqual([
      "uncached_input_tokens",
      "cache_creation_5m_tokens",
      "output_tokens",
    ]);
    expect(activeTokenTypes([anthropic, openrouter]).map((t) => t.key)).toEqual([
      "uncached_input_tokens",
      "cache_creation_5m_tokens",
      "output_tokens",
      "reasoning_tokens",
    ]);
    expect(activeTokenTypes([])).toEqual([]);
  });
});

describe("formatUsd", () => {
  it("groups thousands and keeps two decimals", () => {
    expect(formatUsd("56056.12")).toBe("56,056.12");
    expect(formatUsd("0.00")).toBe("0.00");
    expect(formatUsd(-0.5)).toBe("-0.50");
  });

  it("renders a dash for missing values", () => {
    expect(formatUsd(null)).toBe("-");
    expect(formatUsd(undefined)).toBe("-");
    expect(formatUsd("not-a-number")).toBe("-");
  });
});

describe("formatTokens", () => {
  it("groups thousands", () => {
    expect(formatTokens(134165)).toBe("134,165");
    expect(formatTokens(0)).toBe("0");
    expect(formatTokens(null)).toBe("-");
  });
});

describe("formatPercent", () => {
  it("appends the sign", () => {
    expect(formatPercent("83.17")).toBe("83.17%");
    expect(formatPercent(100)).toBe("100.00%");
    expect(formatPercent(null)).toBe("-");
  });
});

describe("dates and durations", () => {
  it("prints UTC timestamps and plain dates", () => {
    expect(formatDateTime("2026-08-10T12:34:56.789+00:00")).toBe("2026-08-10 12:34:56 UTC");
    expect(formatDateTime(null)).toBe("-");
    expect(formatDate("2026-08-10T00:00:00+00:00")).toBe("2026-08-10");
  });

  it("switches units at one minute", () => {
    expect(formatDuration(12.34)).toBe("12.3s");
    expect(formatDuration(125)).toBe("2m 5s");
    expect(formatDuration(null)).toBe("-");
  });

  it("prints a scheduled instant to the minute", () => {
    expect(formatMinute("2026-09-15T06:00:00+00:00")).toBe("2026-09-15 06:00 UTC");
    expect(formatMinute(null)).toBe("-");
    expect(formatMinute("bogus")).toBe("-");
  });
});

describe("formatRelative", () => {
  const now = new Date("2026-09-15T12:00:00Z");

  it("names the distance in the largest unit that fits", () => {
    expect(formatRelative("2026-09-15T11:59:40Z", now)).toBe("just now");
    expect(formatRelative("2026-09-15T11:59:00Z", now)).toBe("1 minute ago");
    expect(formatRelative("2026-09-15T11:20:00Z", now)).toBe("40 minutes ago");
    expect(formatRelative("2026-09-15T10:00:00Z", now)).toBe("2 hours ago");
    expect(formatRelative("2026-09-14T06:00:00Z", now)).toBe("1 day ago");
    expect(formatRelative("2026-09-01T12:00:00Z", now)).toBe("14 days ago");
  });

  it("falls back to the date after a month and marks future instants", () => {
    expect(formatRelative("2026-06-01T12:00:00Z", now)).toBe("2026-06-01");
    expect(formatRelative("2026-09-16T06:00:00Z", now)).toBe("in 18 hours");
    expect(formatRelative(null, now)).toBe("-");
    expect(formatRelative("bogus", now)).toBe("-");
  });
});
