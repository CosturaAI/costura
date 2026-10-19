import { describe, expect, it } from "vitest";

import { safeNextPath } from "./return-path";

describe("safeNextPath", () => {
  it("keeps a path on this origin with its query", () => {
    expect(safeNextPath("/overview?org=acme")).toBe("/overview?org=acme");
  });

  it.each([
    [null],
    [""],
    ["https://evil.com/"],
    ["//evil.com"],
    ["/\\evil.com"],
    ["/\t/evil.com"],
    ["/\n/evil.com"],
    ["/\r/evil.com"],
    ["/\u0000/evil.com"],
  ])("falls back for %j", (input) => {
    expect(safeNextPath(input, "/home")).toBe("/home");
  });
});
