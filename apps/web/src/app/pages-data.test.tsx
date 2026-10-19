/** Reconcile, runs and inventory pages. */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import * as fx from "@/test/fixtures";
import InventoryPage from "./(app)/inventory/page";
import ReconcilePage from "./(app)/reconcile/page";
import RunsPage from "./(app)/runs/page";
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

describe("reconcile", () => {
  it("passes all three checks when the provider total matches", async () => {
    render(
      await ReconcilePage({
        searchParams: Promise.resolve({ by: "day" }),
      }),
    );

    expect(mocked.reconcile).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "day",
    );
    expect(screen.getByText("Does August 2026 add up?")).toBeInTheDocument();
    expect(screen.getAllByText("pass")).toHaveLength(3);
    expect(screen.getByText("Costura total matches the provider total")).toBeInTheDocument();
    expect(screen.getByText("Stored rows match the provider report")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getByText("2026-08-01")).toBeInTheDocument();
  });

  it("shows OpenAI activity-family coverage as a fifth check", async () => {
    page.view = { ...page.view!, scope: "openai" };
    mocked.reconcile.mockResolvedValue({
      ...fx.reconcile,
      key_check_supported: true,
      activity_coverage: {
        covered_families: [
          "images",
          "embeddings",
          "moderations",
          "audio_speeches",
          "audio_transcriptions",
          "vector_stores",
          "code_interpreter_sessions",
        ],
        missing_families: [],
        complete: true,
      },
    });

    render(await ReconcilePage({ searchParams: fx.noSearch }));

    expect(screen.getByText(/Six checks/)).toBeInTheDocument();
    expect(screen.getByText("Activity families cover the period")).toBeInTheDocument();
    expect(screen.getByText(/All 7 OpenAI non-completions families/)).toBeInTheDocument();
  });

  it("narrows the checks to one account through ?account= when the provider has several", async () => {
    const accounts = [
      { id: 1, provider: "anthropic", label: "Anthropic" },
      { id: 4, provider: "anthropic", label: "Research" },
    ];
    page.pathname = "/reconcile";
    mocked.reconcile.mockResolvedValue({ ...fx.reconcile, accounts });
    render(await ReconcilePage({ searchParams: fx.noSearch }));
    expect(mocked.reconcile).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "workspace",
    );
    const group = screen.getByRole("group", { name: "Account" });
    expect(
      within(group)
        .getAllByRole("link")
        .map((l) => l.textContent),
    ).toEqual(["All accounts", "Anthropic", "Research"]);
    expect(within(group).getByRole("link", { name: "Research" })).toHaveAttribute(
      "href",
      "/reconcile?account=4",
    );
    expect(screen.getByText(/every account of the provider added up/)).toBeInTheDocument();
    cleanup();

    mocked.reconcile.mockResolvedValue({
      ...fx.reconcile,
      accounts,
      account_id: 4,
      account_label: "Research",
    });
    render(await ReconcilePage({ searchParams: Promise.resolve({ account: "4" }) }));
    expect(mocked.reconcile).toHaveBeenLastCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "workspace",
      4,
    );
    expect(
      within(screen.getByRole("group", { name: "Account" })).getByRole("link", {
        name: "Research",
      }),
    ).toHaveAttribute("aria-current", "true");
    expect(screen.getByText(/for the Research account/)).toBeInTheDocument();
  });

  it("prints workspace names without their ids in the breakdown", async () => {
    mocked.reconcile.mockResolvedValue({
      ...fx.reconcile,
      by: "workspace",
      breakdown: [
        { key: "wrkspc_redacted_a", label: "Platform (wrkspc_redacted_a)", amount: "56056.12" },
      ],
    });
    render(await ReconcilePage({ searchParams: fx.noSearch }));
    const table = screen.getByRole("table", { name: /Cost report by workspace/i });
    expect(within(table).getByText("Platform")).toBeInTheDocument();
    expect(within(table).queryByText(/wrkspc_redacted_a\)/)).not.toBeInTheDocument();
  });

  it("fails the first check when the provider total differs", async () => {
    mocked.reconcile.mockResolvedValue({
      ...fx.reconcile,
      provider_check: {
        run_id: 10,
        provider_total: "56000.00",
        delta: "56.12",
        ok: false,
        label: "Provider-reported usage",
        derived_seat_total: "0.00",
      },
    });
    render(await ReconcilePage({ searchParams: fx.noSearch }));

    expect(screen.getByText("fail")).toBeInTheDocument();
    expect(screen.getByText(/Provider-reported usage reports/)).toBeInTheDocument();
    expect(screen.getByText("56,000.00")).toBeInTheDocument();
  });

  it("compares a calendar month with its stored invoice and offers to change it", async () => {
    mocked.reconcile.mockResolvedValue({
      ...fx.reconcile,
      reported_source: "invoice",
      reported_total: "56100.00",
      delta: "-43.88",
      delta_percent: "-0.08",
      matches: false,
      accounts: [{ id: 3, provider: "anthropic", label: "Anthropic" }],
    });
    mocked.invoices.mockResolvedValue({
      month: "2026-08",
      items: [
        {
          provider: "anthropic",
          account_id: 3,
          account_label: "Anthropic",
          month: "2026-08",
          amount: "56100.00",
          currency: "USD",
          note: "includes VAT",
          entered_by: "owner@acme.com",
          updated_at: "2026-09-03T00:00:00Z",
        },
      ],
    });
    render(await ReconcilePage({ searchParams: fx.noSearch }));
    expect(mocked.invoices).toHaveBeenCalledWith("default", "anthropic", "2026-08");
    expect(screen.getByText("Costura total matches the invoice")).toBeInTheDocument();
    expect(screen.getByText(/The 2026-08 invoice says/)).toBeInTheDocument();
    expect(screen.getByText(/Note: includes VAT/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change the invoice total" })).toBeInTheDocument();
    expect(screen.getAllByText("fail")).toHaveLength(1);
  });

  it("marks the checks pending without a control total or runs", async () => {
    mocked.reconcile.mockResolvedValue({
      ...fx.reconcile,
      provider_check: null,
      raw_check: null,
      allocation: null,
    });
    render(await ReconcilePage({ searchParams: fx.noSearch }));

    expect(mocked.reconcile).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "workspace",
    );
    expect(screen.getAllByText("pending")).toHaveLength(4);
    expect(screen.queryByText("pass")).not.toBeInTheDocument();
    expect(
      screen.getByText(/No provider total for these days yet; it arrives with the next import/),
    ).toBeInTheDocument();
    expect(screen.getByText("No import covers the whole period yet.")).toBeInTheDocument();
    expect(
      screen.getByText("No attribution for this period yet; it runs at the end of each import."),
    ).toBeInTheDocument();
  });

  it("says what the OpenRouter provider total covers, and nothing of the kind for Anthropic", async () => {
    render(await ReconcilePage({ searchParams: fx.noSearch }));
    expect(screen.queryByText(/billed to credits/)).not.toBeInTheDocument();
    cleanup();

    page.view = { ...page.view!, scope: "openrouter" };
    render(await ReconcilePage({ searchParams: fx.noSearch }));
    expect(
      screen.getByText(
        /The provider total is what OpenRouter billed to credits; traffic on your own provider keys \(BYOK\) is not included\./,
      ),
    ).toBeInTheDocument();
  });

  it("adds the per-key check for providers that publish per-key money", async () => {
    page.view = { ...page.view!, scope: "openai" };
    mocked.reconcile.mockResolvedValue({
      ...fx.reconcile,
      key_check_supported: true,
      key_check: null,
    });
    render(await ReconcilePage({ searchParams: fx.noSearch }));
    expect(screen.getByText(/Five checks/)).toBeInTheDocument();
    expect(screen.getByText(/attributed to the key OpenAI reports it under/)).toBeInTheDocument();
    expect(screen.getByText("Provider per-key totals match the attribution")).toBeInTheDocument();
    expect(screen.getAllByText("pending")).toHaveLength(2);
    expect(
      screen.getByText(/No per-key total and attribution cover this period yet/),
    ).toBeInTheDocument();
    cleanup();

    mocked.reconcile.mockResolvedValue({
      ...fx.reconcile,
      key_check_supported: true,
      key_check: {
        run_id: 12,
        keys_compared: 3,
        keys_off: [
          {
            api_key_id: "key_b1",
            label: "batch-runner (key_b1)",
            provider_amount: "13.50",
            allocated_amount: "12.50",
            delta: "-1.00",
          },
        ],
        provider_total: "20.50",
        allocated_total: "19.50",
        ok: false,
      },
    });
    render(await ReconcilePage({ searchParams: fx.noSearch }));
    expect(screen.getByText("fail")).toBeInTheDocument();
    expect(
      screen.getByText(/1 key outside one cent: batch-runner \(key_b1\) -1\.00\./),
    ).toBeInTheDocument();
  });

  it("links to Sync now when the month has no cost lines", async () => {
    mocked.reconcile.mockResolvedValue({ ...fx.reconcile, costura_total: "0.00" });
    render(await ReconcilePage({ searchParams: fx.noSearch }));
    expect(screen.getByText("No cost lines stored in August 2026.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sync now from settings" })).toHaveAttribute(
      "href",
      "/settings/sync",
    );
  });

  describe("under all providers", () => {
    beforeEach(() => {
      page.view = { ...page.view!, scope: "all" };
    });

    it("shows one card per connected provider linking to its own checks", async () => {
      mocked.summary.mockImplementation((_org: string, provider: string) =>
        Promise.resolve(
          provider === "openrouter"
            ? { ...fx.summary, total: "1200.00", provider_total: null, provider_matches: null }
            : fx.summary,
        ),
      );
      render(await ReconcilePage({ searchParams: fx.noSearch }));

      // Control totals are per provider: the aggregated route is never asked to reconcile.
      expect(mocked.reconcile).not.toHaveBeenCalled();
      expect(mocked.summary).toHaveBeenCalledWith("default", "anthropic", {
        from: "2026-08-01",
        to: "2026-08-31",
      });
      expect(mocked.summary).toHaveBeenCalledWith("default", "openrouter", {
        from: "2026-08-01",
        to: "2026-08-31",
      });
      const cards = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
      expect(cards[0]).toMatch(/^Anthropic/);
      expect(cards[1]).toMatch(/^OpenRouter/);
      expect(screen.getByText("pass")).toBeInTheDocument();
      expect(screen.getByText("pending")).toBeInTheDocument();
      expect(screen.getByText("1,200.00 USD")).toBeInTheDocument();
      expect(screen.getByText("not synced")).toBeInTheDocument();
      const links = screen.getAllByRole("link", { name: "See the checks" });
      // Each card's link narrows the view to its provider before opening the checks.
      expect(links[0]).toHaveAttribute(
        "href",
        "/o/default?scope=anthropic&from=2026-08-01&to=2026-08-31&next=%2Freconcile",
      );
      expect(links[1]).toHaveAttribute(
        "href",
        "/o/default?scope=openrouter&from=2026-08-01&to=2026-08-31&next=%2Freconcile",
      );
      // Only the OpenRouter card explains what its provider total leaves out.
      expect(screen.getAllByText(/billed to credits/)).toHaveLength(1);
    });

    it("says so when no provider is connected", async () => {
      mocked.providers.mockResolvedValue(fx.providersNoneConnected);
      mocked.months.mockResolvedValue({ months: [] });
      render(await ReconcilePage({ searchParams: fx.noSearch }));
      expect(screen.getByText(/nothing to reconcile/)).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Connect a provider" })).toHaveAttribute(
        "href",
        "/welcome",
      );
      expect(screen.queryByRole("article")).not.toBeInTheDocument();
    });

    it("keeps disconnected providers with selected-month history and marks them", async () => {
      mocked.providers.mockResolvedValue(fx.providersOneConnected);
      // `all` keeps the month: only the disconnected provider has none.
      mocked.months.mockImplementation((_org: string, provider: string) =>
        Promise.resolve({ months: provider === "anthropic" ? [] : ["2026-08"] }),
      );
      render(await ReconcilePage({ searchParams: fx.noSearch }));

      expect(mocked.summary).toHaveBeenCalledWith("default", "anthropic", {
        from: "2026-08-01",
        to: "2026-08-31",
      });
      expect(mocked.summary).toHaveBeenCalledWith("default", "openrouter", {
        from: "2026-08-01",
        to: "2026-08-31",
      });
      expect(screen.getByText("disconnected")).toBeInTheDocument();
      expect(screen.getByText(/historical data from a disconnected provider/)).toBeInTheDocument();
    });
  });
});

