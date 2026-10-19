import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TransposedSpendTable } from "./transposed-spend-table";

describe("TransposedSpendTable", () => {
  it("uses buckets as columns and series as rows", () => {
    render(
      <TransposedSpendTable
        caption="Spend with bucket columns"
        data={{
          buckets: ["2026-09-01", "2026-09-08"],
          series: [
            {
              key: "a",
              label: "Model A",
              provider: "openai",
              values: [12, 18],
              total: 30,
            },
          ],
          other: [2, 3],
          total: [14, 21],
        }}
      />,
    );

    const table = screen.getByRole("table", { name: "Spend with bucket columns" });
    expect(within(table).getAllByRole("columnheader")).toHaveLength(3);
    expect(within(table).getByRole("row", { name: /Model A/ })).toHaveTextContent("12.00");
    expect(within(table).getByRole("row", { name: /Other/ })).toHaveTextContent("3.00");
  });
});
