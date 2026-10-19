/** The Overview page. */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import * as fx from "@/test/fixtures";
import { type SpendQuery } from "@/lib/api";
import OverviewPage from "./(app)/overview/page";
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

describe("overview", () => {
  it("renders KPIs with the previous-month delta, chart legend and top tables", async () => {
    render(await OverviewPage({ searchParams: fx.noSearch }));

    expect(mocked.summary).toHaveBeenCalledWith("default", "anthropic", {
      from: "2026-08-01",
      to: "2026-08-31",
    });
    expect(mocked.query).toHaveBeenCalledWith(
      "default",
      expect.objectContaining({
        measure: "billed_usd",
        dimensions: ["workspace"],
        start: "2026-08-01",
        end: "2026-08-31",
        interval: "day",
      }),
    );
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Spend in August 2026");
    expect(screen.getAllByText("56,056.12").length).toBeGreaterThan(0);
    expect(screen.getByText("+12.11%")).toBeInTheDocument();
    expect(screen.getByText(/July 2026: 50,000.00/)).toBeInTheDocument();
    expect(screen.getByText("Daily average")).toBeInTheDocument();
    expect(screen.getAllByText("28,028.06").length).toBeGreaterThan(0);
    // A closed month has no forecast, so the detector and token mix occupy the final slots.
    // The KPI stays on the first layer; the card is under More on this period.
    fireEvent.click(screen.getByText("More on this period"));
    expect(screen.getAllByText("Open anomalies")).toHaveLength(2);
    expect(screen.getByText("Cache reads")).toBeInTheDocument();
    expect(screen.queryByText("Top 5 keys")).not.toBeInTheDocument();
    expect(screen.queryByText("Projected end of month")).not.toBeInTheDocument();

    const legend = screen.getByRole("list", { name: "Legend" });
    expect(within(legend).getByText("Platform")).toBeInTheDocument();
    expect(within(legend).getByText("(default workspace)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "cumulative" })).toBeInTheDocument();

    expect(screen.getByRole("heading", { name: "Top API keys" })).toBeInTheDocument();
    expect(
      screen.getByText(/28.64% of spend \(16,056.12 USD\) counts under a person/),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Top accounts" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "See all" })[0]).toHaveAttribute(
      "href",
      "/explore?by=api_key",
    );
    // Row names lead to the entity page, not to Explore.
    expect(screen.getAllByRole("link", { name: "batch-ingest" })[0]).toHaveAttribute(
      "href",
      "/keys/apikey_redacted_2",
    );
    expect(screen.queryByText("Data quality")).not.toBeInTheDocument();
    expect(screen.queryByText("Token mix")).not.toBeInTheDocument();
    expect(screen.queryByText(/spend_cost_lines/)).not.toBeInTheDocument();
    // Card names are headings, so the outline reads them: money, then who spends, then what
    // to watch.
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual(
      expect.arrayContaining([
        "Daily spend",
        "Top API keys",
        "Top accounts",
        "What changed",
        "Open anomalies",
        "Budgets",
        "Where the money goes",
      ]),
    );
    // The provider breakdown moved into the chart card; no card of its own to stretch.
    expect(screen.queryByRole("heading", { name: "By provider" })).not.toBeInTheDocument();
    expect(screen.getByText(/How it is computed/)).toBeInTheDocument();
  });

  it("leads with people and hides the meaningless API-key card for Cursor", async () => {
    page.view = { ...page.view!, scope: "cursor" };

    render(await OverviewPage({ searchParams: fx.noSearch }));

    expect(screen.getByRole("heading", { name: "Top people" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Top API keys" })).not.toBeInTheDocument();
    expect(screen.getByText(/attributed directly to team members/)).toBeInTheDocument();
    expect(mocked.movers).toHaveBeenCalledWith(
      "default",
      "cursor",
      { from: "2026-08-01", to: "2026-08-31" },
      "person",
    );
  });

  it("shows OpenAI activity in the provider scope", async () => {
    page.view = { ...page.view!, scope: "openai" };
    mocked.activity.mockResolvedValue(fx.activity);

    render(await OverviewPage({ searchParams: fx.noSearch }));

    expect(mocked.activity).toHaveBeenCalledWith("default", {
      since: "2026-08-01",
      until: "2026-08-31",
    });
    expect(screen.getByRole("heading", { name: "Activity" })).toBeInTheDocument();
    expect(screen.getByText("Embeddings")).toBeInTheDocument();
    expect(screen.getByText(/25,000 input tokens/)).toBeInTheDocument();
  });

  it("queries the selected time frame and interval for the overview chart", async () => {
    page.view = {
      ...page.view!,
      from: "2026-06-15",
      to: "2026-09-12",
      interval: "week",
    };

    render(await OverviewPage({ searchParams: Promise.resolve({ by: "workspace" }) }));

    expect(mocked.query).toHaveBeenCalledWith(
      "default",
      expect.objectContaining({
        measure: "billed_usd",
        dimensions: ["workspace"],
        start: "2026-06-15",
        end: "2026-09-12",
        interval: "week",
        filters: { provider: "anthropic" },
      }),
    );
    const figures = screen.getByRole("region", { name: "Headline figures" });
    const peak = within(figures).getByText("Peak day").closest<HTMLElement>("[data-slot='card']")!;
    expect(within(peak).getByText("55,056.12")).toBeInTheDocument();
    expect(within(peak).getByText(/Aug 2; highest weekly bucket/)).toBeInTheDocument();
    expect(within(figures).queryByText("Buckets")).not.toBeInTheDocument();
  });

  it("puts what needs a person above the chart, whatever the time frame", async () => {
    mocked.signals.mockResolvedValue(fx.signals);
    render(await OverviewPage({ searchParams: fx.noSearch }));

    expect(mocked.signals).toHaveBeenCalledWith("default", "anthropic");
    const queue = screen.getByRole("heading", { name: "Needs a person" });
    const chart = screen.getByRole("heading", { name: "Daily spend" });
    expect(queue.compareDocumentPosition(chart) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("link", { name: "prod-backend (apikey_1)" })).toHaveAttribute(
      "href",
      "/anomalies/8",
    );
  });

  it("shows a real organization the strip with its last import", async () => {
    mocked.summary.mockResolvedValue(fx.summary);
    const query = mocked.query.getMockImplementation() as
      | ((org: string, request: { dimensions?: string[]; measure: string }) => Promise<SpendQuery>)
      | undefined;
    mocked.query.mockImplementation(
      async (org: string, request: { dimensions?: string[]; measure: string }) =>
        request.dimensions?.[0] === "model_lifecycle"
          ? {
              ...fx.spendQuery,
              dimensions: ["model_lifecycle"],
              series: [],
              total: fx.spendQuery.total.map(() => "0.00"),
            }
          : query!(org, request),
    );

    render(await OverviewPage({ searchParams: fx.noSearch }));

    const strip = screen.getByRole("list", { name: "Signals" });
    expect(within(strip).getByText("Last import")).toBeInTheDocument();
  });

  it("ranks what changed against the previous month in both directions", async () => {
    render(await OverviewPage({ searchParams: fx.noSearch }));

    expect(mocked.movers).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "api_key",
    );
    fireEvent.click(screen.getByText("More on this period"));
    expect(screen.getByText("Each API key's spend against July 2026.")).toBeInTheDocument();
    const up = screen.getByText("Spending more").parentElement!;
    expect(within(up).getByRole("link", { name: "batch-ingest" })).toHaveAttribute(
      "href",
      "/keys/apikey_redacted_2",
    );
    expect(up).toHaveTextContent("+28,000.00");
    expect(within(up).getByText("new")).toBeInTheDocument();
    const down = screen.getByText("Spending less").parentElement!;
    expect(down).toHaveTextContent("-9,000.00");
    expect(within(down).getByText("stopped")).toBeInTheDocument();
  });

  it("says why no key can be compared when a month has no attribution", async () => {
    mocked.movers.mockResolvedValue(fx.noMovers);
    render(await OverviewPage({ searchParams: fx.noSearch }));
    fireEvent.click(screen.getByText("More on this period"));

    expect(screen.getByText(/July 2026 or August 2026 has no attribution yet/)).toBeInTheDocument();
    expect(screen.queryByText("Spending more")).not.toBeInTheDocument();
  });

  it("leads the watch band with the worst open anomalies and their day", async () => {
    mocked.anomalies.mockResolvedValue(fx.mixedAnomalies);
    render(await OverviewPage({ searchParams: fx.noSearch }));
    fireEvent.click(screen.getByText("More on this period"));

    const card = screen
      .getAllByRole("heading", { name: "Open anomalies" })[0]!
      .closest<HTMLElement>("[data-slot='card']")!;
    const rows = within(card).getAllByRole("listitem");
    // Three of the four, in the API's severity order, each with its rule and its day.
    expect(rows).toHaveLength(3);
    expect(within(card).getByText("drop")).toBeInTheDocument();
    expect(within(card).getByText("new")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: /^All/ })).toHaveAttribute("href", "/anomalies");
  });

  it("tells the watch band that nothing left its baseline", async () => {
    render(await OverviewPage({ searchParams: fx.noSearch }));
    fireEvent.click(screen.getByText("More on this period"));

    expect(screen.getByText(/Nothing off baseline in August 2026/)).toBeInTheDocument();
    expect(screen.getByText("nothing left its baseline in August 2026")).toBeInTheDocument();
  });

  it("shows the BYOK figure outside the total only when the scope has one", async () => {
    render(await OverviewPage({ searchParams: fx.noSearch }));
    expect(screen.queryByText(/on your own provider keys/)).not.toBeInTheDocument();
    cleanup();

    mocked.summary.mockResolvedValue(fx.byokSummary);
    page.view = { ...page.view!, scope: "openrouter" };
    render(await OverviewPage({ searchParams: fx.noSearch }));
    // A line of the total card, not a fifth KPI: the money is billed elsewhere.
    expect(
      screen.getByText(/plus 56,872.78 USD on your own provider keys, billed by those providers/),
    ).toBeInTheDocument();
    // The headline total stays what OpenRouter billed.
    expect(screen.getAllByText("8,933.90").length).toBeGreaterThan(0);
  });

  it("keeps range analytics when monthly secondary data fails", async () => {
    mocked.budgetStatuses.mockRejectedValue(new Error("boom"));
    mocked.usage.mockRejectedValue(new Error("boom"));
    render(await OverviewPage({ searchParams: fx.noSearch }));

    expect(screen.getAllByText("56,056.12").length).toBeGreaterThan(0);
    expect(screen.getByText(/Could not load the budgets/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Top API keys" })).toBeInTheDocument();
  });

  it("says which card could not load when anomalies, movers or models fail", async () => {
    const answer = mocked.query.getMockImplementation() as (...args: unknown[]) => unknown;
    mocked.query.mockImplementation((org, query) =>
      query.dimensions?.includes("model") ? Promise.reject(new Error("boom")) : answer(org, query),
    );
    mocked.anomalies.mockRejectedValue(new Error("boom"));
    mocked.movers.mockRejectedValue(new Error("boom"));
    render(await OverviewPage({ searchParams: fx.noSearch }));

    expect(screen.getAllByText("56,056.12").length).toBeGreaterThan(0);
    expect(screen.getByText("could not be loaded; reload to retry")).toBeInTheDocument();
    expect(screen.getByText(/Could not load the model breakdown/)).toBeInTheDocument();
    expect(
      screen.getByText(/Could not load the comparison with the previous period/),
    ).toBeInTheDocument();
  });

  it("compares a month in progress with the same days of the month before", async () => {
    mocked.summary.mockResolvedValue({
      ...fx.summary,
      is_current_month: true,
      comparison_basis: "month_to_date",
      previous_start: "2026-07-01",
      previous_end: "2026-07-14",
    });
    render(await OverviewPage({ searchParams: fx.noSearch }));
    expect(screen.getByText(/against Jul 1 to Jul 14 \(50,000.00 USD\)/)).toBeInTheDocument();
    expect(screen.getByText(/Jul 1 to Jul 14: 50,000.00/)).toBeInTheDocument();
    expect(screen.queryByText(/July 2026: 50,000.00/)).not.toBeInTheDocument();
  });

  it("never colors a drop over part of a month as savings, and names the data's end", async () => {
    mocked.summary.mockResolvedValue({
      ...fx.summary,
      total: "20000.00",
      change_percent: "-60.00",
      comparison_basis: "month_to_date",
      previous_start: "2026-07-01",
      previous_end: "2026-07-14",
      complete_through: "2026-08-14",
      data_stale: true,
    });
    render(await OverviewPage({ searchParams: fx.noSearch }));
    expect(
      screen.getByText(/against Jul 1 to Jul 14 .* Data through Aug 14\. The last import failed\./),
    ).toBeInTheDocument();
    const delta = screen
      .getByText("Total")
      .closest<HTMLElement>("[data-slot='card']")!
      .querySelector(".bg-severity-success-bg");
    expect(delta).toBeNull();
  });

  it("lists each currency instead of adding amounts in different currencies", async () => {
    mocked.summary.mockResolvedValue({
      ...fx.summary,
      currency: null,
      currency_totals: { EUR: "7.50", USD: "10.00" },
    });
    render(await OverviewPage({ searchParams: fx.noSearch }));
    const total = screen.getByText("Total").closest<HTMLElement>("[data-slot='card']")!;
    expect(total).toHaveTextContent("7.50 EUR + 10.00 USD");
    expect(total).toHaveTextContent("several currencies");
  });

  it("falls back to the run-rate projection until the scheduler has projected", async () => {
    mocked.summary.mockResolvedValue({
      ...fx.summary,
      is_current_month: true,
      projected_total: "868869.86",
    });
    render(await OverviewPage({ searchParams: fx.noSearch }));
    expect(screen.getByText("Projected end of month")).toBeInTheDocument();
    expect(screen.getByText("868,869.86")).toBeInTheDocument();
    expect(screen.getByText(/run rate/)).toBeInTheDocument();
    const kpi = screen
      .getByText("Projected end of month")
      .closest<HTMLElement>("[data-slot='card']")!;
    fireEvent.click(within(kpi).getByRole("button", { name: "How this is computed" }));
    expect(await screen.findByText(/Daily average x days in the month/)).toBeInTheDocument();
  });

  it("shows the stored projection with its band and the forecast legend", async () => {
    mocked.summary.mockResolvedValue({ ...fx.summary, is_current_month: true });
    mocked.projection.mockResolvedValue(fx.projections);
    render(await OverviewPage({ searchParams: fx.noSearch }));

    expect(mocked.projection).toHaveBeenCalledWith("default", "anthropic", "2026-08", "org");
    expect(screen.getByText("Projected end of month")).toBeInTheDocument();
    expect(screen.getByText("52,100.00")).toBeInTheDocument();
    expect(screen.getByText(/48,900.00 to 55,600.00/)).toBeInTheDocument();
    // The method sits behind a button any pointer or keyboard can open, on the KPI and on the
    // legend's one word.
    const kpi = screen
      .getByText("Projected end of month")
      .closest<HTMLElement>("[data-slot='card']")!;
    fireEvent.click(within(kpi).getByRole("button", { name: "How this is computed" }));
    expect(await screen.findByText(/Same weekday over the last 4 weeks/)).toBeInTheDocument();
    const legend = screen.getByRole("list", { name: "Legend" });
    expect(within(legend).getByText("projected")).toBeInTheDocument();
    fireEvent.click(within(legend).getByRole("button", { name: "How this is computed" }));
    expect(
      await screen.findByText(
        "Median of the same weekday over the last 4 weeks; band from the last 8",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/run rate/)).not.toBeInTheDocument();
  });

  it("links to the open anomalies and marks them on the chart legend", async () => {
    mocked.anomalies.mockResolvedValue(fx.anomalies);
    render(await OverviewPage({ searchParams: fx.noSearch }));

    expect(mocked.anomalies).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "open",
      undefined,
      "severity",
    );
    // The KPI carries the count and the worst anomaly's own money, linked to that anomaly.
    expect(screen.getByText("3")).toBeInTheDocument();
    const anomalyLink = screen.getByRole("link", {
      name: "worst: high severity, +900.00 USD off baseline",
    });
    expect(anomalyLink).toHaveAttribute("href", "/anomalies/8");
    expect(
      anomalyLink.closest<HTMLElement>("[data-slot='card']")!.querySelector("[data-slot='badge']"),
    ).not.toBeInTheDocument();
    expect(screen.getByText("anomaly")).toBeInTheDocument();
  });

  it("shows the empty budgets card with a link to the budgets page", async () => {
    render(await OverviewPage({ searchParams: fx.noSearch }));
    fireEvent.click(screen.getByText("More on this period"));

    expect(mocked.budgetStatuses).toHaveBeenCalledWith("default", "anthropic", "2026-08");
    expect(screen.getByText(/No budget set for this organization/)).toBeInTheDocument();
    // Once in the budgets card, once in the getting-started checklist.
    const links = screen.getAllByRole("link", { name: "Set a monthly budget" });
    expect(links).toHaveLength(2);
    for (const link of links) {
      expect(link).toHaveAttribute("href", "/budgets");
    }
    expect(screen.queryByRole("meter")).not.toBeInTheDocument();
    cleanup();

    // The sample's budgets are fixed: no link to set one, and the header link only views.
    page.organizations = [{ ...fx.organization, is_demo: true, role: null }];
    render(await OverviewPage({ searchParams: fx.noSearch }));
    fireEvent.click(screen.getByText("More on this period"));
    expect(screen.getByText(/No budget set for this organization/)).toHaveTextContent(
      "The sample's budgets are fixed",
    );
    expect(screen.queryByRole("link", { name: "Set a monthly budget" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View budgets" })).toHaveAttribute("href", "/budgets");
  });

  it("draws one bar per budget, counts the alerts and adds the budget to the KPI", async () => {
    mocked.summary.mockResolvedValue({ ...fx.summary, is_current_month: true });
    mocked.projection.mockResolvedValue(fx.projections);
    mocked.budgetStatuses.mockResolvedValue(fx.budgetStatuses);
    render(await OverviewPage({ searchParams: fx.noSearch }));
    fireEvent.click(screen.getByText("More on this period"));

    const org = screen.getByRole("meter", { name: "organization total budget" });
    expect(org).toHaveAttribute("aria-valuenow", "93");
    expect(screen.getByRole("meter", { name: "Platform budget" })).toHaveAttribute(
      "aria-valuenow",
      "81",
    );
    expect(screen.getAllByText("93.43%").length).toBeGreaterThan(0);
    expect(screen.getByText(/56,056.12 of 60,000.00/)).toBeInTheDocument();
    expect(screen.getByText(/projected 11,800.00 \(118.00%\)/)).toBeInTheDocument();

    // The alert sentences live on the budgets page; the card links to them with the count.
    expect(screen.queryByRole("list", { name: "Budget alerts" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "4 alerts in August 2026" })).toHaveAttribute(
      "href",
      "/budgets",
    );
    // The projection KPI reads the org budget: projected 52,100 is 86.83% of 60,000.
    expect(screen.getByText(/86.83% of the 60,000.00 budget/)).toBeInTheDocument();
    // Under one provider the rows carry no provider badge.
    const orgRow = org.closest("li")!;
    expect(within(orgRow).queryByText("Anthropic")).not.toBeInTheDocument();
  });

  it("names the provider on each budget row under all, since a budget caps one provider", async () => {
    page.view = { ...page.view!, scope: "all" };
    mocked.summary.mockResolvedValue({ ...fx.summary, is_current_month: true });
    mocked.budgetStatuses.mockResolvedValue(fx.budgetStatuses);
    render(await OverviewPage({ searchParams: fx.noSearch }));
    fireEvent.click(screen.getByText("More on this period"));

    const orgRow = screen.getByRole("meter", { name: "organization total budget" }).closest("li")!;
    expect(within(orgRow).getByText("Anthropic")).toBeInTheDocument();
  });

  it("groups Top accounts by person in every provider scope", async () => {
    page.view = { ...page.view!, scope: "all" };
    render(await OverviewPage({ searchParams: fx.noSearch }));
    fireEvent.click(screen.getByText("More on this period"));
    expect(mocked.usage).toHaveBeenCalledWith(
      "default",
      "all",
      { from: "2026-08-01", to: "2026-08-31" },
      "person",
      8,
    );
    const seeAll = screen
      .getAllByRole("link", { name: "See all" })
      .map((a) => a.getAttribute("href"));
    expect(seeAll).toContain("/explore?by=person");

    cleanup();
    vi.clearAllMocks();
    page.view = { ...page.view!, scope: "anthropic" };
    mocked.summary.mockResolvedValue(fx.summary);
    mocked.series.mockResolvedValue(fx.series);
    mocked.usage.mockResolvedValue(fx.usage);
    render(await OverviewPage({ searchParams: fx.noSearch }));
    expect(mocked.usage).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "person",
      8,
    );
    expect(screen.getByText(/own login or Claude Code key/)).toBeInTheDocument();
  });

  it("regroups the chart from the query string", async () => {
    render(await OverviewPage({ searchParams: Promise.resolve({ by: "api_key" }) }));
    expect(mocked.query).toHaveBeenCalledWith(
      "default",
      expect.objectContaining({ dimensions: ["api_key"], top: 6 }),
    );
    expect(screen.getByRole("link", { name: "API key" })).toHaveAttribute("aria-current", "true");
  });

  it("links to Sync now when the month has no spend but a key is connected", async () => {
    mocked.summary.mockResolvedValue({ ...fx.summary, total: "0.00", allocation: null });
    render(await OverviewPage({ searchParams: fx.noSearch }));

    expect(screen.getByText(/No spend recorded for August 2026/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sync now from settings" })).toHaveAttribute(
      "href",
      "/settings/sync",
    );
    cleanup();

    // An instance that refuses writes gets the same link; settings explains the state there.
    mocked.setup.mockResolvedValue({ ...fx.setupReady, writes_enabled: false });
    render(await OverviewPage({ searchParams: fx.noSearch }));
    expect(screen.getByRole("link", { name: "Sync now from settings" })).toHaveAttribute(
      "href",
      "/settings/sync",
    );
  });

  it("links to the welcome page when the organization has no key", async () => {
    mocked.summary.mockResolvedValue({ ...fx.summary, total: "0.00", allocation: null });
    mocked.setup.mockResolvedValue(fx.setupConnect);
    render(await OverviewPage({ searchParams: fx.noSearch }));

    // The connection route refuses `all`, so the empty state reads the setup answer instead.
    expect(mocked.connection).not.toHaveBeenCalled();
    expect(screen.getByText(/no Anthropic key connected/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Connect your Anthropic admin key" })).toHaveAttribute(
      "href",
      "/welcome",
    );
    expect(screen.queryByText(/costura/)).not.toBeInTheDocument();
  });

  it("points at the running first import while it has not finished", async () => {
    mocked.summary.mockResolvedValue({ ...fx.summary, total: "0.00", allocation: null });
    mocked.setup.mockResolvedValue(fx.setupSyncing);
    render(await OverviewPage({ searchParams: fx.noSearch }));

    expect(screen.getByText(/the first import has not finished/)).toBeInTheDocument();
    // The banner above follows the run; the link leads to the run history, not to welcome.
    expect(screen.getByRole("link", { name: "See the first import" })).toHaveAttribute(
      "href",
      "/runs",
    );
  });

  it("names the OpenRouter management key from the registry when that scope has no key", async () => {
    mocked.summary.mockResolvedValue({ ...fx.summary, total: "0.00", allocation: null });
    mocked.setup.mockResolvedValue({
      ...fx.setupReady,
      providers: fx.providersOneConnected,
      writes_enabled: false,
    });
    page.view = { ...page.view!, scope: "openrouter" };
    render(await OverviewPage({ searchParams: fx.noSearch }));
    expect(screen.getByText(/no OpenRouter key connected/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Connect your OpenRouter management key" }),
    ).toHaveAttribute("href", "/welcome");
    expect(screen.queryByRole("link", { name: "Sync now from settings" })).not.toBeInTheDocument();
  });

  it("shows the getting-started card until it is dismissed", async () => {
    mocked.setup.mockResolvedValue({ ...fx.setupReady, providers: fx.providersOneConnected });
    render(await OverviewPage({ searchParams: fx.noSearch }));

    expect(screen.getByRole("heading", { name: "Getting started" })).toBeInTheDocument();
    expect(screen.getByText("2 of 3 left; each takes a minute.")).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Getting started" });
    expect(
      within(list)
        .getAllByRole("link")
        .map((a) => a.textContent),
    ).toEqual(["First import complete", "Connect a second provider", "Set a monthly budget"]);
    // A month with cost lines means the first import landed.
    expect(within(list).getByRole("link", { name: "First import complete" })).toHaveAttribute(
      "href",
      "/runs",
    );
    expect(within(list).getByRole("link", { name: "Connect a second provider" })).toHaveAttribute(
      "href",
      "/welcome",
    );
    expect(within(list).getByRole("link", { name: "Set a monthly budget" })).toHaveAttribute(
      "href",
      "/budgets",
    );
    expect(within(list).getAllByRole("img", { name: "done" })).toHaveLength(1);
    expect(within(list).getAllByRole("img", { name: "to do" })).toHaveLength(2);
    // The form names no organization: the action reads it from the view cookie.
    const dismiss = screen.getByRole("button", { name: "Dismiss" }).closest("form")!;
    expect(dismiss.querySelector('input[name="org"]')).toBeNull();
    cleanup();

    // Two providers and a budget tick the next two items; open anomalies add the fourth.
    mocked.setup.mockResolvedValue(fx.setupReady);
    mocked.budgetStatuses.mockResolvedValue(fx.budgetStatuses);
    mocked.anomalies.mockResolvedValue(fx.anomalies);
    render(await OverviewPage({ searchParams: fx.noSearch }));
    expect(screen.getByText("1 of 4 left; each takes a minute.")).toBeInTheDocument();
    expect(screen.getAllByRole("img", { name: "done" })).toHaveLength(3);
    expect(screen.getByRole("link", { name: "Review the first anomalies" })).toHaveAttribute(
      "href",
      "/anomalies",
    );
    cleanup();

    // Never on the sample organization, whatever the setup answer says.
    page.organizations = [{ ...fx.organization, is_demo: true, role: null }];
    render(await OverviewPage({ searchParams: fx.noSearch }));
    expect(screen.queryByRole("heading", { name: "Getting started" })).not.toBeInTheDocument();
    expect(screen.getAllByText("56,056.12").length).toBeGreaterThan(0);
    cleanup();
    page.organizations = [fx.organization, fx.demoOrganization];

    mocked.setup.mockResolvedValue({ ...fx.setupReady, dismissed_at: "2026-09-14T21:00:00Z" });
    render(await OverviewPage({ searchParams: fx.noSearch }));
    expect(screen.queryByRole("heading", { name: "Getting started" })).not.toBeInTheDocument();
    cleanup();

    // Without writes the card stays but cannot be dismissed; a failed setup call hides it.
    mocked.setup.mockResolvedValue({ ...fx.setupReady, writes_enabled: false });
    render(await OverviewPage({ searchParams: fx.noSearch }));
    expect(screen.getByRole("heading", { name: "Getting started" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dismiss" })).not.toBeInTheDocument();
    cleanup();

    mocked.setup.mockRejectedValue(new Error("boom"));
    render(await OverviewPage({ searchParams: fx.noSearch }));
    expect(screen.queryByRole("heading", { name: "Getting started" })).not.toBeInTheDocument();
    expect(screen.getAllByText("56,056.12").length).toBeGreaterThan(0);
  });

  it("tells the sample organization's story in the signal strip", async () => {
    page.organizations = [{ ...fx.organization, is_demo: true, role: null }];
    mocked.anomalies.mockResolvedValue(fx.anomalies);
    mocked.budgetStatuses.mockResolvedValue(fx.budgetStatuses);
    mocked.setup.mockResolvedValue({ ...fx.setupReady, dismissed_at: "2026-09-14T21:00:00Z" });
    render(await OverviewPage({ searchParams: fx.noSearch }));
    const strip = screen.getByRole("list", { name: "Signals" });
    expect(within(strip).queryByText("Investigate first")).not.toBeInTheDocument();
    expect(within(strip).getByRole("link", { name: "View budgets" })).toHaveAttribute(
      "href",
      "/budgets",
    );
    cleanup();

    // Nothing to tell: no anomaly, budget or finished import leaves the strip out.
    mocked.anomalies.mockResolvedValue(fx.noAnomalies);
    mocked.budgetStatuses.mockResolvedValue(fx.noBudgets);
    mocked.setup.mockResolvedValue({ ...fx.setupReady, runs: [] });
    render(await OverviewPage({ searchParams: fx.noSearch }));
    expect(screen.queryByRole("list", { name: "Signals" })).not.toBeInTheDocument();
  });

  describe("under all providers", () => {
    beforeEach(() => {
      page.view = { ...page.view!, scope: "all" };
    });

    it("groups the chart by provider, lists the provider shares and badges the top keys", async () => {
      mocked.usage.mockImplementation(
        (_org: string, _provider: string, _month: string, by: string) =>
          Promise.resolve(by === "provider" ? fx.usageByProvider : fx.usageAll),
      );
      render(await OverviewPage({ searchParams: fx.noSearch }));

      expect(mocked.summary).toHaveBeenCalledWith("default", "all", {
        from: "2026-08-01",
        to: "2026-08-31",
      });
      expect(mocked.query).toHaveBeenCalledWith(
        "default",
        expect.objectContaining({ dimensions: ["provider"], top: 6 }),
      );
      expect(mocked.usage).toHaveBeenCalledWith(
        "default",
        "all",
        { from: "2026-08-01", to: "2026-08-31" },
        "provider",
      );
      expect(screen.getByRole("link", { name: "Provider" })).toHaveAttribute(
        "aria-current",
        "true",
      );
      const legend = screen.getByRole("list", { name: "Legend" });
      expect(within(legend).queryByText("Anthropic")).not.toBeInTheDocument();
      expect(within(legend).queryByText("OpenRouter")).not.toBeInTheDocument();

      // The provider strip lives in the chart card and drills into Explore filtered to that
      // provider.
      const strip = screen.getByRole("list", { name: "Spend by provider" });
      expect(within(strip).getAllByRole("listitem")).toHaveLength(2);
      expect(strip).toHaveTextContent("Anthropic");
      expect(within(strip).getByRole("link", { name: "OpenRouter" })).toHaveAttribute(
        "href",
        "/explore?by=person&f=provider%3Ais%3Aopenrouter",
      );
      // Rows of the top keys carry a provider badge and open under their own provider.
      expect(screen.getAllByRole("link", { name: "router-prod" })[0]).toHaveAttribute(
        "href",
        "/keys/orkey_hash_1",
      );
      expect(screen.getAllByRole("link", { name: "batch-ingest" })[0]).toHaveAttribute(
        "href",
        "/keys/apikey_redacted_2",
      );
      const keys = screen.getByRole("table", { name: "Top API keys" });
      expect(within(keys).getAllByText("Anthropic").length).toBeGreaterThan(0);
      expect(within(keys).getAllByText("OpenRouter")).toHaveLength(1);
    });

    it("hides the provider grouping and the strip under one provider", async () => {
      page.view = { ...page.view!, scope: "anthropic" };
      render(await OverviewPage({ searchParams: fx.noSearch }));
      expect(screen.queryByRole("link", { name: "Provider" })).not.toBeInTheDocument();
      expect(screen.queryByRole("list", { name: "Spend by provider" })).not.toBeInTheDocument();
      expect(mocked.usage).not.toHaveBeenCalledWith(
        "default",
        "anthropic",
        { from: "2026-08-01", to: "2026-08-31" },
        "provider",
      );
    });

    it("points the empty state at settings, or at welcome when nothing is connected", async () => {
      mocked.summary.mockResolvedValue({ ...fx.summary, total: "0.00", allocation: null });
      mocked.setup.mockResolvedValue({
        ...fx.setupReady,
        providers: fx.providersOneConnected,
        writes_enabled: false,
      });
      render(await OverviewPage({ searchParams: fx.noSearch }));
      expect(screen.getByRole("link", { name: "Sync now from settings" })).toHaveAttribute(
        "href",
        "/settings/sync",
      );
      cleanup();

      mocked.setup.mockResolvedValue(fx.setupConnect);
      render(await OverviewPage({ searchParams: fx.noSearch }));
      expect(screen.getByText(/no provider key connected/)).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Connect a provider" })).toHaveAttribute(
        "href",
        "/welcome",
      );
      expect(
        screen.queryByRole("link", { name: "Sync now from settings" }),
      ).not.toBeInTheDocument();
    });
  });
});