describe("runs", () => {
  it("lists runs newest first with plain job names and the error body", async () => {
    render(await RunsPage({ searchParams: fx.noSearch }));

    expect(mocked.runs).toHaveBeenCalledWith("default", "anthropic", 50, undefined);
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByText("Allocation")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("succeeded")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("Usage")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("failed")).toBeInTheDocument();
    expect(screen.getByText(/Cannot specify more than 5 group_by/)).toBeInTheDocument();
  });

  it("passes endpoint and limit filters", async () => {
    render(
      await RunsPage({
        searchParams: Promise.resolve({ endpoint: "cost_report", limit: "5" }),
      }),
    );
    expect(mocked.runs).toHaveBeenCalledWith("default", "anthropic", 5, "cost_report");
  });

  it("adds a provider column under all", async () => {
    page.view = { ...page.view!, scope: "all" };
    mocked.runs.mockResolvedValue({ runs: [fx.openRouterRun, ...fx.runs] });
    render(await RunsPage({ searchParams: fx.noSearch }));

    expect(mocked.runs).toHaveBeenCalledWith("default", "all", 50, undefined);
    expect(screen.getByText(/every provider/)).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "provider" })).toBeInTheDocument();
    const rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[0]!).getByText("OpenRouter")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("Anthropic")).toBeInTheDocument();
    cleanup();

    page.view = { ...page.view!, scope: "anthropic" };
    render(await RunsPage({ searchParams: fx.noSearch }));
    expect(screen.queryByRole("columnheader", { name: "provider" })).not.toBeInTheDocument();
    cleanup();
  });

  it("points the empty state at Sync now, or at welcome when nothing is connected", async () => {
    mocked.runs.mockResolvedValue({ runs: [] });
    render(await RunsPage({ searchParams: fx.noSearch }));
    expect(screen.getByText("No runs yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sync now from settings" })).toHaveAttribute(
      "href",
      "/settings/sync",
    );
    cleanup();

    mocked.setup.mockResolvedValue(fx.setupConnect);
    render(await RunsPage({ searchParams: fx.noSearch }));
    expect(screen.getByRole("link", { name: "Connect a provider" })).toHaveAttribute(
      "href",
      "/welcome",
    );
    cleanup();

    // Under one provider only that provider's key counts.
    mocked.setup.mockResolvedValue({ ...fx.setupReady, providers: fx.providersOneConnected });
    page.view = { ...page.view!, scope: "openrouter" };
    render(await RunsPage({ searchParams: fx.noSearch }));
    expect(screen.getByRole("link", { name: "Connect a provider" })).toBeInTheDocument();
    cleanup();

    // A failed setup call keeps the page up with the Sync now link.
    mocked.setup.mockRejectedValue(new Error("boom"));
    render(await RunsPage({ searchParams: fx.noSearch }));
    expect(screen.getByRole("link", { name: "Sync now from settings" })).toBeInTheDocument();
  });
});

