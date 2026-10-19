import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import * as fx from "@/test/fixtures";

import { NeedsAPerson } from "./needs-a-person";

describe("NeedsAPerson", () => {
  it("lists the three signals with the most money and links each to where it is fixed", () => {
    render(<NeedsAPerson signals={fx.signals} />);
    const list = screen.getByRole("list", { name: "Needs a person" });
    const rows = within(list).getAllByRole("listitem");

    expect(rows).toHaveLength(3);
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringContaining("prod-backend (apikey_1)"),
      expect.stringContaining("gateway (or_gateway)"),
      expect.stringContaining("organization total"),
    ]);
    expect(within(rows[0]!).getByRole("link")).toHaveAttribute("href", "/anomalies/8");
    expect(within(rows[1]!).getByRole("link")).toHaveAttribute("href", "/keys/or_gateway");
    expect(within(rows[2]!).getByRole("link")).toHaveAttribute("href", "/budgets");
    expect(within(rows[1]!).getByText("no owner")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("no limit")).toBeInTheDocument();
    expect(screen.getByText(/^4 open, most money first/)).toBeInTheDocument();
    expect(screen.queryByText("fresh (key_new)")).not.toBeInTheDocument();
  });

  it("says when nothing needs a person and when the read failed", () => {
    const { rerender } = render(<NeedsAPerson signals={fx.noSignals} />);
    expect(screen.getByText("Nothing needs a person.")).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();

    rerender(<NeedsAPerson signals={null} />);
    expect(screen.getByText("Could not be loaded; reload to retry.")).toBeInTheDocument();
  });
});
