import { describe, expect, it } from "vitest";

import { safeNextPath, switchedOrgPath } from "./return-path";

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

describe("switchedOrgPath", () => {
  it.each([
    ["/settings/audit", "/settings"],
    ["/settings/advanced?x=1", "/settings"],
    ["/anomalies/42", "/anomalies"],
    ["/keys/k-1", "/inventory?kind=api-keys"],
    ["/workspaces/w-1", "/inventory?kind=workspaces"],
    ["/people/ana%40example.com", "/inventory?kind=users"],
    ["/accounts/7", "/overview"],
    ["/models/gpt-5", "/overview"],
  ])("moves %s to %s", (input, expected) => {
    expect(switchedOrgPath(input)).toBe(expected);
  });

  it("keeps a page every organization has", () => {
    expect(switchedOrgPath("/anomalies?status=open")).toBe("/anomalies?status=open");
    expect(switchedOrgPath("/explore?by=team")).toBe("/explore?by=team");
  });
});
