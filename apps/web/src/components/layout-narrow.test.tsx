import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DataTable } from "@/components/data-table";
import { StatePanel } from "@/components/empty-state";
import { QueryChips } from "@/components/query-chips";
import { RunsTable } from "@/components/runs-table";
import { EntitySkeleton, FilterBarSkeleton, TableSkeleton } from "@/components/skeletons";
import type { Run } from "@/lib/api";

vi.mock("next/navigation", () => ({
  usePathname: () => "/explore",
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

function narrow() {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
}

const run: Run = {
  id: 7,
  provider: "anthropic",
  provider_account_id: 1,
  provider_account_label: "Production",
  endpoint: "cost_report",
  status: "succeeded",
  window_start: "2026-08-01",
  window_end: "2026-08-31",
  started_at: "2026-08-31T12:00:00+00:00",
  finished_at: "2026-08-31T12:01:00+00:00",
  duration_seconds: 60,
  pages_fetched: 1,
  raw_results: 2,
  rows_upserted: 2,
  error: null,
};

describe("narrow layout", () => {
  beforeEach(() => {
    narrow();
  });

  it("stacks table rows as cards and chips as a select", () => {
    render(
      <DataTable
        caption="Keys"
        rows={[{ id: "k", name: "Platform key" }]}
        rowKey={(row) => row.id}
        columns={[
          { id: "name", header: "name", render: (row) => row.name },
          { id: "extra", header: "extra", priority: "hide", render: () => "hidden" },
        ]}
      />,
    );
    expect(screen.getByText("Platform key")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText("hidden")).not.toBeInTheDocument();

    render(
      <QueryChips
        name="display"
        value="total"
        label="Display"
        options={[
          { value: "total", label: "Total" },
          { value: "delta", label: "Delta" },
        ]}
      />,
    );
    expect(screen.getByRole("combobox", { name: "Display" })).toBeInTheDocument();
  });

  it("shows the name and at most three fields on a card", () => {
    render(
      <DataTable
        caption="Keys"
        rows={[{ id: "k" }]}
        rowKey={(row) => row.id}
        columns={[
          { id: "name", header: "name", priority: "primary", render: () => "Platform key" },
          { id: "a", header: "one", priority: "summary", render: () => "1" },
          { id: "b", header: "two", priority: "summary", render: () => "2" },
          { id: "c", header: "three", priority: "summary", render: () => "3" },
          { id: "d", header: "four", priority: "summary", render: () => "4" },
        ]}
      />,
    );
    const card = screen.getByText("Platform key").closest("article")!;
    const face = card.querySelector("dl")!;
    expect(within(face).getByText("one")).toBeInTheDocument();
    expect(within(face).getByText("three")).toBeInTheDocument();
    expect(within(face).queryByText("four")).not.toBeInTheDocument();
    expect(within(card).getByText("More on this row")).toBeInTheDocument();
  });

  it("stacks sync runs and renders the shared state and skeleton panels", () => {
    render(<RunsTable runs={[run]} />);
    expect(screen.getByText("Costs")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    const card = screen.getByText("Costs").closest("article")!;
    expect(within(card).getByText("rows")).toBeInTheDocument();
    expect(within(card).getByText("Telemetry")).toBeInTheDocument();
    expect(card.querySelector("details")?.textContent).toContain("window");

    render(<StatePanel tone="warning" title="Partial" message="Some rows are missing." />);
    expect(screen.getByText("Partial")).toBeInTheDocument();
    render(<FilterBarSkeleton />);
    render(<TableSkeleton rows={2} />);
    render(<EntitySkeleton />);
    expect(screen.getAllByLabelText("Loading").length).toBeGreaterThan(0);
  });
});
