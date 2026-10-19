import { describe, expect, it } from "vitest";

import * as fx from "@/test/fixtures";
import { demoConnectHref, inventoryGap, sampleCopy, sampleProviders } from "./sample";

describe("sample copy", () => {
  it("swaps actions for what the read-only sample can do", () => {
    expect(sampleCopy.budgetsLink(true)).toBe("View budgets");
    expect(sampleCopy.budgetsLink(false)).toBe("Manage budgets");
    expect(sampleCopy.noBudget).toMatch(/fixed/);
  });

  it("names the inventory a provider never lists", () => {
    expect(inventoryGap("cursor", "api-keys")).toMatch(/no API keys/);
    expect(inventoryGap("cursor", "workspaces")).toMatch(/no workspaces/);
    expect(inventoryGap("cursor", "users")).toBeNull();
    expect(inventoryGap("openrouter", "users")).toMatch(/organization account/);
    expect(inventoryGap("anthropic", "users")).toBeNull();
  });

  it("keeps the providers the sample holds accounts for", () => {
    const empty = { ...fx.providers[0]!, provider: "codex", accounts: [] };
    const held = { ...fx.providers[0]!, accounts: [fx.connection.accounts[0]!] };
    expect(sampleProviders([held, empty]).map((p) => p.provider)).toEqual([held.provider]);
  });

  it("sends the reader to sign-in, a new organization or their own welcome", () => {
    expect(demoConnectHref(null)).toBe("/sign-in");
    expect(demoConnectHref([{ slug: "demo", is_demo: true }])).toBe("/new");
    expect(
      demoConnectHref([
        { slug: "demo", is_demo: true },
        { slug: "acme", is_demo: false },
      ]),
    ).toBe("/o/acme?next=%2Fwelcome");
  });
});
