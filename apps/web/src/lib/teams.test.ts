import { describe, expect, it } from "vitest";

import * as fx from "@/test/fixtures";

import { teamScopeOptions } from "./budgets";
import { memberOptions, memberValue, teamMemberOptions, teamSlug } from "./teams";

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

  it("leaves out what the team holds and names the team of what would move", () => {
    const groups = [
      {
        label: "People",
        options: [
          { value: "person|all|ana@example.com", label: "ana@example.com" },
          { value: "person|all|bo@example.com", label: "bo@example.com" },
          { value: "person|all|cy@example.com", label: "cy@example.com" },
        ],
      },
      { label: "API keys", options: [{ value: "api_key|openai|k1", label: "ci (OpenAI)" }] },
    ];
    const member = (external_id: string, kind: "person" | "api_key" = "person") => ({
      kind,
      provider: kind === "person" ? "all" : "openai",
      external_id,
      label: external_id,
      updated_at: "2026-09-01T00:00:00Z",
    });
    const teams = [
      {
        slug: "growth",
        name: "Growth",
        members: [member("ana@example.com"), member("k1", "api_key")],
      },
      { slug: "platform", name: "Platform", members: [member("bo@example.com")] },
    ];
    expect(teamMemberOptions(groups, teams, "growth")).toEqual([
      {
        label: "People",
        options: [
          { value: "person|all|bo@example.com", label: "bo@example.com (in Platform)" },
          { value: "person|all|cy@example.com", label: "cy@example.com" },
        ],
      },
    ]);
  });

  it("lists team budget targets under every provider", () => {
    expect(teamScopeOptions([{ slug: "growth", name: "Growth" }])).toEqual([
      { value: "team:growth", label: "Team Growth" },
    ]);
  });
});
