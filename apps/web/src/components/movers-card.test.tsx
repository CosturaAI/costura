import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import * as fx from "@/test/fixtures";

import { MoversCard } from "./movers-card";

function side(heading: string): HTMLElement {
  return screen.getByText(heading).parentElement as HTMLElement;
}

describe("MoversCard", () => {
  it("splits the ranking by direction and marks the keys that appeared or stopped", () => {
    render(<MoversCard movers={fx.movers} period={{ from: "2026-08-01", to: "2026-08-31" }} />);

    expect(screen.getByRole("heading", { name: "What changed" })).toBeInTheDocument();
    expect(screen.getByText("Each API key's spend against July 2026.")).toBeInTheDocument();

    const up = side("Spending more");
    expect(within(up).getByRole("link", { name: "batch-ingest" })).toHaveAttribute(
      "href",
      "/keys/apikey_redacted_2",
    );
    expect(up).toHaveTextContent("+28,000.00");
    expect(up).toHaveTextContent("233.33% against 12,000.00");
    expect(within(up).getByText("new")).toBeInTheDocument();

    const down = side("Spending less");
    expect(down).toHaveTextContent("-9,000.00");
    expect(within(down).getByText("stopped")).toBeInTheDocument();
    expect(within(down).queryByText("new")).toBeNull();
  });

  it("names the missing attribution instead of ranking on one month", () => {
    render(<MoversCard movers={fx.noMovers} period={{ from: "2026-08-01", to: "2026-08-31" }} />);

    expect(screen.getByText(/July 2026 or August 2026 has no attribution yet/)).toBeInTheDocument();
    expect(screen.queryByText("Spending more")).toBeNull();
  });

  it("says so when no row moved", () => {
    render(
      <MoversCard
        movers={{ ...fx.movers, rows: [] }}
        period={{ from: "2026-08-01", to: "2026-08-31" }}
      />,
    );

    expect(screen.getByText("No API key changed its spend against July 2026.")).toBeInTheDocument();
  });
});
