/** The welcome page: one connect card per provider and the first sync. */

import { describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import * as fx from "@/test/fixtures";
import { ApiError } from "@/lib/api";
import WelcomePage from "./welcome/page";
import { connectAction } from "./(app)/settings/connection-actions";
import { page, push, withPageDefaults, type MockedApi } from "@/test/page-harness";

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

describe("welcome", () => {
  it("shows one connect card per provider with the console link and hint", async () => {
    mocked.setup.mockResolvedValue(fx.setupConnect);
    render(await WelcomePage());

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "See your LLM spend in about two minutes.",
    );
    expect(screen.getByText(/one read-only request and stores it encrypted/)).toBeInTheDocument();
    // One provider at a time: the picker lists the unconnected ones, the first is open.
    const picker = screen.getByRole("combobox", { name: "Provider to connect" });
    expect(
      within(picker)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Anthropic", "OpenRouter"]);
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      "Anthropic",
    ]);
    const console = screen.getByRole("link", { name: "Open Anthropic Console" });
    expect(console).toHaveAttribute("href", "https://console.anthropic.com/settings/admin-keys");
    expect(console).toHaveAttribute("target", "_blank");
    expect(screen.getByText("Anthropic Console -> Settings -> Admin keys.")).toBeInTheDocument();
    expect(screen.getByText("Admin API: cost report and usage report.")).toBeInTheDocument();
    expect(screen.getByText(/Console admin keys have no scopes/)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Connect" })).toHaveLength(1);

    fireEvent.change(picker, { target: { value: "openrouter" } });
    expect(screen.getByRole("link", { name: "Open OpenRouter console" })).toHaveAttribute(
      "href",
      "https://openrouter.ai/settings/management-keys",
    );
    expect(screen.getByText("OpenRouter -> Settings -> Management keys.")).toBeInTheDocument();
    expect(screen.getByText(/Management keys are unscoped/)).toBeInTheDocument();
    fireEvent.change(picker, { target: { value: "anthropic" } });
    expect(screen.getByLabelText("Anthropic admin key")).toHaveAttribute("type", "password");
    // The cards carry the hint, so the form's own help line is dropped.
    expect(screen.queryByText(/Checked with one read-only request before/)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Skip for now, look around" })).toHaveAttribute(
      "href",
      `/overview`,
    );
    // No shell around the column, and no sync state: the banner on the overview follows it.
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open overview" })).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText("Importing")).not.toBeInTheDocument();
    // The sample organization is one click away while none of the user's own has data.
    expect(
      within(screen.getByRole("region", { name: "Explore with sample data first" })).getByRole(
        "link",
        { name: "Explore the sample organization" },
      ),
    ).toHaveAttribute("href", "/o/demo");
  });

  it("tells a member or viewer to ask an owner instead of showing the key forms", async () => {
    mocked.setup.mockResolvedValue(fx.setupConnect);
    mocked.org.mockResolvedValue({ ...fx.organization, role: "member" });
    render(await WelcomePage());
    expect(screen.queryByRole("heading", { level: 2, name: "Anthropic" })).toBeNull();
    expect(screen.getByText(/Only an owner of this organization can connect/)).toBeInTheDocument();
  });

  it("keeps the key forms when the role cannot be read", async () => {
    mocked.setup.mockResolvedValue(fx.setupConnect);
    mocked.org.mockRejectedValue(new Error("fetch failed"));
    render(await WelcomePage());
    expect(screen.getByRole("heading", { level: 2, name: "Anthropic" })).toBeInTheDocument();
  });

  it("sends the sample organization, which has nothing to connect, to its overview", async () => {
    mocked.setup.mockResolvedValue(fx.setupConnect);
    mocked.org.mockResolvedValue(fx.demoOrganization);
    await expect(WelcomePage()).rejects.toThrow("NEXT_REDIRECT /overview");
  });

  it("drops the sample-data link when no sample organization is seeded", async () => {
    mocked.setup.mockResolvedValue(fx.setupConnect);
    mocked.me.mockResolvedValue({ ...fx.me, demo_org: null });
    render(await WelcomePage());
    expect(
      screen.queryByRole("region", { name: "Explore with sample data first" }),
    ).not.toBeInTheDocument();
    cleanup();

    // A failed `GET /me` costs the link, not the page.
    mocked.me.mockRejectedValue(new Error("boom"));
    render(await WelcomePage());
    expect(screen.getAllByRole("button", { name: "Connect" })).toHaveLength(1);
    expect(
      screen.queryByRole("region", { name: "Explore with sample data first" }),
    ).not.toBeInTheDocument();
  });

  it("sends the browser to the overview once a key is accepted", async () => {
    mocked.setup.mockResolvedValue(fx.setupConnect);
    vi.mocked(connectAction).mockResolvedValue({
      ok: true,
      message: "Anthropic admin key ending in 4321 accepted; the first import is starting.",
    });
    render(await WelcomePage());

    const form = screen.getByLabelText("Anthropic admin key").closest("form")!;
    fireEvent.change(screen.getByLabelText("Anthropic admin key"), {
      target: { value: "sk-ant-admin-test" },
    });
    fireEvent.submit(form);

    await waitFor(() => expect(push).toHaveBeenCalledWith(`/overview`));
    expect(await screen.findByRole("status")).toHaveTextContent(/ending in 4321 accepted/);
  });

  it("keeps the remaining connect cards while the first import runs", async () => {
    mocked.setup.mockResolvedValue(fx.setupSyncing);
    render(await WelcomePage());

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "This organization is already importing.",
    );
    expect(screen.getByText(/Anthropic is connected/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open overview" })).toHaveAttribute(
      "href",
      `/overview`,
    );
    // Only the provider without a key gets a card; the syncing table lives in the banner.
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      "OpenRouter",
    ]);
    expect(screen.getByRole("button", { name: "Connect" })).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Skip for now, look around" }),
    ).not.toBeInTheDocument();
  });

  it("names the month already in and links to it once the organization has data", async () => {
    render(await WelcomePage());

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "This organization already has data: August 2026 is in.",
    );
    expect(screen.getByRole("link", { name: "Open overview" })).toHaveAttribute(
      "href",
      "/overview",
    );
    expect(screen.getByText("Every registered provider is connected.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Connect" })).not.toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it("explains instead of asking for a key when the API refuses writes", async () => {
    mocked.setup.mockResolvedValue({ ...fx.setupConnect, writes_enabled: false });
    render(await WelcomePage());

    expect(screen.getByRole("note")).toHaveTextContent(
      "This Costura instance does not accept changes from the browser: connecting a key, Sync now and reset are turned off here.",
    );
    expect(screen.queryByRole("button", { name: "Connect" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Skip for now, look around" })).toBeInTheDocument();
  });

  it("goes back to / when the remembered organization is gone", async () => {
    page.view = { org: "nope", month: null, scope: null };
    mocked.setup.mockRejectedValue(new ApiError(404, "/orgs/nope/setup", "organization not found"));
    await expect(WelcomePage()).rejects.toThrow("NEXT_REDIRECT /");
  });
});
