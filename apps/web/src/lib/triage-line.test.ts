import { describe, expect, it } from "vitest";

import { triageLine } from "./anomaly-text";

describe("triageLine", () => {
  it("says who triaged an anomaly and why", () => {
    expect(
      triageLine({
        status: "acknowledged",
        status_reason: "expected: backfill",
        status_changed_by: "ana@example.com",
      }),
    ).toBe("acknowledged by ana@example.com: expected: backfill");
    expect(
      triageLine({ status: "open", status_reason: null, status_changed_by: "ana@example.com" }),
    ).toBeNull();
    expect(
      triageLine({ status: "ignored", status_reason: null, status_changed_by: null }),
    ).toBeNull();
  });
});
