/** Settings pages: shell, connections, sync, members, organization, account and advanced. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import * as fx from "@/test/fixtures";
import AccountSettingsPage from "./(app)/settings/account/page";
import AdvancedSettingsPage from "./(app)/settings/advanced/page";
import ConnectionsSettingsPage from "./(app)/settings/connections/page";
import SettingsLayout from "./(app)/settings/layout";
import MembersSettingsPage from "./(app)/settings/members/page";
import TeamsSettingsPage from "./(app)/settings/teams/page";
import OrganizationSettingsPage from "./(app)/settings/organization/page";
import AnomalySettingsPage from "./(app)/settings/anomalies/page";
import AuditSettingsPage from "./(app)/settings/audit/page";
import SettingsIndex from "./(app)/settings/page";
import SampleSettingsPage from "./(app)/settings/sample/page";
import SyncSettingsPage from "./(app)/settings/sync/page";
import { getSetupAction } from "@/actions/welcome";
import {
  disconnectAction,
  removeAccountAction,
  renameAccountAction,
  syncNowAction,
} from "./(app)/settings/connection-actions";
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
    h.stubs(
      "leaveOrganizationAction",
      "renameOrganizationAction",
      "saveAnomalySettingsAction",
      "deleteOrganizationAction",
    ),
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

/** Settings prints relative times; a fixed "now" makes them assertable. */
const NOW = new Date("2026-09-14T12:00:00Z");

function freezeNow() {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(NOW);
    page.segment = "connections";
  });
  afterEach(() => {
    vi.useRealTimers();
  });
}

