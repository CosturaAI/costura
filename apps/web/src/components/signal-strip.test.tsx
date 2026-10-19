import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

import { SignalStrip } from "./signal-strip";

afterEach(() => {
  cleanup();
});

describe("SignalStrip", () => {
  it("renders nothing without signals", () => {
    const { container } = render(<SignalStrip items={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("lists each signal with its value, optional detail and link", () => {
    render(
      <SignalStrip
        items={[
          {
            label: "Open anomalies",
            value: "3",
            meta: "1 critical",
            href: "/anomalies",
            linkLabel: "Review",
          },
          { label: "Budgets at risk", value: "1", href: "/budgets", linkLabel: "Open budgets" },
        ]}
      />,
    );

    const items = within(screen.getByRole("list", { name: "Signals" })).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(within(items[0]!).getByText("1 critical")).toBeInTheDocument();
    expect(within(items[0]!).getByRole("link", { name: "Review" })).toHaveAttribute(
      "href",
      "/anomalies",
    );
    expect(within(items[1]!).getByText("1")).toBeInTheDocument();
    expect(within(items[1]!).queryByText("1 critical")).not.toBeInTheDocument();
  });
});