describe("inventory", () => {
  it("defaults to api keys, shows month spend per key and flags missing rows", async () => {
    render(await InventoryPage({ searchParams: fx.noSearch }));

    expect(mocked.apiKeys).toHaveBeenCalledWith("default", "anthropic", false);
    expect(mocked.usage).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "api_key",
    );
    expect(mocked.workspaces).not.toHaveBeenCalled();
    expect(screen.getByText("2 of 2 keys")).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Search keys" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unused in August 2026" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "batch-ingest" })).toHaveAttribute(
      "href",
      "/keys/apikey_redacted_2",
    );
    expect(screen.getByText("40,000.00")).toBeInTheDocument();
    for (const summary of screen.getAllByText("Details")) fireEvent.click(summary);
    expect(screen.getByText("2026-09-10")).toBeInTheDocument();
    expect(screen.getByText("missing")).toBeInTheDocument();
    // Spend descending by default: the key with 40,000 comes before the retired one.
    const table = screen.getByRole("table", { name: /API keys in the inventory/ });
    expect(
      within(within(table).getAllByRole("row")[1]!).getByText("batch-ingest"),
    ).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: /^in period/ })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
  });

  it("switches kind and include_missing through the query string", async () => {
    render(
      await InventoryPage({
        searchParams: Promise.resolve({ kind: "workspaces", include_missing: "false" }),
      }),
    );

    expect(mocked.workspaces).toHaveBeenCalledWith("default", "anthropic", false);
    expect(mocked.usage).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "workspace",
    );
    expect(screen.getByText("alice@example.com")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "People & services" })).toHaveAttribute(
      "href",
      "/inventory?kind=users",
    );
  });

  it("badges keys of both providers under all and links each under its own", async () => {
    page.view = { ...page.view!, scope: "all" };
    mocked.apiKeys.mockResolvedValue({ items: [...fx.apiKeys, fx.openRouterKey] });
    mocked.usage.mockResolvedValue(fx.usageAll);
    render(await InventoryPage({ searchParams: fx.noSearch }));

    expect(mocked.apiKeys).toHaveBeenCalledWith("default", "all", false);
    expect(mocked.usage).toHaveBeenCalledWith(
      "default",
      "all",
      { from: "2026-08-01", to: "2026-08-31" },
      "api_key",
    );
    expect(screen.getByText("3 of 3 keys")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: /API keys in the inventory/ });
    expect(within(table).getByRole("columnheader", { name: "provider" })).toBeInTheDocument();
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
    // Spend is matched per provider and id: the OpenRouter key shows its own month figure.
    expect(screen.getByText("1,200.00")).toBeInTheDocument();
    cleanup();

    mocked.apiKeys.mockResolvedValue({ items: [] });
    render(await InventoryPage({ searchParams: fx.noSearch }));
    expect(
      screen.getByText("No keys in the inventory. Inventory arrives with the first import."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sync now from settings" })).toHaveAttribute(
      "href",
      "/settings/sync",
    );
  });
});
