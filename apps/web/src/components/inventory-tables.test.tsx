import userEvent from "@testing-library/user-event";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import * as fx from "@/test/fixtures";
import { spendKey } from "@/lib/dimensions";

import { InventoryTables } from "./inventory-tables";

const spend = {
  [spendKey(fx.apiKeys[0]!.provider, fx.apiKeys[0]!.external_id)]: {
    amount: "12.50",
    tokens: 100,
  },
};

describe("InventoryTables", () => {
  it("filters keys by text and unused state", async () => {
    const user = userEvent.setup();
    render(
      <InventoryTables
        kind="api-keys"
        apiKeys={fx.apiKeys}
        spend={spend}
        periodLabel="October 2026"
        showProvider
      />,
    );

    expect(screen.getByText("2 of 2 keys")).toBeInTheDocument();
    await user.type(screen.getByRole("searchbox", { name: "Search keys" }), "batch");
    expect(screen.getByText("1 of 2 keys")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "batch-ingest" })).toBeInTheDocument();

    await user.clear(screen.getByRole("searchbox", { name: "Search keys" }));
    await user.click(screen.getByRole("button", { name: "Unused in October 2026" }));
    expect(screen.getByText("1 of 2 keys")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "retired" })).toBeInTheDocument();
  });

  it("renders workspace and user-specific columns", () => {
    const { rerender } = render(
      <InventoryTables
        kind="workspaces"
        workspaces={fx.workspaces}
        spend={{}}
        periodLabel="October 2026"
      />,
    );
    fireEvent.click(screen.getAllByText("Details")[0]!);
    expect(screen.getByText(/admins/i)).toBeInTheDocument();
    expect(screen.getByText("alice@example.com")).toBeInTheDocument();

    rerender(
      <InventoryTables kind="users" users={fx.users} spend={{}} periodLabel="October 2026" />,
    );
    expect(screen.getByRole("link", { name: "across providers" })).toBeInTheDocument();
  });

  it("shows the inventory empty state", () => {
    render(<InventoryTables kind="api-keys" apiKeys={[]} spend={{}} periodLabel="October 2026" />);
    expect(screen.getByText(/No keys in the inventory/)).toBeInTheDocument();
  });

  it("explains an empty table by what the provider lists, and offers no sync on the sample", () => {
    const { unmount } = render(
      <InventoryTables
        kind="users"
        users={[]}
        spend={{}}
        periodLabel="October 2026"
        provider="openrouter"
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "OpenRouter lists members only for an organization account",
    );
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    unmount();

    render(
      <InventoryTables
        kind="workspaces"
        workspaces={[]}
        spend={{}}
        periodLabel="October 2026"
        provider="anthropic"
        isDemo
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "The sample has no workspaces in this scope.",
    );
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
