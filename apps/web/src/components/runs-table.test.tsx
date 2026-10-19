import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RunsTable } from "@/components/runs-table";
import type { Run } from "@/lib/api";

function viewport(wide: boolean) {
  window.matchMedia = (query: string) =>
    ({
      matches: wide,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
}

const failed: Run = {
  id: 9,
  provider: "anthropic",
  provider_account_id: 1,
  provider_account_label: "Production",
  endpoint: "cost_report",
  status: "failed",
  window_start: "2026-08-01",
  window_end: "2026-08-31",
  started_at: "2026-08-31T12:00:00+00:00",
  finished_at: "2026-08-31T12:00:09+00:00",
  duration_seconds: 9,
  pages_fetched: 1,
  raw_results: 0,
  rows_upserted: 0,
  error: "ProviderError: the usage report timed out after three attempts",
};

const ok: Run = { ...failed, id: 10, status: "succeeded", error: null, rows_upserted: 12 };

describe("RunsTable error cell", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("folds the error under its first words and copies job, status and message", async () => {
    viewport(true);
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    render(<RunsTable runs={[failed, ok]} showProvider />);

    expect(screen.getByText("ProviderError")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Copy details" })).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Copy details" }));
    await act(async () => Promise.resolve());
    const copied = writeText.mock.calls[0]![0] as string;
    expect(copied).toContain("- Job: Costs (Anthropic run #9)");
    expect(copied).toContain("- Status: failed");
    expect(copied).toContain("the usage report timed out after three attempts");
    expect(copied).not.toContain("Route");
  });

  it("offers the same control in the narrow layout", () => {
    viewport(false);
    render(<RunsTable runs={[failed]} />);
    expect(screen.getByRole("button", { name: "Copy details" })).toBeInTheDocument();
  });
});
