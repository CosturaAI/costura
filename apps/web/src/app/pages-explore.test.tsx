/** Explore. */

import { describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import * as fx from "@/test/fixtures";
import ExplorePage from "./(app)/explore/page";
import { page, withPageDefaults, type MockedApi } from "@/test/page-harness";

vi.mock("next/navigation", () => import("@/test/page-harness").then((h) => h.navigationModule()));
vi.mock("@/lib/session-cookie", () =>
  import("@/test/page-harness").then((h) => h.sessionCookieModule()),
);
vi.mock("@/lib/view-cookie", () => import("@/test/page-harness").then((h) => h.viewCookieModule()));
vi.mock("@/lib/api", () => import("@/test/page-harness").then((h) => h.apiModule()));
vi.mock("./(app)/settings/connection-actions", () =>
  import("@/test/page-harness").then((h) =>
    h.stubs(
      "addCreditPriceAction",
      "connectAction",
      "deleteCreditPriceAction",
      "disconnectAction",
      "renameAccountAction",
      "removeAccountAction",
      "resetSetupAction",
      "syncNowAction",
    ),
  ),
);
vi.mock("./(app)/settings/member-actions", () =>
  import("@/test/page-harness").then((h) =>
    h.stubs("inviteAction", "revokeInvitationAction", "setMemberRoleAction", "removeMemberAction"),
  ),
);
vi.mock("./(app)/settings/organization-actions", () =>
  import("@/test/page-harness").then((h) =>
    h.stubs("leaveOrganizationAction", "renameOrganizationAction"),
  ),
);
vi.mock("./(app)/budgets/actions", () =>
  import("@/test/page-harness").then((h) => h.stubs("setBudgetAction", "deleteBudgetAction")),
);
vi.mock("./(app)/anomalies/actions", () =>
  import("@/test/page-harness").then((h) => h.anomalyActionsModule()),
);
vi.mock("./(app)/overview/actions", () =>
  import("@/test/page-harness").then((h) => h.stubs("dismissSetupAction")),
);
vi.mock("@/actions/view", () => import("@/test/page-harness").then((h) => h.viewActionsModule()));
vi.mock("@/actions/welcome", () =>
  import("@/test/page-harness").then((h) => h.stubs("getSetupAction", "startSyncAction")),
);

const { api } = await import("@/lib/api");
const mocked = api as unknown as MockedApi;
withPageDefaults(mocked);

describe("explore", () => {
  it("adopts a linked range through /o/{org} and keeps the rest of the query", async () => {
    await expect(
      ExplorePage({
        searchParams: Promise.resolve({
          by: "model",
          f: "workspace:is_not:sandbox",
          from: "2026-08-05",
          to: "2026-08-20",
        }),
      }),
    ).rejects.toThrow(
      "NEXT_REDIRECT /o/default?scope=anthropic&from=2026-08-05&to=2026-08-20&next=%2Fexplore%3Fby%3Dmodel%26f%3Dworkspace%253Ais_not%253Asandbox%26was_from%3D2026-08-01%26was_to%3D2026-08-31%26linked%3D2026-08-05..2026-08-20",
    );
  });

  it("names the time frame a link replaced and offers it back", async () => {
    page.view = { ...page.view!, from: "2026-08-05", to: "2026-08-20" };
    render(
      await ExplorePage({
        searchParams: Promise.resolve({
          by: "model",
          was_from: "2026-08-01",
          was_to: "2026-08-31",
          linked: "2026-08-05..2026-08-20",
        }),
      }),
    );
    expect(screen.getByRole("note")).toHaveTextContent(
      "The link set the time frame to 2026-08-05 to 2026-08-20 on every page; it was 2026-08-01 to 2026-08-31.",
    );
    expect(screen.getByRole("link", { name: "Back to 2026-08-01 to 2026-08-31" })).toHaveAttribute(
      "href",
      `/o/default?${new URLSearchParams({
        scope: "anthropic",
        from: "2026-08-01",
        to: "2026-08-31",
        next: "/explore?by=model",
      })}`,
    );
    cleanup();

    // Once the time frame changes again, the notice no longer applies.
    render(
      await ExplorePage({
        searchParams: Promise.resolve({
          by: "model",
          was_from: "2026-08-01",
          was_to: "2026-08-31",
          linked: "2026-07-01..2026-07-31",
        }),
      }),
    );
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("sums the rows past the top N as one Other line", async () => {
    mocked.queries.mockImplementation(async (_org: string, request: { measures: string[] }) => ({
      results: request.measures.map((measure) => ({
        ...fx.spendQuery,
        measure,
        other: fx.spendQuery.buckets.map((_, index) => (index === 0 ? "100.00" : "0")),
      })),
    }));
    render(await ExplorePage({ searchParams: Promise.resolve({ by: "api_key" }) }));
    const table = screen.getByRole("table", { name: /Spend by api key/ });
    const other = within(table).getByText("Other rows").closest("tr")!;
    expect(other).toHaveTextContent("100.00");
    expect(within(other).queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText(/the rest summed as Other rows/)).toBeInTheDocument();
  });

  it("uses URL range overrides and copies every Explore state field", async () => {
    page.view = { ...page.view!, from: "2026-08-05", to: "2026-08-20" };
    page.pathname = "/explore";
    page.searchParams = new URLSearchParams(
      "by=model&top=10&f=workspace%3Ais_not%3Asandbox&from=2026-08-05&to=2026-08-20&interval=week&display=delta&compare=previous_period",
    );
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    render(
      await ExplorePage({
        searchParams: Promise.resolve({
          by: "model",
          top: "10",
          f: "workspace:is_not:sandbox",
          from: "2026-08-05",
          to: "2026-08-20",
          interval: "week",
          display: "delta",
          compare: "previous_period",
        }),
      }),
    );

    expect(mocked.queries).toHaveBeenCalledWith(
      "default",
      expect.objectContaining({
        measures: expect.arrayContaining(["billed_usd"]),
        start: "2026-08-05",
        end: "2026-08-20",
        interval: "week",
        compare: "none",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Copy link" }));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(expect.stringContaining("/o/default?scope=anthropic")),
    );
    const copied = new URL(String(writeText.mock.calls[0]![0]), "http://web.test");
    expect(copied.searchParams.get("next")).toBe(
      "/explore?by=model&top=10&f=workspace%3Ais_not%3Asandbox&from=2026-08-05&to=2026-08-20&interval=week&display=delta&compare=none",
    );
  });

  it("blames the filters only when filters are set and nothing is attributed", async () => {
    page.pathname = "/explore";
    mocked.usage.mockResolvedValue({ ...fx.usage, allocated: false, cost_total: null, rows: [] });
    mocked.query.mockImplementation(async (_org: string, request: { measure: string }) => ({
      ...fx.spendQuery,
      measure: request.measure,
      source: request.measure === "billed_usd" ? "cost" : "usage",
      series: [],
      other: null,
      total: fx.spendQuery.buckets.map(() => 0),
    }));
    render(
      await ExplorePage({
        searchParams: Promise.resolve({ by: "model", f: "workspace:is_not:sandbox" }),
      }),
    );
    expect(screen.getAllByText("No spend matches these filters.").length).toBeGreaterThan(0);
    expect(screen.queryByText(/Nothing is attributed to rows/)).not.toBeInTheDocument();
  });

  it("copies a link that opens the sample organization on the sample", async () => {
    page.pathname = "/explore";
    page.organizations = [{ ...fx.organization, is_demo: true, role: null }];
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    render(await ExplorePage({ searchParams: Promise.resolve({ by: "model" }) }));
    fireEvent.click(screen.getByRole("button", { name: "Copy link" }));
    await waitFor(() => expect(writeText).toHaveBeenCalled());
    const shared = new URL(String(writeText.mock.calls[0]![0]), "http://web.test");
    expect(shared.pathname).toBe("/o/default");
    expect(shared.searchParams.get("scope")).toBe("anthropic");
    expect(shared.searchParams.get("next")).toMatch(/^\/explore\?by=model/);
  });

  it("copies the measure, axis, projection and a custom lookback into the share link", async () => {
    page.pathname = "/explore";
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    render(
      await ExplorePage({
        searchParams: Promise.resolve({
          by: "model",
          measure: "byok_usd",
          from: "2026-08-01",
          to: "2026-08-31",
          interval: "week",
          display: "daily_average_x30",
          axis: "dimension",
          projection: "linear",
          lookback: "6",
          horizon: "8",
        }),
      }),
    );

    expect(screen.getByRole("link", { name: "6 buckets" })).toHaveAttribute("aria-current", "true");
    fireEvent.click(screen.getByRole("button", { name: "Copy link" }));
    await waitFor(() => expect(writeText).toHaveBeenCalled());
    const shared = new URL(String(writeText.mock.calls[0]![0]), "http://web.test");
    const next = new URL(shared.searchParams.get("next")!, "http://web.test");
    expect(Object.fromEntries(next.searchParams)).toMatchObject({
      by: "model",
      measure: "byok_usd",
      display: "daily_average_x30",
      axis: "dimension",
      projection: "linear",
      lookback: "6",
      horizon: "8",
    });
  });

  it("falls back to the cookie when Explore URL range overrides are invalid", async () => {
    render(
      await ExplorePage({
        searchParams: Promise.resolve({
          from: "2026-02-31",
          to: "2026-02-01",
          interval: "hour",
        }),
      }),
    );

    expect(mocked.queries).toHaveBeenCalledWith(
      "default",
      expect.objectContaining({
        measures: expect.arrayContaining(["billed_usd"]),
        start: "2026-08-01",
        end: "2026-08-31",
        interval: "day",
      }),
    );
  });

  it("offers the provider account grouping only with a second account in scope", async () => {
    render(await ExplorePage({ searchParams: Promise.resolve({ by: "api_key" }) }));
    expect(screen.queryByRole("link", { name: "Provider account" })).not.toBeInTheDocument();
    cleanup();

    mocked.providers.mockResolvedValue([
      { ...fx.anthropicInfo, accounts: [fx.anthropicAccount, fx.secondAnthropicAccount] },
      fx.openRouterInfo,
    ]);
    render(await ExplorePage({ searchParams: Promise.resolve({ by: "provider_account" }) }));
    expect(mocked.usage).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "provider_account",
      25,
      {},
    );
    expect(screen.getByRole("link", { name: "Provider account" })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      /Spend by provider account, 2026-08-01 to 2026-08-31/,
    );
  });

  it("badges a row with the account name after the provider when the account has one", async () => {
    mocked.usage.mockResolvedValue({
      ...fx.usage,
      rows: [
        fx.usageRows[0],
        { ...fx.usageRows[1], provider_account_id: 4, provider_account_label: "Research" },
      ],
    });
    render(await ExplorePage({ searchParams: Promise.resolve({ by: "api_key" }) }));
    const table = screen.getByRole("table", {
      name: /Spend by api key, 2026-08-01 to 2026-08-31/,
    });
    expect(within(table).getByText("Anthropic - Research")).toBeInTheDocument();
    // The default account carries the provider's name: no badge under one provider.
    expect(within(table).queryByText("Anthropic")).not.toBeInTheDocument();
  });

  it("renders the toolbar, chart and attribution table with drill-down links", async () => {
    render(await ExplorePage({ searchParams: Promise.resolve({ by: "api_key" }) }));

    expect(mocked.usage).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "api_key",
      25,
      {},
    );
    expect(mocked.queries).toHaveBeenCalledWith(
      "default",
      expect.objectContaining({
        measures: expect.arrayContaining(["billed_usd", "tokens_total"]),
        dimensions: ["api_key"],
        start: "2026-08-01",
        end: "2026-08-31",
        interval: "day",
      }),
    );
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      /Spend by api key, 2026-08-01 to 2026-08-31/,
    );
    expect(screen.getByRole("link", { name: "Export CSV" })).toHaveAttribute(
      "href",
      "/api/exports/query?measure=billed_usd&dimensions=api_key&start=2026-08-01&end=2026-08-31&interval=day&compare=none&top=25&provider=anthropic",
    );
    fireEvent.click(screen.getByText("View options"));
    expect(screen.getByRole("link", { name: "Top 25" })).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("link", { name: "Top 50" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Top 100" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Top 200" })).toBeInTheDocument();
    expect(screen.getAllByText("40,000.00").length).toBeGreaterThan(0);
    expect(screen.getByText(/71\.3[56]%/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "batch-ingest" })).toHaveAttribute(
      "href",
      "/keys/apikey_redacted_2",
    );
    // Header click re-sorts: a second click on USD flips to ascending and the smaller key leads.
    const table = screen.getByRole("table", {
      name: /Spend by api key, 2026-08-01 to 2026-08-31/,
    });
    expect(
      within(within(table).getAllByRole("row")[1]!).getByText("batch-ingest"),
    ).toBeInTheDocument();
    fireEvent.click(within(table).getByRole("button", { name: /^USD/ }));
    fireEvent.click(within(table).getByRole("button", { name: /^USD/ }));
    expect(within(within(table).getAllByRole("row")[1]!).getByText("retired")).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: /^USD/ })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );
    expect(screen.getByText("missing")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show token counters" })).toBeInTheDocument();
  });

  it("passes filters through and shows them as chips", async () => {
    render(
      await ExplorePage({
        searchParams: Promise.resolve({
          by: "model",
          f: "workspace:is:wrkspc_redacted_a",
          top: "all",
        }),
      }),
    );
    expect(mocked.usage).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "model",
      200,
      {
        workspace: { op: "is", values: ["wrkspc_redacted_a"] },
      },
    );
    // The chip label comes from a one-row usage lookup in the filter's own dimension.
    expect(mocked.usage).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "workspace",
      1,
      {
        workspace: "wrkspc_redacted_a",
      },
    );
    expect(screen.getByLabelText("Active filters")).toHaveTextContent("Workspace is");
    expect(screen.getByRole("link", { name: "clear all" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Export CSV" })).toHaveAttribute(
      "href",
      "/api/exports/query?measure=billed_usd&dimensions=model&start=2026-08-01&end=2026-08-31&interval=day&compare=none&top=200&f=workspace%3Ais%3Awrkspc_redacted_a&provider=anthropic",
    );
  });

  it("passes operator clauses through chips, queries and CSV export", async () => {
    page.pathname = "/explore";
    page.searchParams = new URLSearchParams(
      "by=model&f=model%3Ais_not%3Agpt-4o&f=workspace%3Aexists%3A",
    );
    mocked.usage.mockImplementation(
      (_org: string, _provider: string, _month: string, _by: string, top?: number) =>
        Promise.resolve(top === 1 ? { ...fx.usage, rows: [] } : fx.usage),
    );
    render(
      await ExplorePage({
        searchParams: Promise.resolve({
          by: "model",
          f: ["model:is_not:gpt-4o", "workspace:exists:"],
        }),
      }),
    );

    const filters = {
      model: { op: "is_not", values: ["gpt-4o"] },
      workspace: { op: "exists", values: [] },
    };
    expect(mocked.usage).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "model",
      25,
      filters,
    );
    expect(mocked.queries).toHaveBeenCalledWith(
      "default",
      expect.objectContaining({
        measures: expect.arrayContaining(["billed_usd"]),
        filters: { ...filters, provider: "anthropic" },
      }),
    );
    const chips = screen.getByLabelText("Active filters");
    expect(chips).toHaveTextContent("Model is not gpt-4o");
    expect(chips).toHaveTextContent("Workspace exists");
    expect(within(chips).getByTitle("Remove filter Model")).toHaveAttribute(
      "href",
      "/explore?by=model&f=workspace%3Aexists%3A",
    );
    expect(within(chips).getByRole("link", { name: "clear all" })).toHaveAttribute(
      "href",
      "/explore?by=model",
    );
    expect(screen.getByRole("link", { name: "Export CSV" }).getAttribute("href")).toContain(
      "f=model%3Ais_not%3Agpt-4o",
    );
    expect(screen.getByRole("link", { name: "Export CSV" }).getAttribute("href")).toContain(
      "f=workspace%3Aexists%3A",
    );
  });

  it("adds a sortable BYOK column only when a row carries a BYOK amount", async () => {
    render(await ExplorePage({ searchParams: Promise.resolve({ by: "api_key" }) }));
    expect(screen.queryByRole("columnheader", { name: /BYOK/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/on your own provider keys/)).not.toBeInTheDocument();
    cleanup();

    mocked.usage.mockResolvedValue(fx.usageWithByok);
    page.view = { ...page.view!, scope: "openrouter" };
    render(await ExplorePage({ searchParams: Promise.resolve({ by: "api_key" }) }));
    const table = screen.getByRole("table", {
      name: /Spend by api key, 2026-08-01 to 2026-08-31/,
    });
    const header = within(table).getByRole("columnheader", { name: /BYOK/ });
    expect(header).toHaveAttribute("aria-sort", "none");
    expect(within(table).getByText("5,400.50")).toBeInTheDocument();
    // A key with an OpenRouter figure of zero prints 0.00, not a blank.
    expect(within(table).getByText("0.00")).toBeInTheDocument();
    expect(
      screen.getByText(
        "BYOK: Routed through OpenRouter on your own provider keys; billed by the providers.",
      ),
    ).toBeInTheDocument();
    // Sorting by BYOK puts the BYOK-heavy key first.
    fireEvent.click(within(table).getByRole("button", { name: /BYOK/ }));
    expect(
      within(within(table).getAllByRole("row")[1]!).getByText("router-byok"),
    ).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: /BYOK/ })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
  });

  it("falls back to api_key for an unknown dimension", async () => {
    render(await ExplorePage({ searchParams: Promise.resolve({ by: "colour" }) }));
    expect(mocked.usage).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "api_key",
      25,
      {},
    );
  });

  it("links to Sync now and explains an empty spend result", async () => {
    mocked.usage.mockResolvedValue({ ...fx.usage, allocated: false, cost_total: null, rows: [] });
    mocked.query.mockImplementation(async (_org: string, request: { measure: string }) => ({
      ...fx.spendQuery,
      measure: request.measure,
      source: request.measure === "billed_usd" ? "cost" : "usage",
      series: [],
      other: null,
      total: fx.spendQuery.buckets.map(() => 0),
    }));
    render(await ExplorePage({ searchParams: fx.noSearch }));
    expect(screen.getByText(/Nothing is attributed to rows in this range yet/)).toBeInTheDocument();
    expect(screen.queryByText("No spend matches these filters.")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sync now from settings" })).toHaveAttribute(
      "href",
      "/settings/sync",
    );
    expect(
      within(screen.getByRole("group", { name: "Group by" })).queryByRole("link", {
        name: "Provider",
      }),
    ).not.toBeInTheDocument();
  });

  describe("under all providers", () => {
    it("offers the provider grouping and filter and badges each row", async () => {
      page.view = { org: "default", month: "2026-08", scope: "all" };
      page.pathname = "/explore";
      mocked.usage.mockResolvedValue(fx.usageAll);
      render(
        await ExplorePage({
          searchParams: Promise.resolve({ by: "api_key" }),
        }),
      );

      expect(mocked.usage).toHaveBeenCalledWith(
        "default",
        "all",
        { from: "2026-08-01", to: "2026-08-31" },
        "api_key",
        25,
        {},
      );
      const groups = screen.getByRole("group", { name: "Group by" });
      expect(within(groups).getByRole("link", { name: "Provider" })).toHaveAttribute(
        "href",
        "/explore?by=provider",
      );
      const table = screen.getByRole("table", {
        name: /Spend by api key, 2026-08-01 to 2026-08-31/,
      });
      expect(within(table).getAllByText("Anthropic")).toHaveLength(2);
      expect(within(table).getByText("OpenRouter")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "router-prod" })).toHaveAttribute(
        "href",
        "/keys/orkey_hash_1",
      );
      expect(screen.getByRole("link", { name: "batch-ingest" })).toHaveAttribute(
        "href",
        "/keys/apikey_redacted_2",
      );
      // Reasoning tokens appear as a counter once a row carries them.
      fireEvent.click(screen.getByRole("button", { name: "Show token counters" }));
      expect(within(table).getByRole("columnheader", { name: /^reasoning/ })).toBeInTheDocument();
      expect(
        within(table).queryByRole("columnheader", { name: /^cache 5m/ }),
      ).not.toBeInTheDocument();
    });

    it("labels the provider filter chip from the registry label", async () => {
      page.view = { org: "default", month: "2026-08", scope: "all" };
      page.pathname = "/explore";
      mocked.usage.mockImplementation(
        (
          _org: string,
          _provider: string,
          _month: string,
          by: string,
          _top?: number,
          filters: { provider?: string } = {},
        ) => {
          if (by !== "provider") return Promise.resolve(fx.usageAll);
          const rows = filters.provider
            ? fx.usageByProvider.rows.filter((row) => row.key === filters.provider)
            : fx.usageByProvider.rows;
          return Promise.resolve({ ...fx.usageByProvider, rows });
        },
      );
      render(
        await ExplorePage({
          searchParams: Promise.resolve({ by: "api_key", f: "provider:is:openrouter" }),
        }),
      );
      expect(mocked.usage).toHaveBeenCalledWith(
        "default",
        "all",
        { from: "2026-08-01", to: "2026-08-31" },
        "api_key",
        25,
        {
          provider: { op: "is", values: ["openrouter"] },
        },
      );
      expect(mocked.usage).toHaveBeenCalledWith(
        "default",
        "all",
        { from: "2026-08-01", to: "2026-08-31" },
        "provider",
        1,
        {
          provider: "openrouter",
        },
      );
      const chips = screen.getByLabelText("Active filters");
      expect(chips).toHaveTextContent("Provider is");
      expect(chips).toHaveTextContent("OpenRouter");
    });

    it("links to Sync now when the aggregated month has no usage", async () => {
      mocked.usage.mockResolvedValue({ ...fx.usage, rows: [] });
      mocked.query.mockImplementation(async (_org: string, request: { measure: string }) => ({
        ...fx.spendQuery,
        measure: request.measure,
        source: request.measure === "billed_usd" ? "cost" : "usage",
        series: [],
        other: null,
        total: fx.spendQuery.buckets.map(() => 0),
      }));
      render(await ExplorePage({ searchParams: fx.noSearch }));
      expect(screen.getByText("No usage stored for 2026-08-01 to 2026-08-31.")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Sync now from settings" })).toHaveAttribute(
        "href",
        "/settings/sync",
      );
    });
  });
});
