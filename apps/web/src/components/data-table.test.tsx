import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DataTable, type Column } from "./data-table";

type Row = { id: string; name: string; amount: number | null; created: string | null };

const columns: Column<Row>[] = [
  { id: "name", header: "name", render: (r) => r.name, sortValue: (r) => r.name },
  {
    id: "amount",
    header: "USD",
    align: "right",
    render: (r) => (r.amount === null ? "-" : r.amount.toFixed(2)),
    sortValue: (r) => r.amount,
  },
  {
    id: "created",
    header: "created",
    render: (r) => r.created ?? "-",
    sortValue: (r) => r.created,
  },
];

const rows: Row[] = [
  { id: "b", name: "beta", amount: 20, created: "2026-02-01" },
  { id: "a", name: "alpha", amount: null, created: null },
  { id: "c", name: "gamma", amount: 5, created: "2026-01-15" },
];

function names(): string[] {
  return screen
    .getAllByRole("row")
    .slice(1)
    .map((row) => within(row).getAllByRole("cell")[0]!.textContent ?? "");
}

describe("DataTable", () => {
  it("keeps the given order until a header is clicked, then sorts and flips", () => {
    render(<DataTable rows={rows} columns={columns} rowKey={(r) => r.id} caption="rows" />);
    expect(names()).toEqual(["beta", "alpha", "gamma"]);

    const usd = screen.getByRole("button", { name: /^USD/ });
    const usdHead = screen.getByRole("columnheader", { name: /^USD/ });
    expect(usdHead).toHaveAttribute("aria-sort", "none");
    fireEvent.click(usd);
    // A numeric column opens descending; empty values stay last.
    expect(names()).toEqual(["beta", "gamma", "alpha"]);
    expect(usdHead).toHaveAttribute("aria-sort", "descending");

    fireEvent.click(usd);
    expect(names()).toEqual(["gamma", "beta", "alpha"]);
    expect(usdHead).toHaveAttribute("aria-sort", "ascending");

    fireEvent.click(screen.getByRole("button", { name: /^name/ }));
    expect(names()).toEqual(["alpha", "beta", "gamma"]);
    fireEvent.click(screen.getByRole("button", { name: /^created/ }));
    expect(names()).toEqual(["gamma", "beta", "alpha"]);
  });

  it("starts from the default sort when one is given", () => {
    render(
      <DataTable
        rows={rows}
        columns={columns}
        rowKey={(r) => r.id}
        caption="rows"
        defaultSort={{ id: "amount", direction: "desc" }}
      />,
    );
    expect(names()).toEqual(["beta", "gamma", "alpha"]);
  });

  it("shows one page and loads more on request", () => {
    const many = Array.from({ length: 250 }, (_, i) => ({
      id: String(i),
      name: `row ${i}`,
      amount: i,
      created: null,
    }));
    render(
      <DataTable
        rows={many}
        columns={columns}
        rowKey={(r) => r.id}
        caption="rows"
        pageSize={100}
      />,
    );
    expect(screen.getAllByRole("row")).toHaveLength(101);
    expect(screen.getByText("100 of 250 rows")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Load 100 more" }));
    expect(screen.getAllByRole("row")).toHaveLength(201);
    fireEvent.click(screen.getByRole("button", { name: "Load 50 more" }));
    expect(screen.getAllByRole("row")).toHaveLength(251);
    expect(screen.queryByRole("button", { name: /Load \d+ more/ })).not.toBeInTheDocument();
  });

  it("prints the empty message instead of an empty body", () => {
    render(
      <DataTable
        rows={[]}
        columns={columns}
        rowKey={(r) => r.id}
        caption="rows"
        emptyMessage="Nothing here"
      />,
    );
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
  });
});
