import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DailySpendChart } from "@/components/charts/daily-spend-chart";
import { RunsTable } from "@/components/runs-table";
import { endpointLabel } from "@/lib/run-labels";
import { runTone } from "@/components/status-badge";
import type { DailySeries, Run, RunStatus } from "@/lib/api";

const series: DailySeries = {
  month: "2026-09",
  dimension: "model",
  source: "allocated",
  days: ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"],
  series: [
    {
      key: "model-1",
      label: "Model one (model-1)",
      provider: "openrouter",
      values: ["10.00", "20.00", "0.00", "0.00"],
      total: "30.00",
    },
  ],
  other: null,
  total: ["10.00", "20.00", "0.00", "0.00"],
  month_total: "30.00",
};

const run: Run = {
  id: 1,
  provider: "openrouter",
  provider_account_id: 2,
  provider_account_label: "OpenRouter",
  endpoint: "analytics_cost",
  status: "succeeded",
  window_start: "2026-09-01T00:00:00Z",
  window_end: "2026-10-01T00:00:00Z",
  started_at: "2026-09-15T12:00:00Z",
  finished_at: "2026-09-15T12:00:01Z",
  duration_seconds: 1,
  pages_fetched: 1,
  raw_results: 2,
  rows_upserted: 3,
  error: null,
};

describe("run presentation contracts", () => {
  it("uses the same dense column definition for headers and cells", () => {
    render(<RunsTable runs={[run]} dense showProvider />);
    const table = screen.getByRole("table");
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent),
    ).toEqual(["job", "provider", "status", "started", "error"]);
    expect(within(table).getAllByRole("cell")).toHaveLength(5);
  });

  it("keeps window, duration, pages and results under Telemetry on the full table", () => {
    render(<RunsTable runs={[run]} />);
    const headers = within(screen.getByRole("table"))
      .getAllByRole("columnheader")
      .map((cell) => cell.textContent);
    expect(headers).toEqual(["job", "status", "started", "rows", "error", "Telemetry"]);
    expect(screen.queryByRole("columnheader", { name: "window" })).not.toBeInTheDocument();
    expect(screen.getAllByText("Telemetry")).toHaveLength(2);
  });

  it("maps every endpoint and run status used by both providers and the scheduler", () => {
    expect(endpointLabel("analytics_cost")).toBe("Costs and usage");
    expect(endpointLabel("analytics_total")).toBe("Costs (provider total)");
    expect(endpointLabel("keys")).toBe("Inventory: API keys");
    expect(endpointLabel("organization_members")).toBe("Inventory: users");
    expect(endpointLabel("costs")).toBe("Costs");
    expect(endpointLabel("costs_by_key")).toBe("Costs by API key (provider total)");
    expect(endpointLabel("usage_completions")).toBe("Usage: completions");
    expect(endpointLabel("project_users")).toBe("Inventory: project members");

    const expected: Record<RunStatus, ReturnType<typeof runTone>> = {
      queued: "info",
      running: "info",
      skipped: "neutral",
      failed: "critical",
      succeeded: "success",
    };
    for (const [status, tone] of Object.entries(expected) as [
      RunStatus,
      (typeof expected)[RunStatus],
    ][]) {
      expect(runTone(status)).toBe(tone);
    }
  });
});

describe("daily spend chart accessibility", () => {
  it("exposes projection bands and anomalies in daily and cumulative tables", () => {
    render(
      <DailySpendChart
        data={series}
        projection={{
          fromDay: "2026-09-02",
          days: [
            { day: "2026-09-03", expected: "5.00", low: "4.00", high: "7.00" },
            { day: "2026-09-04", expected: "6.00", low: "3.00", high: "8.00" },
          ],
        }}
        markers={[{ day: "2026-09-02", label: "Model spend above baseline", impact: "8.00" }]}
      />,
    );

    const daily = screen.getByRole("table", { name: "Spend by day in USD, daily" });
    expect(
      within(daily)
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent),
    ).toEqual([
      "day",
      "total",
      "Model one",
      "projected expected",
      "projected low",
      "projected high",
      "markers",
    ]);
    const dailyRows = within(daily).getAllByRole("row");
    expect(dailyRows[2]).toHaveTextContent("Model spend above baseline");
    expect(dailyRows[3]).toHaveTextContent("5.004.007.00");

    fireEvent.click(screen.getByRole("button", { name: "cumulative" }));
    const cumulative = screen.getByRole("table", {
      name: "Spend by day in USD, cumulative",
    });
    const cumulativeRows = within(cumulative).getAllByRole("row");
    expect(cumulativeRows[3]).toHaveTextContent("35.0034.0037.00");
    expect(cumulativeRows[4]).toHaveTextContent("41.0037.0045.00");
  });
});
