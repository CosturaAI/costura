import { describe, expect, it } from "vitest";

import { openFor, recurrenceNote } from "./signals";

describe("signal history wording", () => {
  it("names a recurrence from the second stretch on", () => {
    expect(recurrenceNote(0)).toBeNull();
    expect(recurrenceNote(1)).toBeNull();
    expect(recurrenceNote(2)).toBe("2nd time in 90 days");
    expect(recurrenceNote(3)).toBe("3rd time in 90 days");
    expect(recurrenceNote(11)).toBe("11th time in 90 days");
    expect(recurrenceNote(21)).toBe("21st time in 90 days");
  });

  it("says hours under two days and days after", () => {
    expect(openFor("1.0")).toBe("1 hour");
    expect(openFor("3.5")).toBe("3.5 hours");
    expect(openFor("120.0")).toBe("5 days");
  });
});
