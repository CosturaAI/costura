import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import * as fx from "@/test/fixtures";

import { KeyGovernance } from "./key-governance";

vi.mock("@/actions/keys", () => ({
  snoozeGapAction: vi.fn(),
  liftSnoozeAction: vi.fn(),
}));

const key = fx.apiKeys[0]!;

describe("KeyGovernance", () => {
  it("names the gaps, the owner, the last use and the limit, and links the console", () => {
    render(
      <KeyGovernance
        apiKey={{
          ...key,
          owner: null,
          owner_source: null,
          creator_left: true,
          limit_reported: true,
          spend_limit: null,
          last_used_at: "2026-08-02T00:00:00Z",
          last_used_source: "derived",
        }}
        signals={[
          { ...fx.signals.items[1]!, kind: "no_owner" },
          { ...fx.signals.items[1]!, kind: "no_limit" },
        ]}
        consoleUrl="https://openrouter.ai/settings/keys"
        consoleLabel="OpenRouter"
      />,
    );
    expect(screen.getByText("no owner")).toBeInTheDocument();
    expect(screen.getAllByText("no limit")).toHaveLength(2);
    expect(screen.getByText(/the creator left the provider organization/)).toBeInTheDocument();
    expect(screen.getByText("2026-08-02 (from spend, day precision)")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Open the keys in OpenRouter" });
    expect(link).toHaveAttribute("href", "https://openrouter.ai/settings/keys");
    expect(link).toHaveAttribute("rel", "noreferrer");
  });

  it("says when the provider reports no per-key limit and nothing is open", () => {
    render(
      <KeyGovernance
        apiKey={{
          ...key,
          owner: "ana@example.com",
          owner_source: "creator",
          limit_reported: false,
        }}
        signals={[]}
        consoleUrl={null}
        consoleLabel="Anthropic"
      />,
    );
    expect(screen.getByText(/No open gap/)).toBeInTheDocument();
    expect(screen.getByText("ana@example.com, created the key")).toBeInTheDocument();
    expect(screen.getByText("the provider does not report a per-key limit")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});

const gap = fx.signals.items.find((s) => s.kind === "no_owner") ?? {
  ...fx.signals.items[0]!,
  kind: "no_owner" as const,
};

describe("KeyGovernance snoozes", () => {
  it("offers a snooze per open gap and lists the snoozed ones", () => {
    render(
      <KeyGovernance
        apiKey={fx.apiKeys[0]!}
        signals={[gap]}
        snoozes={[
          {
            kind: "no_limit",
            provider: "anthropic",
            key_id: gap.entity_id,
            until: "2026-11-14",
            note: "capped at the workspace",
          },
        ]}
        canSnooze
        consoleUrl={null}
        consoleLabel="Anthropic"
      />,
    );
    expect(screen.getByLabelText("Snooze no owner for")).toHaveValue("30");
    expect(
      screen.getByText("no limit snoozed until 2026-11-14: capped at the workspace"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Bring back now" })).toBeInTheDocument();
  });

  it("only states the snoozes where they cannot be changed", () => {
    render(
      <KeyGovernance
        apiKey={fx.apiKeys[0]!}
        signals={[]}
        snoozes={[
          { kind: "no_limit", provider: "anthropic", key_id: "k", until: "2026-11-14", note: null },
        ]}
        consoleUrl={null}
        consoleLabel="Anthropic"
      />,
    );
    expect(screen.getByText("no limit snoozed until 2026-11-14")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Snooze" })).not.toBeInTheDocument();
  });
});
