import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiDown } from "@/components/api-down";
import { ApiError } from "@/lib/api-error";
import * as fx from "@/test/fixtures";

import AnomalyPage from "./(app)/anomalies/[id]/page";
import AnomaliesPage from "./(app)/anomalies/page";
import ExplorePage from "./(app)/explore/page";
import InventoryPage from "./(app)/inventory/page";
import ScopeLayout from "./(app)/layout";
import ModelPage from "./(app)/models/[id]/page";
import EntityNotFound from "./(app)/not-found";
import OverviewPage from "./(app)/overview/page";
import ReconcilePage from "./(app)/reconcile/page";
import RunsPage from "./(app)/runs/page";
import AccountSettingsPage from "./(app)/settings/account/page";
import AdvancedSettingsPage from "./(app)/settings/advanced/page";
import ConnectionsSettingsPage from "./(app)/settings/connections/page";
import SettingsLayout from "./(app)/settings/layout";
import MembersSettingsPage from "./(app)/settings/members/page";
import SyncSettingsPage from "./(app)/settings/sync/page";
import ClaimInvitationPage from "./join/[token]/page";
import JoinPage from "./join/page";
import RootNotFound from "./not-found";

/**
 * Regression fence for the product UI: the person in the browser has no terminal, so no page
 * prints a `costura` verb, a `just` recipe, an environment variable name or a loopback address.
 * Operator instructions live in the READMEs only.
 */
const CLI_COPY =
  /\bcostura (sync|allocate|org|inventory|anomalies)\b|\bjust |COSTURA_|127\.0\.0\.1/;

let pathname = "/overview";
let view = { org: "default", month: "2026-08", scope: "anthropic" };
const ALL_VIEW = { org: "default", month: "2026-08", scope: "all" };

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), refresh: vi.fn() }),
  usePathname: () => pathname,
  useParams: () => ({}),
  useSearchParams: () => new URLSearchParams(),
  useSelectedLayoutSegment: () => "overview",
  redirect: (url: string) => {
    throw new Error(`NEXT_REDIRECT ${url}`);
  },
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));

vi.mock("./(app)/settings/connection-actions", () => ({
  connectAction: vi.fn(),
  disconnectAction: vi.fn(),
  renameAccountAction: vi.fn(),
  removeAccountAction: vi.fn(),
  resetSetupAction: vi.fn(),
  syncNowAction: vi.fn(),
}));
vi.mock("./(app)/settings/member-actions", () => ({
  inviteAction: vi.fn(),
  revokeInvitationAction: vi.fn(),
  setMemberRoleAction: vi.fn(),
  removeMemberAction: vi.fn(),
}));
vi.mock("./(app)/settings/organization-actions", () => ({
  leaveOrganizationAction: vi.fn(),
  renameOrganizationAction: vi.fn(),
  saveAnomalySettingsAction: vi.fn(),
  deleteOrganizationAction: vi.fn(),
}));
vi.mock("./(app)/anomalies/actions", () => ({
  setStatusAction: vi.fn(),
  bulkStatusAction: vi.fn(),
  markReadAction: vi.fn(),
}));
vi.mock("./(app)/overview/actions", () => ({ dismissSetupAction: vi.fn() }));
vi.mock("@/actions/welcome", () => ({ getSetupAction: vi.fn(), startSyncAction: vi.fn() }));

vi.mock("@/lib/session-cookie", () => ({ readSessionToken: () => Promise.resolve("tok-1") }));
vi.mock("@/lib/view-cookie", () => ({
  readViewCookie: () => Promise.resolve(view),
  writeViewCookie: vi.fn(),
  clearViewCookie: vi.fn(),
}));
vi.mock("@/actions/view", () => ({ setViewAction: vi.fn(), switchOrganizationAction: vi.fn() }));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  const names = [
    "org",
    "me",
    "members",
    "invitations",
    "providers",
    "setup",
    "months",
    "summary",
    "series",
    "usage",
    "query",
    "queries",
    "movers",
    "reconcile",
    "runs",
    "apiKeys",
    "workspaces",
    "users",
    "apiKey",
    "entityLookup",
    "workspace",
    "user",
    "anomalies",
    "signals",
    "signalHistory",
    "anomaly",
    "alerts",
    "projection",
    "connection",
    "budgets",
    "budgetStatuses",
    "invoices",
  ];
  return { ...actual, api: Object.fromEntries(names.map((name) => [name, vi.fn()])) };
});

const { api } = await import("@/lib/api");
const mocked = api as unknown as Record<keyof typeof api, ReturnType<typeof vi.fn>>;

