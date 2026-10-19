/** The app shell: scope layout, the home redirect and the settings redirect. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { automaticSyncLine } from "@/components/data-freshness";
import * as fx from "@/test/fixtures";
import { ApiError } from "@/lib/api";
import ScopeLayout from "./(app)/layout";
import HomePage from "./page";
import SettingsRedirect from "./(app)/settings/page";
import { getSetupAction, startSyncAction } from "@/actions/welcome";
import {
  DEMO_VIEW,
  page,
  push,
  refresh,
  setViewAction,
  withPageDefaults,
  type MockedApi,
} from "@/test/page-harness";

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

describe("scope layout", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-09-14T12:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows the scope bar, the freshness pill and the grouped sidebar", async () => {
    render(await ScopeLayout({ children: <p>child</p> }));

    // The organization is not a scope control any more: it lives in the footer menu.
    expect(screen.queryByRole("combobox", { name: "Organization" })).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Provider" })).toHaveTextContent("Anthropic");
    expect(screen.getByRole("button", { name: "Time frame" })).toHaveTextContent("Last month");
    expect(screen.getByRole("combobox", { name: "Interval" })).toHaveTextContent("Daily");
    expect(screen.getByRole("button", { name: "Search resources" })).toHaveAttribute(
      "aria-keyshortcuts",
      "Control+K Meta+K",
    );

    const nav = screen.getByRole("navigation", { name: "Sections" });
    expect(
      within(nav)
        .getAllByRole("link")
        .map((a) => a.textContent),
    ).toEqual(["Overview", "Analyze", "Anomalies", "Budgets", "Reconciliation"]);
    expect(within(nav).getAllByText(/^(Guardrails|Data health)$/)).toHaveLength(1);
    expect(within(nav).getByRole("link", { name: "Overview" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    // Narrow viewports get a bottom tab row with one page per group plus Explore; the open
    // anomaly count follows.
    const tabs = screen.getByRole("navigation", { name: "Quick sections" });
    expect(
      within(tabs)
        .getAllByRole("link")
        .map((a) => a.getAttribute("href")),
    ).toEqual(["/overview", "/explore", "/anomalies", "/reconcile"]);
    expect(within(tabs).getByRole("link", { name: /Overview/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Analyze" })).toHaveAttribute("href", "/explore");
    expect(mocked.anomalies).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "open",
      undefined,
      "severity",
    );
    expect(mocked.runs).toHaveBeenCalledWith("default", "anthropic", 50);
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute(
      "href",
      "/settings/connections",
    );
    expect(screen.getByRole("button", { name: "Open navigation" })).toBeInTheDocument();
    expect(screen.getByText("child")).toBeInTheDocument();
  });

  it("offers the anomaly alerts bell to a signed-in member, with the opt-in before any list", async () => {
    render(await ScopeLayout({ children: null }));

    expect(mocked.alerts).toHaveBeenCalledWith("default");
    const bell = screen.getByRole("button", { name: "Alerts" });
    expect(bell).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(bell);
    const dialog = screen.getByRole("dialog", { name: "Alerts" });
    expect(within(dialog).getByText(/Get notified about new anomalies/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Turn alerts on" })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("counts the unread anomalies on the bell and lists them with impact, owner and link", async () => {
    mocked.alerts.mockResolvedValue(fx.alerts);
    render(await ScopeLayout({ children: null }));

    const bell = screen.getByRole("button", { name: "Alerts, 2 unread" });
    fireEvent.click(bell);
    const dialog = screen.getByRole("dialog", { name: "Alerts" });
    expect(within(dialog).getByText("2 unread: 2 anomalies")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Mark all read" })).toBeInTheDocument();
    // The read one (experiment) is not listed; the unread ones link to their detail pages.
    expect(within(dialog).queryByRole("link", { name: "experiment" })).not.toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "organization total" })).toHaveAttribute(
      "href",
      "/anomalies/8",
    );
    // The login anomaly is titled with the user; the bell says how the spend reached the
    // provider and the org anomaly names the key creator as the contact.
    expect(
      within(dialog)
        .getAllByRole("link", { name: "ana@example.com" })
        .map((link) => link.getAttribute("href")),
    ).toContain("/anomalies/7");
    expect(within(dialog).getByText("Claude Code login")).toBeInTheDocument();
    expect(within(dialog).getAllByText("+900.00")).toHaveLength(1);
    expect(within(dialog).getByRole("link", { name: "bruno@example.com" })).toHaveAttribute(
      "href",
      "mailto:bruno@example.com",
    );
    expect(within(dialog).getByRole("link", { name: "All anomalies" })).toHaveAttribute(
      "href",
      "/anomalies",
    );
  });

  it("shows no bell on the sample organization even when signed in", async () => {
    page.view = { org: "demo", month: "2026-08", scope: "anthropic" };
    page.pathname = "/overview";
    page.view = { ...DEMO_VIEW, scope: "anthropic" };
    mocked.org.mockResolvedValue(fx.demoOrganization);
    render(await ScopeLayout({ children: null }));
    expect(mocked.alerts).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /^Alerts/ })).not.toBeInTheDocument();
  });

  it("renders equivalent labelled scope selectors in the mobile navigation", async () => {
    render(await ScopeLayout({ children: null }));
    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));

    const sheet = screen.getByRole("dialog", { name: "Navigation" });
    expect(within(sheet).getByRole("combobox", { name: "Provider" })).toHaveTextContent(
      "Anthropic",
    );
    expect(within(sheet).getByText("Provider")).toBeVisible();
  });

  it("collapses the sidebar to icons and remembers it", async () => {
    render(await ScopeLayout({ children: null }));
    const aside = screen.getByRole("complementary", { name: "Sidebar" });
    expect(aside).not.toHaveAttribute("data-collapsed");

    fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));

    expect(aside).toHaveAttribute("data-collapsed", "true");
    expect(window.localStorage.getItem("costura.sidebar.collapsed")).toBe("1");
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Expand sidebar" }));
    expect(window.localStorage.getItem("costura.sidebar.collapsed")).toBe("0");
  });

  it("highlights the list an entity page was reached from", async () => {
    page.segment = "keys";
    render(await ScopeLayout({ children: null }));
    const nav = screen.getByRole("navigation", { name: "Sections" });
    expect(within(nav).getByRole("link", { name: "Analyze" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
  });

  it("lists the user's organizations in the footer menu with the active one checked", async () => {
    page.view = { org: "default", month: "2026-08", scope: "anthropic" };
    page.pathname = "/explore";
    mocked.me.mockResolvedValue({
      ...fx.me,
      organizations: [fx.organization, { ...fx.organization, slug: "acme", name: "Acme" }],
      invitations: [fx.invitations[0]],
    });
    render(await ScopeLayout({ children: null }));
    // No organization select in the scope bar: the organization lives in the session.
    expect(screen.queryByRole("combobox", { name: "Organization" })).not.toBeInTheDocument();
    const trigger = screen.getByRole("button", { name: "Account menu" });
    expect(trigger).toHaveTextContent("Default organization");
    expect(trigger).toHaveTextContent("Owner - Default organization");

    fireEvent.keyDown(trigger, { key: "Enter" });
    const menu = await screen.findByRole("menu");
    expect(within(menu).getByText("owner@example.com")).toBeInTheDocument();
    const items = within(menu).getAllByRole("menuitem");
    expect(items.map((item) => item.textContent)).toEqual([
      "Default organizationOwner",
      "AcmeOwner",
      "New organization",
      "Invitations1",
      "Organization settings",
      "Log out",
    ]);
    expect(within(menu).getByRole("menuitem", { name: /Default organization/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
    // Switching posts the slug and the current page, so the reader stays where they were.
    const acme = within(menu).getByRole("menuitem", { name: /Acme/ }).closest("form")!;
    expect(acme.querySelector('input[name="slug"]')).toHaveAttribute("value", "acme");
    expect(acme.querySelector('input[name="next"]')).toHaveAttribute("value", "/explore");
    expect(within(menu).getByRole("menuitem", { name: "New organization" })).toHaveAttribute(
      "href",
      "/new",
    );
    expect(within(menu).getByRole("menuitem", { name: /Invitations/ })).toHaveAttribute(
      "href",
      "/join",
    );
    expect(within(menu).getByRole("menuitem", { name: "Organization settings" })).toHaveAttribute(
      "href",
      "/settings/organization",
    );
  });

  it("keeps the shell up when the runs or anomalies call fails", async () => {
    mocked.runs.mockRejectedValue(new Error("boom"));
    mocked.anomalies.mockRejectedValue(new Error("boom"));
    render(await ScopeLayout({ children: <p>child</p> }));
    expect(screen.getByText("child")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Data freshness:/ })).toHaveTextContent(
      "No data synced yet",
    );
  });

  it("sends the freshness drawer to the welcome page before the first run", async () => {
    mocked.runs.mockResolvedValue({ runs: [] });
    render(await ScopeLayout({ children: null }));
    fireEvent.click(screen.getByRole("button", { name: /^Data freshness:/ }));
    const panel = screen.getByRole("dialog");
    expect(within(panel).getByText(/No runs recorded/)).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "Connect a provider" })).toHaveAttribute(
      "href",
      "/welcome",
    );
    expect(
      within(panel).getByText(/The first import starts when a provider is connected/),
    ).toBeInTheDocument();
    cleanup();

    // Without writes the sentence stays and the link goes: nothing to connect from here.
    mocked.connection.mockResolvedValue({ ...fx.connection, writes_enabled: false });
    render(await ScopeLayout({ children: null }));
    fireEvent.click(screen.getByRole("button", { name: /^Data freshness:/ }));
    const readOnly = screen.getByRole("dialog");
    expect(
      within(readOnly).getByText(/The first import starts when a provider is connected/),
    ).toBeInTheDocument();
    expect(
      within(readOnly).queryByRole("link", { name: "Connect a provider" }),
    ).not.toBeInTheDocument();
  });

  it("shows a month without dates as that month's range without navigating", async () => {
    page.view = { org: "default", month: "2026-08", scope: "anthropic" };
    page.pathname = "/explore";
    page.searchParams = new URLSearchParams({ by: "model", api_key: "apikey_1" });
    render(await ScopeLayout({ children: null }));

    expect(screen.getByRole("button", { name: "Time frame" })).toHaveTextContent("Last month");
    expect(screen.getByRole("combobox", { name: "Interval" })).toHaveTextContent("Daily");
    expect(setViewAction).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
  });

  it("shows the open anomaly count on the Anomalies item", async () => {
    mocked.anomalies.mockResolvedValue(fx.anomalies);
    render(await ScopeLayout({ children: null }));

    const nav = screen.getByRole("navigation", { name: "Sections" });
    const tab = within(nav).getByRole("link", { name: /Anomalies/ });
    expect(within(tab).getByLabelText("3 open")).toHaveTextContent("3");
    expect(tab).toHaveAttribute("href", "/anomalies");
  });

  it("keeps the open anomaly count when the time frame holds none of them", async () => {
    mocked.anomalies.mockResolvedValue({ ...fx.noAnomalies, open_total: 4 });
    render(await ScopeLayout({ children: null }));

    const nav = screen.getByRole("navigation", { name: "Sections" });
    const tab = within(nav).getByRole("link", { name: /Anomalies/ });
    expect(within(tab).getByLabelText("4 open")).toHaveTextContent("4");
  });

  it("summarises the runs in the freshness pill", async () => {
    render(await ScopeLayout({ children: null }));
    const pill = screen.getByRole("button", { name: /^Data freshness:/ });
    // No succeeded cost_report run in the fixture: nothing to date the data by.
    expect(pill).toHaveTextContent("No data synced yet");
    expect(pill).toHaveTextContent("1 failed job");
  });

  it.each(["cost_report", "costs", "filtered_usage_events"])(
    "dates the data by the newest succeeded cost sync (%s)",
    async (endpoint) => {
      mocked.runs.mockResolvedValue({
        runs: [{ ...fx.runs[0], id: 12, endpoint }, ...fx.runs],
      });
      render(await ScopeLayout({ children: null }));
      expect(screen.getByRole("button", { name: /^Data freshness:/ })).toHaveTextContent(
        "Data as of 2026-09-14 12:00",
      );
    },
  );

  it("words the automatic sync line from the schedule", () => {
    expect(automaticSyncLine(fx.connection.schedule)).toBe("Automatic sync: 2026-09-14 06:02 ok");
    expect(automaticSyncLine({ ...fx.connection.schedule, status: "failed" })).toBe(
      "Automatic sync: 2026-09-14 06:02 failed",
    );
    expect(automaticSyncLine(fx.notConnected.schedule)).toBe("Automatic sync: never");
    expect(automaticSyncLine(undefined)).toBe("Automatic sync: never");
  });

  describe("sync banner", () => {
    const banner = () => screen.getByRole("region", { name: "Import progress" });

    it("stays hidden on a ready organization with no run in progress", async () => {
      render(await ScopeLayout({ children: <p>child</p> }));
      expect(mocked.setup).toHaveBeenCalledWith("default");
      expect(screen.queryByRole("region", { name: "Import progress" })).not.toBeInTheDocument();
      expect(screen.queryByText(/First data is in/)).not.toBeInTheDocument();
      expect(screen.queryByRole("note")).not.toBeInTheDocument();
    });

    it("follows the running first import with a pill and the steps behind a toggle", async () => {
      mocked.setup.mockResolvedValue(fx.setupSyncing);
      render(await ScopeLayout({ children: <p>child</p> }));

      const region = banner();
      expect(within(region).getByText("Anthropic")).toBeInTheDocument();
      expect(within(region).getByText("Importing")).toBeInTheDocument();
      expect(within(region).getByText(/Importing costs, usage and inventory/)).toBeInTheDocument();
      const toggle = within(region).getByText("Show steps");
      expect(toggle.closest("details")).toHaveProperty("open", false);
      const table = within(region).getByRole("table", { name: "Anthropic steps" });
      expect(within(table).getByText("3 workspaces, 12 keys, 4 users")).toBeInTheDocument();
      expect(within(table).getByText(/Still importing/)).toBeInTheDocument();
      // The provider without a key has no row.
      expect(within(region).queryByText("OpenRouter")).not.toBeInTheDocument();
      expect(within(region).queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
      expect(screen.getByText("child")).toBeInTheDocument();
    });

    it("offers Retry after a failed first run and starts the sync again", async () => {
      mocked.setup.mockResolvedValue(fx.setupSyncingFailed);
      vi.mocked(startSyncAction).mockResolvedValue({ ok: true, message: "Sync started." });
      vi.mocked(getSetupAction).mockResolvedValue({ setup: fx.setupSyncing, error: null });
      render(await ScopeLayout({ children: null }));

      const region = banner();
      expect(within(region).getByText("Failed")).toBeInTheDocument();
      expect(within(region).getByText(/The import failed/)).toBeInTheDocument();
      expect(within(region).getByText("Anthropic request failed: status=429")).toBeInTheDocument();
      expect(within(region).getByText("1 of 2 steps failed")).toBeInTheDocument();

      fireEvent.click(within(region).getByRole("button", { name: "Retry" }));

      await waitFor(() => expect(startSyncAction).toHaveBeenCalledWith("default", "anthropic"));
      await waitFor(() => expect(getSetupAction).toHaveBeenCalledWith("default"));
      expect(await within(banner()).findByText("Importing")).toBeInTheDocument();
    });

    it("hides Retry when the API refuses writes", async () => {
      mocked.setup.mockResolvedValue({ ...fx.setupSyncingFailed, writes_enabled: false });
      render(await ScopeLayout({ children: null }));
      expect(within(banner()).getByText("Failed")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    });

    it("flips to the first-data link when a poll sees the organization become ready", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        mocked.setup.mockResolvedValue(fx.setupSyncing);
        vi.mocked(getSetupAction).mockResolvedValue({ setup: fx.setupReady, error: null });
        render(await ScopeLayout({ children: <p>child</p> }));
        expect(banner()).toBeInTheDocument();

        await act(async () => {
          await vi.advanceTimersByTimeAsync(2100);
        });

        expect(getSetupAction).toHaveBeenCalledWith("default");
        expect(screen.queryByRole("region", { name: "Import progress" })).not.toBeInTheDocument();
        const status = screen.getByRole("status");
        expect(status).toHaveTextContent("First data is in - open August 2026");
        expect(within(status).getByRole("link", { name: "open August 2026" })).toHaveAttribute(
          "href",
          "/o/default?month=2026-08&next=%2Foverview",
        );
        // The page under the band was rendered before the data landed.
        expect(refresh).toHaveBeenCalled();

        fireEvent.click(within(status).getByRole("button", { name: "Dismiss" }));
        expect(screen.queryByRole("status")).not.toBeInTheDocument();
      } finally {
        vi.useRealTimers();
      }
    });

    it("follows a second provider's run on a ready organization and lets go when it ends", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        const secondProvider = {
          ...fx.setupReady,
          runs: [fx.succeededRun, { ...fx.runningRun, id: 40, provider: "openrouter" }],
        };
        mocked.setup.mockResolvedValue(secondProvider);
        vi.mocked(getSetupAction).mockResolvedValue({ setup: fx.setupReady, error: null });
        render(await ScopeLayout({ children: null }));

        // Only the provider still importing has a row; Anthropic is done.
        const region = banner();
        expect(within(region).getByText("OpenRouter")).toBeInTheDocument();
        expect(within(region).queryByText("Anthropic")).not.toBeInTheDocument();

        await act(async () => {
          await vi.advanceTimersByTimeAsync(2100);
        });

        // Ready before and after: no flip, the band goes and the page reloads its data.
        expect(screen.queryByRole("region", { name: "Import progress" })).not.toBeInTheDocument();
        expect(screen.queryByText(/First data is in/)).not.toBeInTheDocument();
        expect(refresh).toHaveBeenCalled();
      } finally {
        vi.useRealTimers();
      }
    });

    it("keeps the shell up when the setup call fails", async () => {
      mocked.setup.mockRejectedValue(new Error("boom"));
      render(await ScopeLayout({ children: <p>child</p> }));
      expect(screen.getByText("child")).toBeInTheDocument();
      expect(screen.queryByRole("region", { name: "Import progress" })).not.toBeInTheDocument();
    });
  });

  describe("sample organization", () => {
    beforeEach(() => {
      page.view = DEMO_VIEW;
    });

    it("shows the sample-data band linking to the user's own welcome page", async () => {
      page.view = { org: "demo", month: "2026-08", scope: "all" };
      page.pathname = "/overview";
      mocked.setup.mockResolvedValue({ ...fx.setupReady, dismissed_at: "2026-09-14T00:00:00Z" });
      render(await ScopeLayout({ children: <p>child</p> }));

      const note = screen.getByRole("region", { name: "Sample organization" });
      expect(note).toHaveTextContent("is a fictional company: every figure is synthetic");
      // The link opens the user's own organization first, since the view is the sample one.
      expect(
        within(note).getByRole("link", { name: "Connect a provider in your organization" }),
      ).toHaveAttribute("href", "/o/default?next=%2Fwelcome");
      expect(screen.queryByRole("region", { name: "Import progress" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Account menu" })).toHaveTextContent(
        "Sample organization",
      );
      expect(within(note).queryByRole("button")).not.toBeInTheDocument();
    });

    it("renders read-only for a visitor without a session and never asks who they are", async () => {
      page.view = { org: "demo", month: "2026-08", scope: "all" };
      page.pathname = "/overview";
      page.sessionToken = null;
      mocked.org.mockResolvedValue(fx.demoOrganization);
      mocked.setup.mockResolvedValue({ ...fx.setupReady, dismissed_at: "2026-09-14T00:00:00Z" });
      render(await ScopeLayout({ children: <p>child</p> }));

      expect(mocked.org).toHaveBeenCalledWith("demo");
      expect(mocked.me).not.toHaveBeenCalled();
      expect(mocked.alerts).not.toHaveBeenCalled();
      expect(screen.queryByRole("button", { name: /^Alerts/ })).not.toBeInTheDocument();
      expect(screen.getByText("child")).toBeInTheDocument();
      const note = screen.getByRole("region", { name: "Sample organization" });
      expect(within(note).getByRole("link", { name: "Sign in to connect yours" })).toHaveAttribute(
        "href",
        "/sign-in",
      );
      const aside = screen.getByRole("complementary", { name: "Sidebar" });
      expect(within(aside).getByRole("link", { name: "Sign in" })).toHaveAttribute(
        "href",
        "/sign-in",
      );
      expect(within(aside).queryByRole("button", { name: "Account menu" })).not.toBeInTheDocument();
      expect(within(aside).queryByText("Default")).not.toBeInTheDocument();
    });

    it("sends a user without an organization to the organization form", async () => {
      page.view = { org: "demo", month: "2026-08", scope: "all" };
      page.pathname = "/overview";
      mocked.me.mockResolvedValue({ ...fx.me, organizations: [fx.demoOrganization] });
      render(await ScopeLayout({ children: null }));
      expect(screen.getByRole("link", { name: "Create your organization" })).toHaveAttribute(
        "href",
        "/new",
      );
      cleanup();

      mocked.me.mockRejectedValue(new Error("boom"));
      render(await ScopeLayout({ children: null }));
      expect(screen.getByRole("link", { name: "Create your organization" })).toHaveAttribute(
        "href",
        "/new",
      );
    });
  });

  it("falls back to the newest month with data when the cookie names one without", async () => {
    page.view = { org: "default", month: "2026-05", scope: "anthropic" };
    render(await ScopeLayout({ children: null }));
    expect(mocked.runs).toHaveBeenCalledWith("default", "anthropic", 50);
    expect(screen.getByRole("button", { name: "Time frame" })).toHaveTextContent("Last month");
  });

  it("falls back to all providers when the cookie names an unknown scope", async () => {
    page.view = { org: "default", month: "2026-08", scope: "bedrock" };
    render(await ScopeLayout({ children: null }));
    expect(mocked.months).toHaveBeenCalledWith("default", "all");
    expect(screen.getByRole("combobox", { name: "Provider" })).toHaveTextContent("All providers");
  });

  it("goes back to / without a view cookie or with an organization the API does not know", async () => {
    page.view = null;
    await expect(ScopeLayout({ children: null })).rejects.toThrow("NEXT_REDIRECT /");

    page.view = { org: "nope", month: "2026-08", scope: "anthropic" };
    mocked.months.mockRejectedValue(
      new ApiError(404, "/orgs/nope/providers/anthropic/months", "organization not found"),
    );
    await expect(ScopeLayout({ children: null })).rejects.toThrow("NEXT_REDIRECT /");
  });

  it("reads one connection per provider under all and names the scope in the bar", async () => {
    page.view = { ...page.view!, scope: "all" };
    page.view = { org: "default", month: "2026-08", scope: "all" };
    page.pathname = "/overview";
    mocked.connection.mockImplementation((_org: string, provider: string) =>
      Promise.resolve(provider === "openrouter" ? fx.openRouterConnection : fx.connection),
    );
    mocked.runs.mockResolvedValue({ runs: [fx.openRouterRun, ...fx.runs] });
    render(await ScopeLayout({ children: <p>child</p> }));

    expect(mocked.providers).toHaveBeenCalledWith("default");
    expect(mocked.connection).toHaveBeenCalledWith("default", "anthropic");
    expect(mocked.connection).toHaveBeenCalledWith("default", "openrouter");
    expect(mocked.connection).not.toHaveBeenCalledWith("default", "all");
    expect(mocked.months).toHaveBeenCalledWith("default", "all");
    expect(mocked.runs).toHaveBeenCalledWith("default", "all", 50);
    expect(screen.getByRole("combobox", { name: "Provider" })).toHaveTextContent("All providers");
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute(
      "href",
      "/settings/connections",
    );
    // The freshness pill dates the data by the newest succeeded cost sync of any provider.
    expect(screen.getByRole("button", { name: /^Data freshness:/ })).toHaveTextContent(
      "Data as of 2026-09-14 13:00",
    );
    // The newest scheduler run (OpenRouter, 06:10, failed) words the automatic sync line.
    fireEvent.click(screen.getByRole("button", { name: /^Data freshness:/ }));
    expect(screen.getByText(/Automatic sync: 2026-09-14 06:10 failed/)).toBeInTheDocument();
    // The latest-run panel keeps one row per provider and job and names the provider.
    const panel = screen.getByRole("dialog");
    expect(within(panel).getByRole("columnheader", { name: "provider" })).toBeInTheDocument();
    expect(within(panel).getByText("OpenRouter")).toBeInTheDocument();
  });
});

describe("/settings", () => {
  it("redirects to the connections section", async () => {
    await expect(SettingsRedirect()).rejects.toThrow("NEXT_REDIRECT /settings/connections");
  });
});

describe("/", () => {
  it("lands on the overview of the remembered organization", async () => {
    await expect(HomePage()).rejects.toThrow("NEXT_REDIRECT /overview");
    expect(mocked.setup).toHaveBeenCalledWith("default");
  });

  it("opens the first owned organization through /o when nothing is remembered", async () => {
    page.view = null;
    await expect(HomePage()).rejects.toThrow("NEXT_REDIRECT /o/default?next=%2Foverview");
  });

  it("forgets a remembered organization the caller is no longer a member of", async () => {
    page.view = { org: "acme", month: null, scope: null };
    await expect(HomePage()).rejects.toThrow("NEXT_REDIRECT /o/default?next=%2Foverview");
  });

  it("sends a signed-out visitor to sign in, an invitee to /join and the rest to /new", async () => {
    page.sessionToken = null;
    await expect(HomePage()).rejects.toThrow("NEXT_REDIRECT /sign-in");
    page.sessionToken = "tok-1";
    page.view = null;
    mocked.me.mockResolvedValue({ ...fx.me, organizations: [], invitations: [fx.invitations[0]] });
    await expect(HomePage()).rejects.toThrow("NEXT_REDIRECT /join");
    mocked.me.mockResolvedValue({ ...fx.me, organizations: [], invitations: [] });
    await expect(HomePage()).rejects.toThrow("NEXT_REDIRECT /new");
  });
});