describe("settings shell", () => {
  freezeNow();

  it("groups the sections by scope and marks the one being read", async () => {
    render(await SettingsLayout({ children: <p>section body</p> }));

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Settings");
    const nav = screen.getByRole("navigation", { name: "Settings sections" });
    expect(
      within(nav)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual([
      "Organization",
      "Connections",
      "Sync",
      "Anomalies",
      "Members",
      "Teams",
      "Audit",
      "Advanced",
      "Account",
    ]);
    expect(within(nav).getByRole("link", { name: "Organization" })).toHaveAttribute(
      "href",
      "/settings/organization",
    );
    expect(within(nav).getByText("You")).toBeInTheDocument();
    const connections = within(nav).getByRole("link", { name: "Connections" });
    expect(connections).toHaveAttribute("href", "/settings/connections");
    expect(connections).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Account" })).toHaveAttribute(
      "href",
      "/settings/account",
    );
    expect(within(nav).getByRole("link", { name: "Sync" })).not.toHaveAttribute("aria-current");
    expect(screen.getByText("section body")).toBeInTheDocument();
    // The page title is the only heading the shell adds; the sections bring their own cards.
    expect(screen.queryAllByRole("heading", { level: 2 })).toHaveLength(0);
  });

  it("marks the section holding a rejected key or a failed import", async () => {
    mocked.connection.mockResolvedValue({
      ...fx.connection,
      last_error: "Anthropic rejected the key (HTTP 401).",
      schedule: { ...fx.connection.schedule, status: "failed" },
    });
    render(await SettingsLayout({ children: null }));

    const nav = screen.getByRole("navigation", { name: "Settings sections" });
    expect(
      within(nav)
        .getAllByRole("link")
        .map((link) => link.getAttribute("aria-label")),
    ).toEqual([
      null,
      "Connections, needs attention",
      "Sync, needs attention",
      null,
      null,
      null,
      null,
      null,
      null,
    ]);
  });

  it("lists the audit trail for an owner and pages through it", async () => {
    mocked.audit.mockResolvedValue({
      events: [
        {
          id: 3,
          event: "provider_key_connected",
          actor_email: "owner@example.com",
          target: "anthropic:1",
          request_id: "req-1",
          details: { provider: "anthropic" },
          created_at: "2026-10-15T08:00:00Z",
        },
      ],
      total: 120,
      limit: 50,
      offset: 50,
    });
    render(await AuditSettingsPage({ searchParams: Promise.resolve({ page: "2" }) }));
    expect(mocked.audit).toHaveBeenCalledWith("default", 50, 50);
    const row = screen.getByRole("row", { name: /provider key connected/ });
    expect(row).toHaveTextContent("owner@example.com");
    expect(row).toHaveTextContent("anthropic:1");
    expect(row).toHaveTextContent("request req-1");
    expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Older" })).toHaveAttribute(
      "href",
      "/settings/audit?page=3",
    );
    cleanup();

    mocked.org.mockResolvedValue({ ...fx.organization, role: "member" });
    await expect(AuditSettingsPage({ searchParams: Promise.resolve({}) })).rejects.toThrow(
      "NEXT_NOT_FOUND",
    );
  });

  it("leaves out the sections a caller cannot act in", async () => {
    mocked.org.mockResolvedValue({ ...fx.organization, role: "member" });
    render(await SettingsLayout({ children: null }));

    let nav = screen.getByRole("navigation", { name: "Settings sections" });
    expect(within(nav).queryByRole("link", { name: "Advanced" })).not.toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "Audit" })).not.toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Account" })).toBeInTheDocument();
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
    cleanup();

    // The sample organization is public and has no members, so nothing personal is kept there.
    mocked.org.mockResolvedValue({ ...fx.organization, is_demo: true, role: null });
    render(await SettingsLayout({ children: null }));
    nav = screen.getByRole("navigation", { name: "Settings sections" });
    expect(
      within(nav)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual(["How it is configured", "Connections", "Sync", "Anomalies"]);
    expect(screen.getByRole("note")).toHaveTextContent(/This is the sample organization/);
  });

  it("says once, above the sections, when the instance refuses browser writes", async () => {
    mocked.connection.mockResolvedValue({ ...fx.connection, writes_enabled: false });
    render(await SettingsLayout({ children: null }));

    expect(screen.getByRole("note")).toHaveTextContent(
      "This Costura instance does not accept changes from the browser: connecting a key, Sync now and reset are turned off here.",
    );
  });

  it("sends the section-less address to Connections, or the sample to its configuration", async () => {
    await expect(SettingsIndex()).rejects.toThrow("NEXT_REDIRECT /settings/connections");
    mocked.org.mockResolvedValue({ ...fx.organization, is_demo: true, role: null });
    await expect(SettingsIndex()).rejects.toThrow("NEXT_REDIRECT /settings/sample");
  });

  it("reads the anomaly settings, and says the sample keeps the defaults", async () => {
    render(await AnomalySettingsPage());
    expect(screen.getByRole("heading", { name: "Anomaly detection" })).toBeInTheDocument();
    expect(screen.queryByText(/The sample keeps the defaults/)).not.toBeInTheDocument();
    cleanup();
    mocked.webhook.mockClear();
    mocked.org.mockResolvedValue({ ...fx.organization, is_demo: true, role: null });
    render(await AnomalySettingsPage());
    expect(screen.getByText(/The sample keeps the defaults/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Save/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Slack webhook" })).not.toBeInTheDocument();
    expect(mocked.webhook).not.toHaveBeenCalled();
  });

  it("says outbound webhooks are off until the operator allows a host", async () => {
    render(await AnomalySettingsPage());
    expect(screen.getByRole("heading", { name: "Slack webhook" })).toBeInTheDocument();
    expect(screen.getByText(/Outbound webhooks are off on this stack/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Webhook URL")).not.toBeInTheDocument();
  });

  it("shows the saved host, its deliveries and the owner's controls, never the URL", async () => {
    mocked.webhook.mockResolvedValue(fx.webhookSaved);
    render(await AnomalySettingsPage());
    expect(screen.getByText("hooks.slack.com")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Recent deliveries" });
    expect(within(table).getByText("sent")).toBeInTheDocument();
    expect(within(table).getByText("HTTP 503, 2 attempts")).toBeInTheDocument();
    expect(within(table).getByText("no owner")).toBeInTheDocument();
    expect(screen.getByLabelText("Replace the webhook URL")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Send a test message" })).toBeInTheDocument();

    cleanup();
    mocked.webhook.mockRejectedValue(new Error("down"));
    render(await AnomalySettingsPage());
    expect(screen.getByText("Could not load the webhook; reload to retry.")).toBeInTheDocument();
  });

  it("keeps the sample out of Members and Organization", async () => {
    mocked.org.mockResolvedValue({ ...fx.organization, is_demo: true, role: null });
    await expect(MembersSettingsPage()).rejects.toThrow("NEXT_NOT_FOUND");
    await expect(OrganizationSettingsPage()).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("describes how the sample is configured and what it demonstrates", async () => {
    await expect(SampleSettingsPage()).rejects.toThrow("NEXT_NOT_FOUND");
    mocked.org.mockResolvedValue({ ...fx.organization, is_demo: true, role: null });
    render(await SampleSettingsPage());
    expect(
      screen.getByRole("heading", { name: "How this sample is configured" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/no provider key is stored/)).toBeInTheDocument();
    expect(screen.getByText(/Forms are hidden here/)).toBeInTheDocument();
    for (const [name, href] of [
      ["Anomalies", "/anomalies"],
      ["Budgets", "/budgets"],
      ["Reconciliation", "/reconcile"],
      ["Run history", "/runs"],
      ["Resources", "/inventory"],
    ]) {
      expect(screen.getByRole("link", { name })).toHaveAttribute("href", href);
    }
  });
});

describe("settings: connections", () => {
  freezeNow();

  it("shows required Codex pricing beside its connected account", async () => {
    page.view = { ...page.view!, scope: "codex" };
    const account = {
      ...fx.anthropicAccount,
      id: 7,
      provider: "codex",
      label: "Codex",
      external_id: "11111111-2222-4333-8444-555555555555",
    };
    mocked.providers.mockResolvedValue([
      {
        ...fx.anthropicInfo,
        provider: "codex",
        label: "Codex",
        vendor: "OpenAI",
        surface: "Codex",
        key_label: "Admin API key",
        key_prefix: "sk-admin-",
        env_var: "CODEX_ADMIN_KEY",
        attribution: "direct",
        accounts: [account],
      },
    ]);
    mocked.connection.mockResolvedValue({
      ...fx.connection,
      provider: "codex",
      accounts: [account],
    });
    mocked.creditPrices.mockResolvedValue([]);

    render(await ConnectionsSettingsPage());

    expect(mocked.creditPrices).toHaveBeenCalledWith("default", 7);
    expect(screen.getByRole("alert")).toHaveTextContent("Pricing required");
    expect(screen.getByLabelText("Effective from")).toBeEnabled();
    expect(screen.getByLabelText("USD per credit")).toBeEnabled();
  });

  it("marks an experimental connector on its card from the registry flag", async () => {
    mocked.providers.mockResolvedValue([{ ...fx.anthropicInfo, experimental: true }]);

    render(await ConnectionsSettingsPage());

    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      "Anthropicexperimentalconnected",
    ]);
  });

  it("states the key in one line and keeps the field behind Replace key", async () => {
    render(await ConnectionsSettingsPage());

    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      "Anthropicconnected",
    ]);
    expect(screen.getByText(/\.\.\.4321/).closest("p")).toHaveTextContent(
      "Key ...4321 (stored), checked 3 hours ago (2026-09-14 09:00 UTC).",
    );
    // A working key needs no input: the field opens on demand and closes again.
    expect(screen.queryByLabelText("New admin key")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Replace key" }));
    const field = screen.getByLabelText("New admin key");
    expect(field).toHaveAttribute("type", "password");
    expect(screen.getByText(/Checked with one read-only request/)).toHaveTextContent(
      "sk-ant-admin",
    );
    // The prefix and key label travel with the form so the action can refuse the wrong key.
    const form = field.closest("form")!;
    expect(form.querySelector('input[name="key_prefix"]')).toHaveAttribute("value", "sk-ant-admin");
    expect(form.querySelector('input[name="provider"]')).toHaveAttribute("value", "anthropic");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("New admin key")).not.toBeInTheDocument();
  });

  it("names the console once and removes the key behind a confirmation", async () => {
    render(await ConnectionsSettingsPage());

    expect(screen.getAllByRole("link", { name: "Anthropic Console" })).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Anthropic Console" })).toHaveAttribute(
      "href",
      "https://console.anthropic.com/settings/admin-keys",
    );
    fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveTextContent("Remove the stored key?");
    expect(within(dialog).getByRole("button", { name: "Remove key" })).toHaveAttribute(
      "form",
      "disconnect-form-anthropic-1",
    );
  });

  it("names the instance-provided key and offers to store one of the organization", async () => {
    mocked.connection.mockResolvedValue(fx.connectionFromEnvironment);
    render(await ConnectionsSettingsPage());

    expect(screen.getByText(/\.\.\.env9/).closest("p")).toHaveTextContent(
      "Key ...env9 (provided by the instance configuration), checked never.",
    );
    expect(screen.queryByRole("button", { name: "Disconnect" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Connect a key" }));
    expect(screen.getByLabelText("Anthropic admin key")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect" })).toBeInTheDocument();
  });

  it("asks for a key when nothing is connected and hides the form when writes are off", async () => {
    mocked.connection.mockResolvedValue(fx.notConnected);
    render(await ConnectionsSettingsPage());

    expect(screen.getAllByText("not connected")).toHaveLength(1);
    expect(
      screen.getByText(/Nothing syncs from Anthropic until one is connected here\./),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect" })).toBeInTheDocument();
    expect(screen.queryByText(/turned off on this instance/)).not.toBeInTheDocument();
    cleanup();

    mocked.connection.mockResolvedValue({ ...fx.notConnected, writes_enabled: false });
    render(await ConnectionsSettingsPage());
    expect(
      screen.getByText(/Changes from the browser are turned off on this instance\./),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Connect" })).not.toBeInTheDocument();
    cleanup();

    mocked.connection.mockResolvedValue({ ...fx.notConnected, secret_key_configured: false });
    render(await ConnectionsSettingsPage());
    expect(screen.getByRole("note")).toHaveTextContent(
      "Key storage is not configured on this instance, so a key cannot be saved yet. Ask whoever runs Costura to finish the server setup.",
    );
    expect(screen.queryByRole("button", { name: "Connect" })).not.toBeInTheDocument();
  });

  it("tells a member who owns the key instead of offering the form", async () => {
    mocked.org.mockResolvedValue({ ...fx.organization, role: "member" });
    render(await ConnectionsSettingsPage());

    expect(screen.getByText("An owner of this organization manages this key.")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Disconnect|Connect|Replace/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/\.\.\.4321/).closest("p")).toHaveTextContent("(stored)");
  });

  it("previews the sample's providers without a key or a form", async () => {
    mocked.org.mockResolvedValue({ ...fx.organization, is_demo: true, role: null });
    page.view = { ...page.view!, scope: "all" };
    mocked.connection.mockImplementation(async (_org: string, provider: string) =>
      provider === "anthropic" ? fx.connection : { ...fx.notConnected, provider, accounts: [] },
    );
    render(await ConnectionsSettingsPage());

    expect(screen.getByRole("heading", { name: /^Anthropic/ })).toHaveTextContent("sample");
    expect(screen.getByText(/Here the data is generated: no key is stored/)).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Anthropic accounts" })).toHaveTextContent("refreshed");
    expect(screen.queryByText(/4321/)).not.toBeInTheDocument();
    expect(screen.queryByText(/not connected/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText(/supported but not part of the sample/)).toBeInTheDocument();
  });

  it("lists one row per account with rename, remove and Add account", async () => {
    mocked.connection.mockResolvedValue(fx.connectionWithTwoAccounts);
    vi.mocked(renameAccountAction).mockResolvedValue({ ok: true, message: "Renamed to Labs." });
    vi.mocked(removeAccountAction).mockResolvedValue({ ok: true, message: "Account removed." });
    render(await ConnectionsSettingsPage());

    expect(screen.getByRole("heading", { name: /^Anthropic/ })).toHaveTextContent("2 accounts");
    const list = screen.getByRole("list", { name: "Anthropic accounts" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    // The default account keeps the provider's name and shows it once two rows exist.
    expect(rows[0]).toHaveTextContent("Anthropic");
    expect(rows[1]).toHaveTextContent("Research");
    expect(rows[1]).toHaveTextContent("org_redacted_second");
    expect(
      within(rows[1]!).getByRole("button", { name: "Disconnect" }).closest("form"),
    ).toHaveAttribute("id", "disconnect-form-anthropic-4");
    // Replacing the key of a named account says which one.
    fireEvent.click(within(rows[1]!).getByRole("button", { name: "Replace key" }));
    expect(screen.getByLabelText("New admin key for Research")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    // Rename posts the account id and the new name.
    fireEvent.click(within(rows[1]!).getByRole("button", { name: "Rename" }));
    const nameField = within(rows[1]!).getByLabelText("Account name");
    fireEvent.change(nameField, { target: { value: "Labs" } });
    fireEvent.submit(nameField.closest("form")!);
    await waitFor(() => expect(renameAccountAction).toHaveBeenCalledOnce());
    const renamed = vi.mocked(renameAccountAction).mock.calls[0]![1] as FormData;
    expect(renamed.get("account_id")).toBe("4");
    expect(renamed.get("label")).toBe("Labs");

    // Remove stays behind a confirmation and names the account.
    fireEvent.click(within(rows[1]!).getByRole("button", { name: "Remove" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Research");
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove account" }));
    await waitFor(() => expect(removeAccountAction).toHaveBeenCalledOnce());
    expect((vi.mocked(removeAccountAction).mock.calls[0]![1] as FormData).get("account_id")).toBe(
      "4",
    );

    // A further console connects through "Add account", with an optional name.
    fireEvent.click(screen.getByRole("button", { name: "Add account" }));
    expect(screen.getByLabelText("Account name (optional)")).toBeInTheDocument();
    const keyField = screen.getByLabelText("admin key of the account");
    expect(keyField.closest("form")!.querySelector('input[name="mode"]')).toHaveAttribute(
      "value",
      "add",
    );
  });

  it("offers no Remove on the only account of a provider", async () => {
    render(await ConnectionsSettingsPage());
    expect(screen.queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add account" })).toBeInTheDocument();
  });

  it("shows the provider error next to the badge", async () => {
    mocked.connection.mockResolvedValue({
      ...fx.connection,
      last_error: "Anthropic rejected the key (HTTP 401).",
    });
    render(await ConnectionsSettingsPage());

    expect(screen.getByRole("heading", { name: /^Anthropic/ })).toHaveTextContent("error");
    expect(screen.getByText("Anthropic rejected the key (HTTP 401).")).toBeInTheDocument();
  });

  describe("under all providers", () => {
    beforeEach(() => {
      page.view = { ...page.view!, scope: "all" };
    });

    freezeNow();

    it("renders one card per provider, each posting to its own", async () => {
      mocked.connection.mockImplementation((_org: string, provider: string) =>
        Promise.resolve(provider === "openrouter" ? fx.openRouterConnection : fx.connection),
      );
      vi.mocked(disconnectAction).mockResolvedValue({ ok: true, message: "Stored key removed." });
      render(await ConnectionsSettingsPage());

      expect(mocked.connection).not.toHaveBeenCalledWith("default", "all");
      expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
        "Anthropicconnected",
        "OpenRouterconnected",
      ]);
      expect(screen.getByText(/\.\.\.4321/)).toBeInTheDocument();
      expect(screen.getByText(/\.\.\.or99/)).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "OpenRouter console" })).toHaveAttribute(
        "href",
        "https://openrouter.ai/settings/management-keys",
      );
      const disconnects = screen.getAllByRole("button", { name: "Disconnect" });
      expect(disconnects.map((button) => button.closest("form")?.id)).toEqual([
        "disconnect-form-anthropic-1",
        "disconnect-form-openrouter-2",
      ]);
      fireEvent.click(disconnects[1]!);
      const dialog = await screen.findByRole("alertdialog");
      const confirm = within(dialog).getByRole("button", { name: "Remove key" });
      expect(confirm).toHaveAttribute("form", "disconnect-form-openrouter-2");
      fireEvent.click(confirm);
      await waitFor(() => expect(disconnectAction).toHaveBeenCalledOnce());
      const submitted = vi.mocked(disconnectAction).mock.calls[0]![1] as FormData;
      expect(submitted.get("provider")).toBe("openrouter");
      expect(submitted.get("account_id")).toBe("2");
      // Each key field carries its own provider and prefix once opened.
      fireEvent.click(screen.getAllByRole("button", { name: "Replace key" })[1]!);
      const openRouterForm = screen.getByLabelText("New management key").closest("form")!;
      expect(openRouterForm.querySelector('input[name="provider"]')).toHaveAttribute(
        "value",
        "openrouter",
      );
      expect(openRouterForm.querySelector('input[name="key_prefix"]')).toHaveAttribute(
        "value",
        "sk-or-v1-",
      );
    });

    it("keeps the connect form of the provider still missing a key", async () => {
      mocked.providers.mockResolvedValue(fx.providersOneConnected);
      mocked.connection.mockImplementation((_org: string, provider: string) =>
        Promise.resolve(provider === "openrouter" ? fx.notConnected : fx.connection),
      );
      render(await ConnectionsSettingsPage());

      expect(
        screen.getByText(/Nothing syncs from OpenRouter until one is connected here/),
      ).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Connect" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Replace key" })).toBeInTheDocument();
    });
  });
});

describe("settings: sync", () => {
  freezeNow();

  it("dates the last import in relative time and names what started it", async () => {
    render(await SyncSettingsPage());

    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("Automatic syncsucceeded");
    expect(screen.getByText(/Once a day at 06:00 UTC Costura imports/)).toBeInTheDocument();
    expect(screen.getByText(/^5 hours ago \(/).closest("dd")).toHaveTextContent(
      "5 hours ago (2026-09-14 06:02 UTC), automatic",
    );
    expect(screen.getByText("2026-09-15 06:00 UTC")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sync now" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Full run history" })).toHaveAttribute("href", "/runs");
    expect(screen.queryByText(/No automatic run yet/)).not.toBeInTheDocument();
  });

  it("warns when the import that was due did not run", async () => {
    vi.setSystemTime(new Date("2026-09-16T12:00:00Z"));
    render(await SyncSettingsPage());

    expect(
      screen.getByText(/The automatic import due 2026-09-15 06:00 UTC has not run\./),
    ).toBeInTheDocument();
    expect(screen.getByText(/ask whoever runs Costura to check the daily import/)).toBeVisible();
  });

  it("says nothing ran yet, and nothing is scheduled without a key", async () => {
    mocked.connection.mockResolvedValue(fx.connectionFromEnvironment);
    render(await SyncSettingsPage());

    expect(screen.getByText("never")).toBeInTheDocument();
    expect(
      screen.getByText(
        "No automatic run yet. Runs happen once a day for every connected provider; use Sync now to import today.",
      ),
    ).toBeInTheDocument();
    cleanup();

    mocked.connection.mockResolvedValue(fx.notConnected);
    render(await SyncSettingsPage());
    expect(screen.getByText(/none: connect a key first/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sync now" })).not.toBeInTheDocument();
    expect(screen.queryByText(/No automatic run yet/)).not.toBeInTheDocument();
  });

  it("lists one row per provider under all, with the failed steps", async () => {
    page.view = { ...page.view!, scope: "all" };
    mocked.connection.mockImplementation((_org: string, provider: string) =>
      Promise.resolve(provider === "openrouter" ? fx.openRouterConnection : fx.connection),
    );
    render(await SyncSettingsPage());

    expect(screen.getByText("Anthropic").closest("dt")).toBeInTheDocument();
    expect(screen.getByText("OpenRouter").closest("dt")).toBeInTheDocument();
    expect(screen.getByText(/failed: usage 2026-09/)).toBeInTheDocument();
    expect(screen.getAllByText(/^5 hours ago \(/)).toHaveLength(2);
    const sync = screen.getByRole("button", { name: "Sync now" }).closest("form")!;
    expect(sync.querySelector('input[name="provider"]')).toHaveAttribute("value", "all");
    expect(screen.getByText(/Runs every connected provider in turn/)).toBeInTheDocument();
  });

  it("starts the sync, then follows the running steps through setup", async () => {
    const syncNow = vi.mocked(syncNowAction);
    syncNow.mockResolvedValue({
      ok: true,
      message: "Sync started.",
      results: [
        {
          provider: "anthropic",
          provider_account_id: 1,
          run_id: 31,
          status: "running",
          error: null,
          steps: [],
        },
      ],
    });
    vi.mocked(getSetupAction).mockResolvedValue({ setup: fx.setupSyncing, error: null });
    render(await SyncSettingsPage());

    fireEvent.submit(screen.getByRole("button", { name: "Sync now" }).closest("form")!);

    expect(await screen.findByText("Sync started.")).toBeInTheDocument();
    await waitFor(() => expect(getSetupAction).toHaveBeenCalledWith("default"));
    const table = await screen.findByRole("table", { name: "Anthropic steps" });
    expect(within(table).getByText("Inventory")).toBeInTheDocument();
    expect(within(table).getByText("3 workspaces, 12 keys, 4 users")).toBeInTheDocument();
    expect(within(table).getByText(/Still importing/)).toBeInTheDocument();
    expect(screen.getByText("Importing")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Syncing..." })).toBeDisabled();
    expect(screen.getByText(/Steps appear as they finish/)).toBeInTheDocument();
  });

  it("is read-only on the sample organization", async () => {
    mocked.org.mockResolvedValue({ ...fx.organization, is_demo: true, role: null });
    render(await SyncSettingsPage());

    expect(screen.queryByRole("button", { name: "Sync now" })).not.toBeInTheDocument();
    expect(screen.getByText(/^5 hours ago \(/)).toBeInTheDocument();
    expect(screen.getByText("with the next sample refresh, once a day")).toBeInTheDocument();
    expect(screen.getByText(/generated provider answers/)).toBeInTheDocument();
  });

  it("tells a viewer who runs imports instead of offering the button", async () => {
    mocked.org.mockResolvedValue({ ...fx.organization, role: "viewer" });
    render(await SyncSettingsPage());

    expect(screen.queryByRole("button", { name: "Sync now" })).not.toBeInTheDocument();
    expect(screen.getByText(/Members and owners run imports/)).toBeInTheDocument();
  });
});

describe("settings: members", () => {
  freezeNow();

  it("lists the members with their role and join date", async () => {
    render(await MembersSettingsPage());

    expect(mocked.members).toHaveBeenCalledWith("default");
    const table = screen.getByRole("table", { name: "Members" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    expect(within(rows[0]!).getByText("owner@example.com")).toBeInTheDocument();
    expect(within(rows[0]!).getAllByRole("cell")[1]).toHaveTextContent("Owner");
    expect(within(rows[0]!).getByText("(you)")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("2026-09-14")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("dev@example.com")).toBeInTheDocument();
    expect(within(rows[2]!).getByText("watcher@example.com")).toBeInTheDocument();
    cleanup();

    mocked.members.mockRejectedValue(new Error("boom"));
    render(await MembersSettingsPage());
    expect(screen.getByText(/Could not load the members/)).toBeInTheDocument();
  });

  it("gives an owner the invite card, a role select per row and Remove", async () => {
    render(await MembersSettingsPage());

    expect(screen.getByRole("heading", { level: 2, name: "Invite someone" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Invite" })).toBeInTheDocument();
    expect(screen.getByText(/Costura sends no e-mail/)).toBeInTheDocument();
    // Every role is offered with the sentence that says what it may do.
    expect(screen.getByText("Reads every page. Changes nothing.")).toBeInTheDocument();

    const table = screen.getByRole("table", { name: "Members" });
    const rows = within(table).getAllByRole("row").slice(1);
    // The sole owner keeps the role and the membership; the other rows are changeable.
    expect(within(rows[0]!).getByLabelText("Role of owner@example.com")).toBeDisabled();
    expect(within(rows[0]!).getByText("last owner")).toBeInTheDocument();
    expect(within(rows[0]!).queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
    expect(within(rows[1]!).getByLabelText("Role of dev@example.com")).toBeEnabled();
    expect(within(rows[1]!).getByRole("button", { name: "Remove" })).toBeEnabled();
  });

  it("lists the invitations nobody claimed, with Revoke", async () => {
    render(await MembersSettingsPage());

    expect(mocked.invitations).toHaveBeenCalledWith("default");
    const table = screen.getByRole("table", { name: "Pending invitations" });
    const row = within(table).getAllByRole("row")[1];
    expect(within(row!).getByText("newcomer@example.com")).toBeInTheDocument();
    expect(within(row!).getByText("Member")).toBeInTheDocument();
    expect(within(row!).getByText("owner@example.com")).toBeInTheDocument();
    expect(within(row!).getByText("in 14 days")).toBeInTheDocument();
    expect(within(row!).getByRole("button", { name: "Revoke" })).toBeInTheDocument();
    cleanup();

    // An expired one shows why the link stopped working instead of a countdown.
    mocked.invitations.mockResolvedValue([{ ...fx.invitations[0], status: "expired" }]);
    render(await MembersSettingsPage());
    expect(screen.getByText("expired")).toBeInTheDocument();
  });

  it("is read-only for a member and a viewer", async () => {
    for (const role of ["member", "viewer"] as const) {
      mocked.org.mockResolvedValue({ ...fx.organization, role });
      render(await MembersSettingsPage());

      expect(screen.queryByRole("button", { name: "Invite" })).not.toBeInTheDocument();
      expect(screen.queryByRole("table", { name: "Pending invitations" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Role of dev@example.com")).not.toBeInTheDocument();
      expect(screen.getByText("Owners invite people and change roles.")).toBeInTheDocument();
      // The roles are still visible, as badges.
      expect(screen.getByRole("table", { name: "Members" })).toBeInTheDocument();
      cleanup();
    }
    expect(mocked.invitations).not.toHaveBeenCalled();
  });
});

describe("settings: organization", () => {
  it("lets an owner rename and shows the fixed id with its creation date", async () => {
    mocked.org.mockResolvedValue({ ...fx.organization, created_at: "2026-09-14T10:00:00Z" });
    render(await OrganizationSettingsPage());

    expect(screen.getByLabelText("Name")).toHaveValue("Default organization");
    expect(screen.getByRole("button", { name: "Save name" })).toBeInTheDocument();
    expect(screen.getByText("default", { selector: "code" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy organization id" })).toBeInTheDocument();
    expect(screen.getByText("2026-09-14")).toBeInTheDocument();
  });

  it("shows the name read-only to a member and an unknown creation date", async () => {
    mocked.org.mockResolvedValue({ ...fx.organization, role: "member" });
    render(await OrganizationSettingsPage());

    expect(screen.queryByRole("button", { name: "Save name" })).not.toBeInTheDocument();
    expect(screen.getByText(/Only an owner can change it/)).toBeInTheDocument();
    expect(screen.getByText("Default organization")).toBeInTheDocument();
    expect(screen.getByText("Unknown")).toBeInTheDocument();
  });
});

describe("settings: account", () => {
  freezeNow();

  it("holds the caller's own identity, alert opt-in and sessions", async () => {
    render(await AccountSettingsPage());

    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      "You in this organization",
      "Alerts",
      "Your sessions",
      "Leave this organization",
    ]);
    expect(screen.getByText("owner@example.com")).toBeInTheDocument();
    expect(screen.getByText("owner")).toBeInTheDocument();
    // The only owner cannot leave: the organization would have nobody to manage its keys.
    expect(screen.queryByRole("button", { name: "Leave organization" })).not.toBeInTheDocument();
    expect(screen.getByText(/You are the only owner/)).toBeInTheDocument();
    // The caller's own opt-in for the bell, off by default.
    expect(screen.getByRole("button", { name: "Turn alerts on" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByRole("button", { name: "Sign out everywhere" })).toBeInTheDocument();
  });

  it("stays open to a member and reports what it could not read", async () => {
    mocked.org.mockResolvedValue({ ...fx.organization, role: "member" });
    mocked.alerts.mockRejectedValue(new Error("boom"));
    mocked.me.mockResolvedValue({ ...fx.me, user: { email: "dev@example.com", name: null } });
    mocked.members.mockResolvedValue([
      { ...fx.members[0], is_you: false },
      { ...fx.members[1], is_you: true },
    ]);
    render(await AccountSettingsPage());

    expect(screen.getByText("member")).toBeInTheDocument();
    expect(screen.getByText(/Could not load your alert setting/)).toBeInTheDocument();
    // Anyone who is not the last owner may give up their own membership.
    expect(screen.getByRole("button", { name: "Leave organization" })).toBeEnabled();
  });

  it("keeps a viewer's own settings and drops nothing else", async () => {
    mocked.org.mockResolvedValue({ ...fx.organization, role: "viewer" });
    mocked.me.mockResolvedValue({ ...fx.me, user: { email: "watcher@example.com", name: null } });
    mocked.members.mockResolvedValue([
      { ...fx.members[0], is_you: false },
      { ...fx.members[2], is_you: true },
    ]);
    render(await AccountSettingsPage());

    expect(screen.getByText("viewer")).toBeInTheDocument();
    expect(screen.getByText("Reads every page. Changes nothing.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Turn alerts on" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Sign out everywhere" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Leave organization" })).toBeEnabled();
  });

  it("does not exist on the sample organization", async () => {
    mocked.org.mockResolvedValue({ ...fx.organization, is_demo: true, role: null });
    await expect(AccountSettingsPage()).rejects.toThrow("NEXT_NOT_FOUND");
  });
});

describe("settings: advanced", () => {
  freezeNow();

  it("offers to reset the onboarding behind a confirmation naming what is deleted", async () => {
    render(await AdvancedSettingsPage());

    expect(screen.getByRole("heading", { name: "Reset onboarding" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Delete organization" })).toBeInTheDocument();
    expect(
      screen.getByText(/Start over as if this organization were newly created/),
    ).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Reset onboarding" });
    expect(button.closest("form")!.querySelector('input[name="org"]')).toBeNull();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();

    fireEvent.click(button);

    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveTextContent("Reset the onboarding of this organization?");
    expect(dialog).toHaveTextContent(
      "Removes the stored provider keys and every synced record for this organization: spend, inventory, runs, anomalies, projections and budgets. The next visit starts at the welcome screen.",
    );
    const confirm = within(dialog).getByRole("button", { name: "Reset everything" });
    expect(confirm).toHaveAttribute("type", "submit");
    expect(confirm).toHaveAttribute("form", "reset-setup-form");
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("holds the reset while a run is in progress", async () => {
    mocked.setup.mockResolvedValue(fx.setupSyncing);
    render(await AdvancedSettingsPage());

    expect(mocked.setup).toHaveBeenCalledWith("default");
    const button = screen.getByRole("button", { name: "Reset onboarding" });
    expect(button).toBeDisabled();
    expect(button).toHaveAccessibleDescription("Wait for the queued or running import to finish.");
    fireEvent.click(button);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    cleanup();

    mocked.setup.mockResolvedValue(fx.setupReady);
    render(await AdvancedSettingsPage());
    expect(screen.getByRole("button", { name: "Reset onboarding" })).toBeEnabled();
  });

  it("is closed to a member, to a read-only instance and to the sample organization", async () => {
    mocked.org.mockResolvedValue({ ...fx.organization, role: "member" });
    await expect(AdvancedSettingsPage()).rejects.toThrow("NEXT_NOT_FOUND");

    mocked.org.mockResolvedValue(fx.organization);
    mocked.connection.mockResolvedValue({ ...fx.connection, writes_enabled: false });
    await expect(AdvancedSettingsPage()).rejects.toThrow("NEXT_NOT_FOUND");

    mocked.connection.mockResolvedValue(fx.connection);
    mocked.org.mockResolvedValue({ ...fx.organization, is_demo: true, role: null });
    await expect(AdvancedSettingsPage()).rejects.toThrow("NEXT_NOT_FOUND");
  });
});

describe("settings: teams", () => {
  it("lists each team's members and offers people, workspaces and keys to an owner", async () => {
    mocked.teams.mockResolvedValue({
      teams: [
        {
          slug: "platform",
          name: "Platform",
          members: [
            {
              kind: "person",
              provider: "all",
              external_id: "ana@example.com",
              label: "ana@example.com",
              updated_at: "2026-09-01T00:00:00Z",
            },
          ],
        },
      ],
    });
    mocked.users.mockResolvedValue({ items: fx.users });
    mocked.workspaces.mockResolvedValue({ items: fx.workspaces });
    mocked.apiKeys.mockResolvedValue({ items: fx.apiKeys });
    render(await TeamsSettingsPage());

    const list = screen.getByRole("list", { name: "Platform members" });
    expect(within(list).getByText("ana@example.com")).toBeInTheDocument();
    const select = screen.getByLabelText("Add to Platform");
    const groups = [...select.querySelectorAll("optgroup")].map((g) => g.label);
    expect(groups).toEqual(["People", "Workspaces", "API keys"]);
    expect(screen.getByRole("button", { name: "Add team" })).toBeInTheDocument();
  });

  it("shows the teams without controls to a member", async () => {
    mocked.org.mockResolvedValue({ ...fx.organization, role: "member" });
    render(await TeamsSettingsPage());
    expect(screen.getByText("No team yet.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add team" })).not.toBeInTheDocument();
    expect(mocked.users).not.toHaveBeenCalledWith("default", "all", false);
  });
});
