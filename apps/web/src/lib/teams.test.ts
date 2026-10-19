import { describe, expect, it } from "vitest";

import * as fx from "@/test/fixtures";

import { teamScopeOptions } from "./budgets";
import { memberOptions, memberValue, teamSlug } from "./teams";

describe("teams", () => {
  it("derives a slug the API accepts from a name", () => {
    expect(teamSlug(" Data Platform ")).toBe("data-platform");
    expect(teamSlug("Pesquisa & Inovação")).toBe("pesquisa-inovacao");
    expect(teamSlug("---")).toBe("");
  });

  it("offers people once per e-mail, then live workspaces and active keys", () => {
    const groups = memberOptions(fx.users, fx.workspaces, fx.apiKeys);
    const people = groups.find((g) => g.label === "People")!.options;
    expect(new Set(people.map((o) => o.value)).size).toBe(people.length);
    expect(people.every((o) => o.value.startsWith("person|all|"))).toBe(true);
    expect(memberValue({ kind: "api_key", provider: "openai", external_id: "k|1" })).toBe(
      "api_key|openai|k|1",
    );
  });

  it("lists team budget targets under every provider", () => {
    expect(teamScopeOptions([{ slug: "growth", name: "Growth" }])).toEqual([
      { value: "team:growth", label: "Team Growth" },
    ]);
  });
});
