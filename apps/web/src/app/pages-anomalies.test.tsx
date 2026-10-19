/** The anomaly list and the anomaly detail page. */

import { describe, expect, it, onTestFinished, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import * as fx from "@/test/fixtures";
import { ApiError } from "@/lib/api";
import AnomalyPage from "./(app)/anomalies/[id]/page";
import AnomaliesPage from "./(app)/anomalies/page";
import { markReadAction, page, withPageDefaults, type MockedApi } from "@/test/page-harness";

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

describe("anomalies", () => {
  it("summarizes, groups by day and links each series to its entity page", async () => {
    page.view = { org: "default", month: "2026-08", scope: "anthropic" };
    page.pathname = "/anomalies";
    mocked.anomalies.mockResolvedValue(fx.anomalies);
    render(await AnomaliesPage({ searchParams: fx.noSearch }));

    expect(mocked.anomalies).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "open",
      undefined,
      "day",
    );
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Anomalies in August 2026");
    expect(screen.queryByRole("region", { name: "Quick wins" })).not.toBeInTheDocument();
    const feed = screen.getByRole("region", { name: "Anomaly feed" });
    const summary = screen.getByRole("region", { name: "Summary" });
    expect(within(summary).getByText("Open").nextSibling).toHaveTextContent("3");
    expect(within(summary).getByText("Days affected")).toBeInTheDocument();
    // Day headings, most recent first.
    const days = screen
      .getAllByRole("heading", { level: 2 })
      .map((h) => h.textContent)
      .filter((heading) => /Aug 1[0-9]/.test(heading ?? ""));
    expect(days[0]).toMatch(/Aug 1[0-9]/);
    // The login anomaly is titled with the user's e-mail and badged; the same e-mail is a
    // driver of the org anomaly, where it opens the account page.
    const anaLinks = within(feed).getAllByRole("link", { name: "ana@example.com" });
    expect(anaLinks.map((link) => link.getAttribute("href")).sort()).toEqual([
      "/accounts/user_01",
      "/anomalies/7",
      "mailto:ana@example.com",
    ]);
    expect(within(feed).getAllByText("Claude Code login")).toHaveLength(1);
    expect(within(feed).getByRole("link", { name: "Open the account" })).toHaveAttribute(
      "href",
      "/accounts/user_01",
    );
    expect(
      within(feed).getByText(
        /Spent 1,420.00; the same Tuesday over the last 8 weeks was 610.00, upper bound 890.00; 132.79% over the baseline/,
      ),
    ).toBeInTheDocument();
    // The episode's impact and its share of the period are the primary figures; severity
    // comes from the detector, which weighs the money against the series' own swing.
    expect(within(feed).getByText("+810.00 USD")).toBeInTheDocument();
    expect(within(feed).getByText("12.4% of the period's spend")).toBeInTheDocument();
    expect(within(feed).getByText("13.8% of the period's spend")).toBeInTheDocument();
    expect(within(feed).getByText("0.9% of the period's spend")).toBeInTheDocument();
    expect(within(feed).getAllByText("high severity")).toHaveLength(2);
    expect(within(feed).getByText("medium severity")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "By severity" })).toHaveAttribute(
      "href",
      "/anomalies?sort=severity",
    );
    // The first owner is one click away; a login anomaly carries no owner line, the
    // title is the person.
    expect(within(feed).getByRole("link", { name: "bruno@example.com" })).toHaveAttribute(
      "href",
      "mailto:bruno@example.com",
    );
    expect(within(feed).queryByText(/Contact ana@example.com/)).not.toBeInTheDocument();
    expect(within(feed).getByRole("link", { name: "prod-backend" })).toHaveAttribute(
      "href",
      "/keys/apikey_1",
    );
    fireEvent.click(screen.getByText("Filters"));
    expect(screen.getByRole("group", { name: "Order" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "By impact" })).toHaveAttribute(
      "href",
      "/anomalies?sort=impact",
    );
    expect(within(feed).getAllByRole("button", { name: "Acknowledge" })).toHaveLength(3);
    expect(within(feed).getAllByRole("button", { name: "Ignore" })).toHaveLength(3);
    expect(screen.getByRole("group", { name: "Status" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Series" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Users" })).toHaveAttribute(
      "href",
      "/anomalies?kind=account",
    );
    expect(screen.queryByRole("link", { name: "Workspaces" })).not.toBeInTheDocument();
  });

  it("lists the signals closed in the last 90 days with how long each stayed open", async () => {
    mocked.signalHistory.mockResolvedValueOnce({
      items: [
        {
          kind: "sync_stale",
          provider: "openai",
          entity_kind: "provider_account",
          entity_id: "2",
          label: "OpenAI production",
          detail: "latest cost import failed",
          dollars_at_risk: "41.00",
          currency: "USD",
          opened_at: "2026-09-12T06:00:00Z",
          closed_at: "2026-09-12T09:30:00Z",
          hours_open: "3.5",
        },
      ],
    });
    render(await AnomaliesPage({ searchParams: fx.noSearch }));
    const list = screen.getByRole("list", { name: "Closed in the last 90 days" });
    expect(list.textContent).toContain("OpenAI production");
    expect(list.textContent).toContain("after 3.5 hours");
  });

  it("names the rule and the run of each episode", async () => {
    page.view = { org: "default", month: "2026-08", scope: "anthropic" };
    page.pathname = "/anomalies";
    mocked.anomalies.mockResolvedValue(fx.mixedAnomalies);
    render(await AnomaliesPage({ searchParams: fx.noSearch }));
    const feed = screen.getByRole("region", { name: "Anomaly feed" });

    // A drop is money that stopped arriving: negative figure, lower bound, its own badge.
    expect(within(feed).getByText("drop")).toBeInTheDocument();
    expect(within(feed).getByText("-880.00 USD")).toBeInTheDocument();
    expect(
      within(feed).getByText(
        /the same Tuesday over the last 8 weeks was 1,000.00, lower bound 700.00/,
      ),
    ).toBeInTheDocument();
    expect(within(feed).getByText(/88.00% under the baseline/)).toBeInTheDocument();
    // Money that stopped arriving is not added to the overspend, and the day says so with a minus.
    expect(screen.getByText(/drops are 880\.00 under it/)).toBeInTheDocument();
    expect(screen.getByText(/-880\.00 impact/)).toBeInTheDocument();
    // A driver that fell carries its own minus sign, never "+-".
    expect(within(feed).getByText(/^-380\.00/)).toBeInTheDocument();
    expect(within(feed).queryByText(/\+-/)).not.toBeInTheDocument();
    // A key younger than the baseline window: everything it spent is the figure.
    expect(within(feed).getByText("new")).toBeInTheDocument();
    expect(within(feed).getByText("+420.00 USD")).toBeInTheDocument();
    expect(
      within(feed).getByText(/nothing to compare against: the series is less than 12 days old/),
    ).toBeInTheDocument();
    // A running level shift is one row with its duration and the whole run's total.
    expect(within(feed).getByText("ongoing, 4 days so far")).toBeInTheDocument();
    expect(within(feed).getByText("+3,600.00 USD")).toBeInTheDocument();
    expect(
      within(feed).getByText(/Spent 1,900.00 on the first day, 7,600.00 over the run/),
    ).toBeInTheDocument();
  });

  it("says when the inventory names nobody instead of presenting the fallback as the contact", async () => {
    const orphan = {
      ...fx.anomaly,
      id: 9,
      series_id: "terminal-bench-mukerem",
      label: "terminal-bench-mukerem (not in inventory)",
      owners: [
        { email: "owner@example.com", role: "organization owner", source: "Costura organization" },
      ],
      owners_gap:
        "The provider's key listing does not include this key; the usage report names it only as `terminal-bench-mukerem`. Nobody is recorded as its creator.",
    };
    mocked.anomalies.mockResolvedValue({ ...fx.anomalies, anomalies: [orphan] });
    render(await AnomaliesPage({ searchParams: fx.noSearch }));
    const feed = screen.getByRole("region", { name: "Anomaly feed" });

    expect(within(feed).queryByText(/^Contact/)).not.toBeInTheDocument();
    const line = within(feed).getByText("Nobody recorded in the provider inventory").closest("p")!;
    expect(line).not.toHaveAttribute("title");
    expect(within(line).getByRole("button", { name: "How this is computed" })).toBeInTheDocument();
    expect(within(line).getByRole("link", { name: "owner@example.com" })).toBeInTheDocument();
    // The title is the card's stretched link, styled as text: no tooltip, no link colour.
    const title = within(feed).getByRole("link", {
      name: "terminal-bench-mukerem (not in inventory)",
    });
    expect(title).toHaveAttribute("href", "/anomalies/9");
    expect(title).not.toHaveAttribute("title");
    expect(title.className).not.toMatch(/text-primary/);
  });

  it("leads each anomaly with the sentence that explains it", async () => {
    mocked.anomalies.mockResolvedValue(fx.anomalies);
    render(await AnomaliesPage({ searchParams: fx.noSearch }));
    expect(screen.getAllByText(fx.anomaly.explanation).length).toBeGreaterThan(0);
  });

  it("keeps the drivers collapsed behind a count and expands on demand", async () => {
    mocked.anomalies.mockResolvedValue(fx.anomalies);
    render(await AnomaliesPage({ searchParams: fx.noSearch }));

    const counts = screen.getAllByText(/^\d+ drivers?$/);
    expect(counts.length).toBe(3);
    expect(counts[0]!.closest("summary")).toBeNull();
    const toggle = screen.getAllByText("show all")[0];
    const details = toggle!.closest("details");
    expect(details).not.toBeNull();
    expect(details).toHaveProperty("open", false);
    expect(within(toggle!.closest("summary")!).queryByRole("link")).toBeNull();
    fireEvent.click(toggle!.closest("summary")!);
    expect(details).toHaveProperty("open", true);
    // A driver measured on the anomaly's baseline days says how much of the change is its own.
    expect(
      screen.getAllByText(/400\.00 on the baseline days; 71\.00% of the increase/).length,
    ).toBeGreaterThan(0);
  });

  it("selects anomalies for a bulk acknowledge or ignore", async () => {
    mocked.anomalies.mockResolvedValue(fx.anomalies);
    render(await AnomaliesPage({ searchParams: fx.noSearch }));

    expect(screen.queryByRole("form", { name: "Bulk actions" })).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("checkbox", { name: /Select the account anomaly ana@example.com/ }),
    );
    const bar = screen.getByRole("form", { name: "Bulk actions" });
    expect(bar).toHaveTextContent("1 selected");
    expect(within(bar).getByRole("button", { name: "Acknowledge" })).toBeInTheDocument();
    expect(within(bar).getByRole("button", { name: "Ignore" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox", { name: "Select every open anomaly" }));
    expect(screen.getByRole("form", { name: "Bulk actions" })).toHaveTextContent("3 selected");
  });

  it("omits every mutation control when instance writes are off or the organization is demo", async () => {
    mocked.anomalies.mockResolvedValue(fx.anomalies);
    mocked.setup.mockResolvedValue({ ...fx.setupReady, writes_enabled: false });
    render(await AnomaliesPage({ searchParams: fx.noSearch }));

    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Acknowledge" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ignore" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reopen" })).not.toBeInTheDocument();
    cleanup();

    mocked.setup.mockResolvedValue(fx.setupReady);
    page.organizations = [{ ...fx.organization, is_demo: true, role: null }];
    render(await AnomaliesPage({ searchParams: fx.noSearch }));
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Acknowledge" })).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Anomaly feed" })).toBeInTheDocument();
    cleanup();

    // A viewer reads the same rows; the status controls belong to the member role.
    page.organizations = [{ ...fx.organization, role: "viewer" }];
    render(await AnomaliesPage({ searchParams: fx.noSearch }));
    expect(screen.getAllByRole("heading", { level: 2 }).length).toBeGreaterThan(0);
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Acknowledge" })).not.toBeInTheDocument();
  });

  it("filters by status and series kind from the query string and offers Reopen on closed rows", async () => {
    mocked.anomalies.mockResolvedValue({
      ...fx.anomalies,
      anomalies: [{ ...fx.anomaly, status: "acknowledged" }, fx.newKeyAnomaly],
    });
    render(
      await AnomaliesPage({
        searchParams: Promise.resolve({ status: "acknowledged", kind: "account" }),
      }),
    );
    const feed = screen.getByRole("region", { name: "Anomaly feed" });

    expect(mocked.anomalies).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "acknowledged",
      undefined,
      "day",
    );
    // The kind filter is applied in the page: only the user card is listed.
    expect(within(feed).getAllByRole("heading", { level: 3 })).toHaveLength(1);
    expect(within(feed).queryByRole("link", { name: "experiment" })).not.toBeInTheDocument();
    expect(within(feed).getByRole("button", { name: "Reopen" })).toBeInTheDocument();
    expect(within(feed).queryByRole("button", { name: "Acknowledge" })).not.toBeInTheDocument();
    expect(within(feed).queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("explains the empty state by when anomalies are re-evaluated", async () => {
    render(await AnomaliesPage({ searchParams: fx.noSearch }));

    expect(
      screen.getByText(
        "No open anomalies in August 2026. Anomalies are re-evaluated with every import.",
      ),
    ).toBeInTheDocument();
    expect(document.querySelector("pre")).toBeNull();
  });

  describe("under all providers", () => {
    it("badges each card with its provider and links under that provider", async () => {
      page.view = { org: "default", month: "2026-08", scope: "all" };
      page.pathname = "/anomalies";
      mocked.anomalies.mockResolvedValue({
        ...fx.anomalies,
        open_count: 4,
        anomalies: [...fx.anomalies.anomalies, fx.openRouterAnomaly],
      });
      render(await AnomaliesPage({ searchParams: fx.noSearch }));
      const feed = screen.getByRole("region", { name: "Anomaly feed" });

      expect(mocked.anomalies).toHaveBeenCalledWith(
        "default",
        "all",
        { from: "2026-08-01", to: "2026-08-31" },
        "open",
        undefined,
        "day",
      );
      expect(within(feed).getAllByText("Anthropic")).toHaveLength(3);
      expect(within(feed).getByText("OpenRouter")).toBeInTheDocument();
      // Titles open the anomaly under the aggregated scope; entity links carry the provider.
      expect(within(feed).getByRole("link", { name: "router-prod" })).toHaveAttribute(
        "href",
        `/anomalies/${fx.openRouterAnomaly.id}`,
      );
      const entityLinks = within(feed)
        .getAllByRole("link", { name: /Open the (key|account)/ })
        .map((link) => link.getAttribute("href"));
      expect(entityLinks).toContain("/keys/orkey_hash_1");
      expect(entityLinks).toContain("/accounts/user_01");
      expect(within(feed).getByRole("link", { name: "Analyze the day" })).toHaveAttribute(
        "href",
        "/explore?by=workspace&measure=billed_usd&from=2026-06-13&to=2026-08-11&interval=day&f=provider%3Ais%3Aanthropic&f=provider_account%3Ais%3A1",
      );
      // The org anomaly's top driver still opens the key page under its provider.
      expect(
        within(feed)
          .getAllByRole("link", { name: "prod-backend" })
          .map((link) => link.getAttribute("href")),
      ).toContain("/keys/apikey_1");
      // Each status form posts to the anomaly's own provider; the bulk bar keeps the scope.
      const form = within(feed)
        .getAllByRole("button", { name: "Acknowledge" })[3]!
        .closest("form")!;
      expect(form.querySelector('input[name="provider"]')).toHaveAttribute("value", "openrouter");
      fireEvent.click(screen.getByRole("checkbox", { name: "Select every open anomaly" }));
      const bar = screen.getByRole("form", { name: "Bulk actions" });
      expect(bar.querySelector('input[name="provider"]')).toHaveAttribute("value", "all");
      expect(bar).toHaveTextContent("4 selected");
    });

    it("words the empty state the same under all", async () => {
      render(await AnomaliesPage({ searchParams: fx.noSearch }));
      expect(screen.getByText(/Anomalies are re-evaluated with every import/)).toBeInTheDocument();
    });
  });

  it("reads the anomalies of the time frame and names its days", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-09-20T12:00:00Z"));
    onTestFinished(() => {
      vi.useRealTimers();
    });
    page.view = {
      org: "default",
      month: "2026-08",
      scope: "anthropic",
      from: "2026-07-20",
      to: "2026-08-14",
    };
    mocked.anomalies.mockResolvedValue(fx.noAnomalies);
    render(await AnomaliesPage({ searchParams: fx.noSearch }));

    expect(mocked.anomalies).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-07-20", to: "2026-08-14" },
      "open",
      undefined,
      "day",
    );
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Anomalies from Jul 20 to Aug 14",
    );
    expect(screen.getByText(/No open anomalies from Jul 20 to Aug 14\./)).toBeInTheDocument();
  });

  it("orders by impact across days when asked", async () => {
    mocked.anomalies.mockResolvedValue(fx.anomalies);
    render(await AnomaliesPage({ searchParams: Promise.resolve({ sort: "impact" }) }));

    expect(mocked.anomalies).toHaveBeenLastCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "open",
      undefined,
      "impact",
    );
    expect(
      screen
        .queryAllByRole("heading", { level: 2 })
        .find((heading) => /Aug 1[0-9]/.test(heading.textContent ?? "")),
    ).toBeUndefined();
    const titles = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(titles[0]).toContain("organization total");
    expect(titles[2]).toContain("experiment");
  });
});

