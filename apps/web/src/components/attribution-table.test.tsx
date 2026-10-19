import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { UsageRow } from "@/lib/api";

import { AttributionTable } from "./attribution-table";

const tokens = {
  uncached_input_tokens: 1,
  cache_creation_5m_tokens: 0,
  cache_creation_1h_tokens: 0,
  cache_read_tokens: 0,
  output_tokens: 0,
  reasoning_tokens: 0,
};

function row(provider: string, overrides: Partial<UsageRow> = {}): UsageRow {
  return {
    key: "shared-key",
    label: "Shared key (shared-key)",
    provider,
    details: {},
    amount: "1.00",
    share: "50.00",
    byok_amount: null,
    tokens,
    total_tokens: 1,
    web_search_requests: 0,
    person: null,
    provider_account_id: null,
    provider_account_label: null,
    ...overrides,
  };
}

describe("AttributionTable", () => {
  it("keeps duplicate provider ids as distinct keyed rows", () => {
    render(
      <AttributionTable
        rows={[row("anthropic"), row("openrouter")]}
        dimension="api_key"
        allocated
        showProvider
      />,
    );

    const rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[0]!).getAllByRole("cell")[0]).toHaveTextContent("1");
    expect(within(rows[1]!).getAllByRole("cell")[0]).toHaveTextContent("2");
    expect(within(rows[0]!).getByRole("link")).toHaveAttribute("href", "/keys/shared-key");
    expect(within(rows[1]!).getByRole("link")).toHaveAttribute("href", "/keys/shared-key");
  });

  it("leaves the compact card's name column the space the figures do not take", () => {
    render(
      <AttributionTable
        rows={[
          row("anthropic", { byok_amount: "3.09", details: { status: "inactive" } }),
          row("openrouter"),
        ]}
        dimension="api_key"
        allocated
        showProvider
        caption="Top API keys"
        compact
      />,
    );

    // A fixed layout would hand the four figure columns 368 px and the name column nothing.
    const table = screen.getByRole("table", { name: "Top API keys" });
    expect(table.className).not.toContain("table-fixed");
    const first = screen.getAllByRole("row")[1];
    const name = within(first!).getAllByRole("cell")[1];
    expect(name!.className).toContain("max-w-0");
    expect(within(name!).getByRole("link").className).toContain("min-w-0");
    // The badges leave the name line, so the amount keeps its width.
    expect(within(name!).getByText("Anthropic").closest("div")).not.toContain(
      within(name!).getByRole("link"),
    );
    expect(within(name!).getByText("inactive")).toBeInTheDocument();
  });

  it("names the provider once when the account label already starts with it", () => {
    render(
      <AttributionTable
        rows={[
          row("anthropic", { provider_account_label: "Anthropic - Acme" }),
          row("openai", { provider_account_label: "Acme Platform" }),
        ]}
        dimension="api_key"
        allocated
        showProvider
        compact
      />,
    );
    const rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[0]!).getByText("Anthropic - Acme")).toBeInTheDocument();
    expect(within(rows[0]!).queryByText("Anthropic - Anthropic - Acme")).not.toBeInTheDocument();
    expect(within(rows[1]!).getByText("OpenAI - Acme Platform")).toBeInTheDocument();
  });
});