beforeEach(() => {
  vi.clearAllMocks();
  pathname = "/overview";
  view = { org: "default", month: "2026-08", scope: "anthropic" };
  mocked.org.mockResolvedValue(fx.organization);
  mocked.me.mockResolvedValue(fx.me);
  mocked.members.mockResolvedValue(fx.members);
  mocked.invitations.mockResolvedValue(fx.invitations);
  mocked.providers.mockResolvedValue(fx.providers);
  mocked.setup.mockResolvedValue(fx.setupReady);
  mocked.months.mockResolvedValue({ months: ["2026-08", "2026-07"] });
  mocked.summary.mockResolvedValue(fx.summary);
  mocked.series.mockResolvedValue(fx.series);
  mocked.usage.mockResolvedValue(fx.usage);
  mocked.query.mockResolvedValue(fx.spendQuery);
  mocked.queries.mockResolvedValue({ results: [fx.spendQuery] });
  mocked.movers.mockResolvedValue(fx.movers);
  mocked.reconcile.mockResolvedValue(fx.reconcile);
  mocked.invoices.mockResolvedValue({ month: "2026-08", items: [] });
  mocked.runs.mockResolvedValue({ runs: fx.runs });
  mocked.apiKeys.mockResolvedValue({ items: fx.apiKeys });
  mocked.workspaces.mockResolvedValue({ items: fx.workspaces });
  mocked.users.mockResolvedValue({ items: fx.users });
  mocked.apiKey.mockResolvedValue(fx.apiKeys[0]);
  mocked.entityLookup.mockResolvedValue({ provider: "anthropic", provider_account_id: null });
  mocked.workspace.mockResolvedValue(fx.workspaces[0]);
  mocked.user.mockResolvedValue(fx.users[0]);
  mocked.connection.mockResolvedValue(fx.connection);
  mocked.anomalies.mockResolvedValue(fx.noAnomalies);
  mocked.signals.mockResolvedValue(fx.noSignals);
  mocked.signalHistory.mockResolvedValue({ items: [] });
  mocked.anomaly.mockResolvedValue({ ...fx.anomalyDetail, owners: [], same_day: [] });
  mocked.alerts.mockResolvedValue(fx.alertsOff);
  mocked.projection.mockResolvedValue(fx.noProjections);
  mocked.budgets.mockResolvedValue({ budgets: [] });
  mocked.budgetStatuses.mockResolvedValue(fx.noBudgets);
});

afterEach(cleanup);

function expectNoCliCopy() {
  expect(document.body.textContent).not.toMatch(CLI_COPY);
}

const emptyMonth = { ...fx.summary, total: "0.00", allocation: null };
const writesOff = { ...fx.setupReady, writes_enabled: false };

