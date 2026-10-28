import { describe, expect, it } from "vitest";

import {
  autoInterval,
  monthRange,
  monthToDate,
  monthsIn,
  periodPhrase,
  periodTitle,
  presetRange,
  rangeDays,
  shortRangeLabel,
  validRange,
  wholeMonth,
} from "./time-range";

const TODAY = new Date("2026-09-17T12:00:00Z");

describe("time ranges", () => {
  it("reads a range from the 1st to today as the month so far", () => {
    expect(monthToDate("2026-09-01", "2026-09-17", TODAY)).toBe("2026-09");
    expect(monthToDate("2026-09-02", "2026-09-17", TODAY)).toBeNull();
    expect(monthToDate("2026-09-01", "2026-09-16", TODAY)).toBeNull();
    expect(monthToDate("2026-08-01", "2026-09-17", TODAY)).toBeNull();
  });

  it("names a period as its month when it is one, else by its days", () => {
    expect(wholeMonth("2026-02-01", "2026-02-28")).toBe("2026-02");
    expect(wholeMonth("2026-02-01", "2026-02-27")).toBeNull();
    expect(wholeMonth("2026-01-31", "2026-02-28")).toBeNull();
    expect(periodPhrase("2026-08-01", "2026-08-31", TODAY)).toBe("in August 2026");
    expect(periodPhrase("2026-01-01", "2026-09-17", TODAY)).toBe("from Jan 1 to Sep 17");
    expect(periodPhrase("2026-09-17", "2026-09-17", TODAY)).toBe("on Sep 17");
    expect(periodTitle("2025-12-20", "2026-01-05", TODAY)).toBe("Dec 20, 2025 - Jan 5, 2026");
  });

  it("lists the months a period touches, newest first", () => {
    expect(monthsIn("2025-11-15", "2026-02-02")).toEqual([
      "2026-02",
      "2026-01",
      "2025-12",
      "2025-11",
    ]);
    expect(monthsIn("2026-08-03", "2026-08-09")).toEqual(["2026-08"]);
  });

  it("formats short range labels with the year only when needed", () => {
    expect(shortRangeLabel("2026-09-01", "2026-09-17", TODAY)).toBe("Sep 1 - Sep 17");
    expect(shortRangeLabel("2025-12-20", "2026-01-05", TODAY)).toBe("Dec 20, 2025 - Jan 5, 2026");
    expect(shortRangeLabel("2025-03-01", "2025-03-31", TODAY)).toBe("Mar 1 - Mar 31, 2025");
    expect(shortRangeLabel("2026-09-17", "2026-09-17", TODAY)).toBe("Sep 17");
    expect(shortRangeLabel("2025-09-17", "2025-09-17", TODAY)).toBe("Sep 17, 2025");
    expect(rangeDays("2026-09-01", "2026-09-30")).toBe(30);
  });

  it("uses the requested auto interval thresholds", () => {
    expect(autoInterval("2026-08-01", "2026-10-01")).toBe("day");
    expect(autoInterval("2026-01-01", "2026-12-31")).toBe("week");
    expect(autoInterval("2025-01-01", "2026-01-01")).toBe("month");
  });

  it("builds the calendar and rolling presets", () => {
    expect(presetRange("this_month", TODAY)).toEqual({
      from: "2026-09-01",
      to: "2026-09-17",
    });
    expect(presetRange("last_month", TODAY)).toEqual({
      from: "2026-08-01",
      to: "2026-08-31",
    });
    expect(presetRange("last_7_days", TODAY)).toEqual({
      from: "2026-09-10",
      to: "2026-09-16",
    });
    expect(presetRange("rolling_7_days", TODAY)).toEqual({
      from: "2026-09-11",
      to: "2026-09-17",
    });
    expect(presetRange("quarter", TODAY)).toEqual({
      from: "2026-07-01",
      to: "2026-09-17",
    });
    expect(presetRange("ytd", TODAY)).toEqual({
      from: "2026-01-01",
      to: "2026-09-17",
    });
  });

  it("turns a month into its range and rejects impossible dates", () => {
    expect(monthRange("2024-02")).toEqual({ from: "2024-02-01", to: "2024-02-29" });
    expect(validRange("2026-02-01", "2026-02-28")).toBe(true);
    expect(validRange("2026-02-30", "2026-03-01")).toBe(false);
    expect(validRange("0202-01-01", "2026-01-31")).toBe(false);
    expect(validRange("2099-12-01", "2100-01-01")).toBe(false);
    expect(validRange("2017-01-01", "2026-09-30")).toBe(true);
    expect(validRange("2015-01-01", "2026-09-30")).toBe(false);
    expect(validRange("2025-09-01", "2026-09-30", 400)).toBe(true);
    expect(validRange("2025-01-01", "2026-09-30", 400)).toBe(false);
    expect(validRange("2026-03-02", "2026-03-01")).toBe(false);
  });
});
