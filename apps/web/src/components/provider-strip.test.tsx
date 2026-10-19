import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProviderStrip, type ProviderShare } from "./provider-strip";

const items: ProviderShare[] = [
  {
    key: "anthropic",
    label: "Anthropic",
    amount: "2679.47",
    share: "76.62",
    href: "/default/all/2026-08/explore?by=api_key&provider=anthropic",
  },
  { key: "openrouter", label: "OpenRouter", amount: "817.72", share: "23.38", href: null },
];

describe("ProviderStrip", () => {
  it("names each provider with its amount, share and drill-down", () => {
    render(<ProviderStrip items={items} />);

    const legend = screen.getByRole("list", { name: "Spend by provider" });
    const rows = within(legend).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Anthropic");
    expect(rows[0]).toHaveTextContent("2,679.47 USD");
    expect(rows[0]).toHaveTextContent("76.62%");
    expect(within(rows[0]!).getByRole("link")).toHaveAttribute(
      "href",
      "/default/all/2026-08/explore?by=api_key&provider=anthropic",
    );
    // A sentinel row has no entity to open; the label stays plain text.
    expect(within(rows[1]!).queryByRole("link")).toBeNull();

    const bar = screen.getByTestId("provider-strip-bar");
    expect(bar.children).toHaveLength(2);
    expect(bar.children[0]).toHaveStyle({ width: "76.62%" });
  });

  it("falls back to the amounts when the API sends no share", () => {
    render(
      <ProviderStrip
        items={[
          { key: "a", label: "A", amount: "30.00", share: null },
          { key: "b", label: "B", amount: "10.00", share: null },
        ]}
      />,
    );

    const bar = screen.getByTestId("provider-strip-bar");
    expect(bar.children[0]).toHaveStyle({ width: "75%" });
  });

  it("renders nothing for a single provider, which compares with nobody", () => {
    const { container } = render(<ProviderStrip items={[items[0]!]} />);

    expect(container).toBeEmptyDOMElement();
  });
});