describe("anomaly detail", () => {
  const detailParams = Promise.resolve({ id: "7" });

  it("marks the organization owners as a fallback when the inventory names nobody", async () => {
    const gap =
      "The key's creator id `user_31yQ` is not in the provider's member list, so it maps to no e-mail; the provider lists no administrators for Default Workspace (ws_1).";
    mocked.anomaly.mockResolvedValue({
      ...fx.anomalyDetail,
      owners: [
        { email: "owner@example.com", role: "organization owner", source: "Costura organization" },
      ],
      owners_gap: gap,
    });
    render(await AnomalyPage({ params: detailParams }));

    const contact = screen.getByRole("heading", { level: 2, name: "Who to contact" });
    const card = contact.closest("[data-slot=card]") ?? contact.parentElement!.parentElement!;
    expect(within(card as HTMLElement).getByText(new RegExp(gap.slice(0, 40)))).toHaveTextContent(
      /listed as a fallback; they are not the people behind the spend/,
    );
    expect(within(card as HTMLElement).getByText("fallback")).toBeInTheDocument();
    expect(within(card as HTMLElement).queryByText("organization owner")).not.toBeInTheDocument();
  });

  it("lets a member assign a contact to a key the inventory names nobody for", async () => {
    mocked.anomaly.mockResolvedValue({
      ...fx.anomalyDetail,
      series_kind: "api_key",
      series_id: "apikey_9",
      label: "gateway (apikey_9)",
      owners: [
        { email: "owner@example.com", role: "organization owner", source: "Costura organization" },
      ],
      owners_gap: "Nobody is recorded as its creator.",
    });
    render(await AnomalyPage({ params: detailParams }));

    fireEvent.click(screen.getByRole("button", { name: "Assign a contact" }));
    const email = screen.getByLabelText("Contact e-mail");
    expect(email).toHaveAttribute("type", "email");
    const form = email.closest("form")!;
    expect(form.querySelector('input[name="kind"]')).toHaveAttribute("value", "api_key");
    expect(form.querySelector('input[name="external_id"]')).toHaveAttribute("value", "apikey_9");
    expect(screen.getByRole("button", { name: "Save contact" })).toBeInTheDocument();
  });

  it("shows the assigned contact first with its note and offers to change or remove it", async () => {
    mocked.anomaly.mockResolvedValue({
      ...fx.anomalyDetail,
      series_kind: "api_key",
      series_id: "apikey_9",
      label: "gateway (apikey_9)",
      owners: [
        {
          email: "oncall@example.com",
          role: "assigned in Costura",
          source: "gateway (apikey_9)",
          note: "gateway rotation",
        },
        { email: "owner@example.com", role: "organization owner", source: "Costura organization" },
      ],
      owners_gap: null,
    });
    render(await AnomalyPage({ params: detailParams }));

    expect(screen.getByText(/recorded who answers for this spend/)).toBeInTheDocument();
    expect(screen.getByText("assigned in Costura")).toBeInTheDocument();
    expect(screen.getByText("gateway (apikey_9): gateway rotation")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change the assigned contact" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove" })).toBeInTheDocument();
  });

  it("keeps the assign form away from the sample organization and from login anomalies", async () => {
    render(await AnomalyPage({ params: detailParams }));
    expect(screen.queryByRole("button", { name: "Assign a contact" })).not.toBeInTheDocument();

    mocked.org.mockResolvedValue(fx.demoOrganization);
    mocked.anomaly.mockResolvedValue({
      ...fx.anomalyDetail,
      series_kind: "api_key",
      series_id: "apikey_9",
      label: "gateway (apikey_9)",
    });
    render(await AnomalyPage({ params: detailParams }));
    expect(screen.queryByRole("button", { name: "Assign a contact" })).not.toBeInTheDocument();
  });

  it("names the principals that drove the day inside the contact card of an org anomaly", async () => {
    mocked.anomaly.mockResolvedValue({
      ...fx.anomalyDetail,
      ...fx.orgAnomaly,
      same_day: [
        {
          id: fx.anomaly.id,
          series_kind: "account",
          series_id: "user_01",
          label: "ana@example.com",
          impact: "810.00",
          status: "open",
        },
      ],
    });
    render(await AnomalyPage({ params: detailParams }));

    const contact = screen.getByRole("heading", { level: 2, name: "Who to contact" });
    const card = (contact.closest("[data-slot=card]") ??
      contact.parentElement!.parentElement!) as HTMLElement;
    const drivers = within(card).getByText("Who drove the day").nextElementSibling as HTMLElement;
    // The key was not flagged on its own: its row opens the key page. The login was: its row
    // opens that anomaly.
    expect(within(drivers).getByRole("link", { name: "prod-backend" })).toHaveAttribute(
      "href",
      "/keys/apikey_1",
    );
    expect(within(drivers).getByRole("link", { name: "ana@example.com" })).toHaveAttribute(
      "href",
      `/anomalies/${fx.anomaly.id}`,
    );
    expect(within(drivers).getByText("flagged too")).toBeInTheDocument();
    expect(within(drivers).getByText("+800.00")).toBeInTheDocument();
  });

  it("leads with who to contact, the impact in USD and as a share, the series and the drivers", async () => {
    render(await AnomalyPage({ params: detailParams }));

    // The address names no provider: the row is fetched under `all` and says which it is.
    expect(mocked.anomaly).toHaveBeenCalledWith("default", "all", 7);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("ana@example.com");
    expect(screen.getByText("Claude Code login")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the account" })).toHaveAttribute(
      "href",
      "/accounts/user_01",
    );
    const contact = screen.getByRole("heading", { level: 2, name: "Who to contact" });
    expect(contact).toBeInTheDocument();
    expect(screen.getByText(/made with this person's own Claude Code login/)).toBeInTheDocument();
    const emails = screen.getAllByRole("link", { name: /@example.com$/ }).map((a) => a.textContent);
    expect(emails).toEqual(["ana@example.com", "owner@example.com"]);
    expect(screen.getByRole("button", { name: "Copy ana@example.com" })).toBeInTheDocument();
    expect(screen.getByText("used their own login")).toBeInTheDocument();
    expect(screen.getByText("organization owner")).toBeInTheDocument();
    expect(screen.queryByText("fallback")).not.toBeInTheDocument();

    const figures = screen.getByRole("region", { name: "Headline figures" });
    expect(within(figures).getByText("Impact").nextSibling).toHaveTextContent("+810.00");
    expect(
      within(figures).getByText(/spent above the expected amount on the day; 12.4% of/),
    ).toBeInTheDocument();
    // Severity weighs the money against the swing the series usually has.
    expect(within(figures).getByText("Severity").nextSibling).toHaveTextContent("high");
    expect(within(figures).getByText(/12.9 x the series' usual swing/)).toBeInTheDocument();
    expect(within(figures).getByText("Over the baseline").nextSibling).toHaveTextContent("132.79%");
    expect(screen.getByRole("heading", { name: "What normal looked like" })).toBeInTheDocument();
    fireEvent.click(screen.getByText("Evidence"));
    expect(
      screen.getByRole("table", { name: /eight weeks ending on the episode/ }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("baseline sample").length).toBeGreaterThan(0);

    // The day table opens on the first dimension (models); the same-day list links to the
    // other anomaly.
    expect(screen.getByRole("link", { name: "claude-opus-4-1" })).toHaveAttribute(
      "href",
      "/models/claude-opus-4-1",
    );
    expect(screen.getByRole("link", { name: "organization total" })).toHaveAttribute(
      "href",
      "/anomalies/8",
    );
    expect(screen.getByRole("link", { name: "Open in Analyze" })).toHaveAttribute(
      "href",
      "/explore?by=account&measure=billed_usd&from=2026-06-13&to=2026-08-11&interval=day&f=provider%3Ais%3Aanthropic&f=provider_account%3Ais%3A1&f=account%3Ais%3Auser_01",
    );
    // Writable scope: the status controls; opening the page marks the anomaly read.
    expect(screen.getByRole("button", { name: "Acknowledge" })).toBeInTheDocument();
    await waitFor(() => expect(markReadAction).toHaveBeenCalledWith([7]));
  });

  it("lays out the evidence: checks, baseline samples, the day by dimension, price, data, history", async () => {
    render(await AnomalyPage({ params: detailParams }));
    fireEvent.click(screen.getByText("Evidence"));

    // Every check with its numbers and the rule that fixed the bound.
    expect(
      screen.getByText(
        "8 of 8 checks hold; the margin came from the MAD multiple of the sensitivity.",
      ),
    ).toBeInTheDocument();
    const checks = screen.getByRole("table", { name: "Detection checks" });
    expect(within(checks).getAllByText("holds")).toHaveLength(8);
    const bound = within(checks).getByText("Above the upper bound").closest("tr")!;
    expect(bound).toHaveTextContent("1,420.00");
    expect(bound).toHaveTextContent("890.00");
    expect(within(checks).getByText("At least 12 days of history").closest("tr")).toHaveTextContent(
      "71 days",
    );
    expect(screen.queryByText(/changed after detection/)).not.toBeInTheDocument();

    // The baseline: eight sample days, median, MAD and the winning margin.
    const samples = screen.getByRole("table", { name: "Baseline samples" });
    expect(within(samples).getAllByRole("row")).toHaveLength(9);
    expect(within(samples).getAllByText("Tuesday")).toHaveLength(8);
    expect(screen.getByText("Median absolute deviation (MAD)").nextSibling).toHaveTextContent(
      "62.95",
    );
    expect(screen.getByText("fixed the bound").closest("li")).toHaveTextContent(
      "the MAD multiple of the sensitivity",
    );
    expect(screen.getByText("Upper bound (median + margin)").nextSibling).toHaveTextContent(
      "610.00 + 280.00 = 890.00",
    );
    // The sensitivity behind the margin, the trend carried into the samples, and what each
    // sample day was read as.
    expect(screen.getByText("Sensitivity").nextSibling).toHaveTextContent("normal");
    expect(screen.getByText("Trend carried into the samples").nextSibling).toHaveTextContent(
      "0.00 USD per week",
    );
    expect(
      within(samples)
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual(["day", "amount", "read as"]);

    // The day by dimension: tabs, every row, delta, tokens, price; the new key gets a badge.
    const day = screen.getByRole("table", { name: /Spend on the anomaly day by Model/ });
    expect(within(day).getByText("claude-sonnet-4").closest("tr")).toHaveTextContent("+210.00");
    expect(within(day).getByText("claude-opus-4-1").closest("tr")).toHaveTextContent("20.00");
    fireEvent.mouseDown(screen.getByRole("tab", { name: "API key" }));
    const keys = screen.getByRole("table", { name: /Spend on the anomaly day by API key/ });
    expect(within(keys).getByRole("link", { name: "prod-backend" })).toHaveAttribute(
      "href",
      "/keys/apikey_1",
    );
    expect(within(keys).getByText("migration-script").closest("tr")).toHaveTextContent("new");
    expect(within(keys).getAllByRole("link", { name: "Analyze" })[0]).toHaveAttribute(
      "href",
      "/explore?by=model&f=api_key%3Ais%3Aapikey_1",
    );

    // Volume or price, in one sentence and a table.
    expect(screen.getByText(/^Price moved most: 2\.1 x/)).toBeInTheDocument();
    const price = screen.getByRole("table", { name: "Volume or price" });
    expect(within(price).getByText("Tokens").closest("tr")).toHaveTextContent("203,000,000");
    expect(within(price).getByText("Token mix").closest("tr")).toHaveTextContent(
      "94% input, 6% output",
    );

    // The data behind the day and the series' history.
    expect(screen.getByRole("link", { name: "Costs" })).toHaveAttribute(
      "href",
      "/runs?endpoint=cost_report",
    );
    expect(screen.getByText("usage lines").nextSibling).toHaveTextContent("48");
    // The link switches the view to the anomaly's own provider and month on the way.
    expect(screen.getByRole("link", { name: "Reconcile the month" })).toHaveAttribute(
      "href",
      "/o/default?scope=anthropic&month=2026-08&next=%2Freconcile",
    );
    expect(screen.getByRole("link", { name: "Thursday, Jul 2" })).toHaveAttribute(
      "href",
      "/anomalies/3",
    );
  });

  it("says when the day's data changed after detection and which checks fail now", async () => {
    const baseline = fx.anomalyEvidence.baseline!;
    mocked.anomaly.mockResolvedValue({
      ...fx.anomalyDetail,
      evidence: {
        ...fx.anomalyEvidence,
        baseline: { ...baseline, actual_now: "700.00", matches_stored: false },
        checks: fx.anomalyEvidence.checks.map((check) =>
          check.name === "above_upper_bound"
            ? { ...check, passed: false, observed: "700.00" }
            : check,
        ),
        data_quality: { ...fx.anomalyEvidence.data_quality, changed_since_detection: true },
        history: [],
      },
    });
    render(await AnomalyPage({ params: detailParams }));
    fireEvent.click(screen.getByText("Evidence"));

    expect(
      screen.getByText("The day's data changed after detection: spent 1,420.00, now 700.00."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/7 of 8 checks hold with today's data; failing: above the upper bound/),
    ).toBeInTheDocument();
    expect(screen.getByText("fails").closest("tr")).toHaveTextContent("within upper bound");
    expect(
      screen.getByText(/A cost or usage sync finished after this anomaly/),
    ).toBeInTheDocument();
    expect(screen.getByText("First anomaly of this series.")).toBeInTheDocument();
  });

  it("hides the status controls and the read mark on the sample organization and 404s on an unknown id", async () => {
    mocked.org.mockResolvedValue(fx.demoOrganization);
    render(await AnomalyPage({ params: detailParams }));
    expect(screen.queryByRole("button", { name: "Acknowledge" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Who to contact" })).toBeInTheDocument();
    expect(markReadAction).not.toHaveBeenCalled();
    cleanup();

    mocked.org.mockResolvedValue(fx.organization);
    mocked.anomaly.mockRejectedValue(new ApiError(404, "/anomalies/7", "anomaly not found"));
    await expect(AnomalyPage({ params: detailParams })).rejects.toThrow("NEXT_NOT_FOUND");
    await expect(AnomalyPage({ params: Promise.resolve({ id: "seven" }) })).rejects.toThrow(
      "NEXT_NOT_FOUND",
    );
  });

  it("lists nobody gracefully when the inventory and the organization name no one", async () => {
    mocked.anomaly.mockResolvedValue({ ...fx.anomalyDetail, owners: [], same_day: [] });
    render(await AnomalyPage({ params: detailParams }));
    expect(screen.getByText(/names nobody for this series/)).toBeInTheDocument();
    expect(screen.getByText("No other anomaly that day.")).toBeInTheDocument();
  });
});