describe("no CLI copy in the product UI", () => {
  it("overview: empty without a key, empty without writes, populated", async () => {
    mocked.summary.mockResolvedValue(emptyMonth);
    mocked.setup.mockResolvedValue(fx.setupConnect);
    render(await OverviewPage({ searchParams: fx.noSearch }));
    expectNoCliCopy();
    cleanup();

    mocked.setup.mockResolvedValue(writesOff);
    view = ALL_VIEW;
    render(await OverviewPage({ searchParams: fx.noSearch }));
    expectNoCliCopy();
    cleanup();

    mocked.summary.mockResolvedValue({ ...fx.summary, top_key_count: 0 });
    mocked.series.mockResolvedValue({ ...fx.series, source: "cost" });
    mocked.usage.mockResolvedValue({ ...fx.usage, rows: [] });
    render(await OverviewPage({ searchParams: fx.noSearch }));
    expectNoCliCopy();
  });

  it("explore: empty month, tokens only", async () => {
    mocked.usage.mockResolvedValue({ ...fx.usage, rows: [], allocated: false });
    render(await ExplorePage({ searchParams: fx.noSearch }));
    expectNoCliCopy();
  });

  it("runs: empty under one provider and under all, with and without a key", async () => {
    mocked.runs.mockResolvedValue({ runs: [] });
    render(await RunsPage({ searchParams: fx.noSearch }));
    expectNoCliCopy();
    cleanup();

    mocked.setup.mockResolvedValue(fx.setupConnect);
    view = ALL_VIEW;
    render(await RunsPage({ searchParams: fx.noSearch }));
    expectNoCliCopy();
  });

  it("inventory: empty", async () => {
    mocked.apiKeys.mockResolvedValue({ items: [] });
    render(await InventoryPage({ searchParams: fx.noSearch }));
    expectNoCliCopy();
  });

  it("anomalies: empty under one provider and under all", async () => {
    render(await AnomaliesPage({ searchParams: fx.noSearch }));
    expectNoCliCopy();
    cleanup();

    view = ALL_VIEW;
    render(await AnomaliesPage({ searchParams: fx.noSearch }));
    expectNoCliCopy();
  });

  it("anomaly detail: without owners or same-day rows, writes off", async () => {
    mocked.setup.mockResolvedValue(writesOff);
    render(await AnomalyPage({ params: Promise.resolve({ id: "7" }) }));
    expectNoCliCopy();
  });

  it("reconcile: pending checks, empty month, and all with nothing connected", async () => {
    mocked.reconcile.mockResolvedValue({
      ...fx.reconcile,
      costura_total: "0.00",
      provider_check: null,
      raw_check: null,
      allocation: null,
    });
    render(await ReconcilePage({ searchParams: fx.noSearch }));
    expectNoCliCopy();
    cleanup();

    mocked.providers.mockResolvedValue(fx.providersNoneConnected);
    view = ALL_VIEW;
    render(await ReconcilePage({ searchParams: fx.noSearch }));
    expectNoCliCopy();
  });

  it("settings connections: writes on, writes off, key storage missing, instance key", async () => {
    mocked.connection.mockResolvedValue(fx.notConnected);
    render(await ConnectionsSettingsPage());
    expectNoCliCopy();
    cleanup();

    mocked.connection.mockResolvedValue({ ...fx.notConnected, writes_enabled: false });
    render(await ConnectionsSettingsPage());
    expectNoCliCopy();
    cleanup();

    mocked.connection.mockResolvedValue({ ...fx.notConnected, secret_key_configured: false });
    render(await ConnectionsSettingsPage());
    expectNoCliCopy();
    cleanup();

    mocked.connection.mockResolvedValue(fx.connectionFromEnvironment);
    view = ALL_VIEW;
    render(await ConnectionsSettingsPage());
    expectNoCliCopy();
  });

  it("settings: the shell, sync, members, account and advanced sections", async () => {
    render(await SettingsLayout({ children: null }));
    expectNoCliCopy();
    cleanup();

    mocked.connection.mockResolvedValue(fx.connectionFromEnvironment);
    view = ALL_VIEW;
    render(await SyncSettingsPage());
    expectNoCliCopy();
    cleanup();

    render(await MembersSettingsPage());
    expectNoCliCopy();
    cleanup();

    render(await AccountSettingsPage());
    expectNoCliCopy();
    cleanup();

    mocked.connection.mockResolvedValue(fx.connection);
    render(await AdvancedSettingsPage());
    expectNoCliCopy();
  });

  it("join: the invitation list and the link page", async () => {
    mocked.me.mockResolvedValue({ ...fx.me, invitations: [fx.pendingInvitation] });
    render(await JoinPage());
    expectNoCliCopy();
    cleanup();

    render(await ClaimInvitationPage({ params: Promise.resolve({ token: "tok" }) }));
    expectNoCliCopy();
    cleanup();

    // Nothing waiting: the page explains the mismatch without naming a command.
    mocked.me.mockResolvedValue({ ...fx.me, invitations: [] });
    render(await JoinPage());
    expectNoCliCopy();
  });

  it("entity page: no spend in the month", async () => {
    mocked.usage.mockResolvedValue({ ...fx.usage, by: "model", rows: [] });
    render(await ModelPage({ params: Promise.resolve({ id: "claude-haiku" }) }));
    expectNoCliCopy();
  });

  it("not-found pages and the error boundary body", async () => {
    render(<RootNotFound />);
    expectNoCliCopy();
    cleanup();

    pathname = "/keys/nope";
    render(await EntityNotFound());
    expectNoCliCopy();
    cleanup();

    render(<ApiDown error={new Error("fetch failed")} reset={() => {}} />);
    expectNoCliCopy();
    expect(screen.getByText("Technical details")).toBeInTheDocument();
    cleanup();

    render(
      <ApiDown
        error={new ApiError(429, "/orgs/demo/query", "too many requests", "60")}
        reset={() => {}}
      />,
    );
    expect(screen.getByText("Sample data is temporarily busy")).toBeInTheDocument();
    expect(screen.getByText(/Wait a minute/)).toBeInTheDocument();
  });

  it("data freshness drawer: no runs and writes off", async () => {
    mocked.runs.mockResolvedValue({ runs: [] });
    mocked.connection.mockResolvedValue({ ...fx.connection, writes_enabled: false });
    render(await ScopeLayout({ children: null }));
    fireEvent.click(screen.getByRole("button", { name: /^Data freshness:/ }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expectNoCliCopy();
  });
});
