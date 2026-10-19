/**
 * Shared harness for the page tests: the navigation, session and API modules they mock, the
 * mutable request state (path, view cookie, search params) and the default API answers.
 *
 * A factory passed to `vi.mock` runs before the test file's own bindings exist, so each file
 * registers its mocks as `vi.mock(path, () => import("@/test/page-harness").then((h) => ...))`
 * and then calls `withPageDefaults(mocked)`.
 */

import { beforeEach, vi } from "vitest";

import type { Organization, api as realApi } from "@/lib/api";
import { ApiError } from "@/lib/api-error";
import type { ViewCookie } from "@/lib/view-cookie";
import * as fx from "@/test/fixtures";

export const DEMO_VIEW: ViewCookie = { org: "demo", month: "2026-08", scope: "all" };

/** What the request looks like to the page; tests reassign fields before rendering. */
export const page: {
  pathname: string;
  /** The view cookie as the pages see it: organization, month and scope. */
  view: ViewCookie | null;
  searchParams: URLSearchParams;
  segment: string | null;
  /** Session cookie as the layout sees it; null renders the shell for a visitor. */
  sessionToken: string | null;
  /** The organizations `GET /orgs/{slug}` answers from; 404 for any other slug. */
  organizations: Organization[];
} = {
  pathname: "/overview",
  view: { org: "default", month: "2026-08", scope: "anthropic" },
  searchParams: new URLSearchParams(),
  segment: "overview",
  sessionToken: "tok-1",
  organizations: [fx.organization, fx.demoOrganization],
};

export const push = vi.fn();
export const refresh = vi.fn();
const redirect = vi.fn((url: string) => {
  throw new Error(`NEXT_REDIRECT ${url}`);
});
export const markReadAction = vi.fn();
export const setViewAction = vi.fn();
const writeViewCookie = vi.fn(async (next: ViewCookie) => {
  page.view = next;
});

export function navigationModule() {
  return {
    useRouter: () => ({ push, replace: push, prefetch: vi.fn(), refresh }),
    usePathname: () => page.pathname,
    useParams: () => ({}),
    useSearchParams: () => page.searchParams,
    useSelectedLayoutSegment: () => page.segment,
    redirect: (url: string) => redirect(url),
    notFound: () => {
      throw new Error("NEXT_NOT_FOUND");
    },
  };
}

export function sessionCookieModule() {
  return {
    readSessionToken: () => Promise.resolve(page.sessionToken),
  };
}

export function viewCookieModule() {
  return {
    readViewCookie: () => Promise.resolve(page.view),
    writeViewCookie: (next: ViewCookie) => writeViewCookie(next),
    clearViewCookie: vi.fn(),
  };
}

export async function apiModule() {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  // Every function on the real client becomes a spy, so a new API method is mocked without a
  // hand-kept list.
  const mocked = Object.fromEntries(
    Object.entries(actual.api)
      .filter(([, value]) => typeof value === "function")
      .map(([name]) => [name, vi.fn()]),
  );
  return { ...actual, api: mocked };
}

/** A module of server actions where every named export is a spy. */
export function stubs(...names: string[]) {
  return Object.fromEntries(names.map((name) => [name, vi.fn()]));
}

export function anomalyActionsModule() {
  return {
    ...stubs("setStatusAction", "bulkStatusAction", "assignOwnerAction", "unassignOwnerAction"),
    markReadAction: (...args: unknown[]) => markReadAction(...args),
  };
}

export function viewActionsModule() {
  return {
    setViewAction: (...args: unknown[]) => setViewAction(...args),
    switchOrganizationAction: vi.fn(),
  };
}

export type MockedApi = Record<keyof typeof realApi, ReturnType<typeof vi.fn>>;

/** Registers the default request state and API answers before every test of the file. */
export function withPageDefaults(mocked: MockedApi) {
  beforeEach(() => {
    vi.clearAllMocks();
    page.pathname = "/overview";
    page.view = { org: "default", month: "2026-08", scope: "anthropic" };
    page.searchParams = new URLSearchParams();
    page.segment = "overview";
    page.sessionToken = "tok-1";
    page.organizations = [fx.organization, fx.demoOrganization];
    mocked.org.mockImplementation(async (slug: string) => {
      const found = page.organizations.find((o) => o.slug === slug);
      if (!found) throw new ApiError(404, `/orgs/${slug}`, `unknown organization '${slug}'`);
      return found;
    });
    mocked.me.mockResolvedValue(fx.me);
    mocked.members.mockResolvedValue(fx.members);
    mocked.invitations.mockResolvedValue(fx.invitations);
    mocked.providers.mockResolvedValue(fx.providers);
    mocked.setup.mockResolvedValue(fx.setupReady);
    mocked.anomalySettings.mockResolvedValue({
      sensitivity: "normal",
      detect_drops: true,
      detect_new_principals: true,
      retention_days: 90,
    });
    mocked.months.mockResolvedValue({ months: ["2026-08", "2026-07"] });
    mocked.summary.mockResolvedValue(fx.summary);
    mocked.series.mockResolvedValue(fx.series);
    mocked.query.mockImplementation(
      async (
        _org: string,
        request: { measure: string; dimensions?: string[]; filters?: { provider?: string } },
      ) => {
        const dimension = request.dimensions?.[0] ?? "api_key";
        if (dimension === "workspace" && request.measure === "billed_usd") {
          return {
            ...fx.spendQuery,
            dimensions: [dimension],
            buckets: fx.series.days,
            series: fx.series.series.map((item) => ({
              keys: { [dimension]: item.key },
              labels: { [dimension]: item.label },
              provider: item.provider,
              values: item.values,
              total: item.total,
            })),
            other: fx.series.other,
            total: fx.series.total,
          };
        }
        const sourceRows =
          dimension === "provider"
            ? fx.usageByProvider.rows
            : request.filters?.provider === "openrouter"
              ? fx.usageWithByok.rows
              : request.filters?.provider
                ? fx.usageRows
                : fx.usageAll.rows;
        const value = (index: number) => {
          const row = sourceRows[index];
          if (request.measure === "billed_usd") return row!.amount ?? "0.00";
          if (request.measure === "byok_usd") return row!.byok_amount ?? "0.00";
          if (request.measure === "tokens_total") return row!.total_tokens;
          if (request.measure === "tokens_input") return row!.tokens.uncached_input_tokens ?? 0;
          if (request.measure === "tokens_output") return row!.tokens.output_tokens ?? 0;
          if (request.measure === "tokens_cache_read") return row!.tokens.cache_read_tokens ?? 0;
          if (request.measure === "tokens_cache_write") {
            return (
              (row!.tokens.cache_creation_5m_tokens ?? 0) +
              (row!.tokens.cache_creation_1h_tokens ?? 0)
            );
          }
          return row!.web_search_requests;
        };
        return {
          ...fx.spendQuery,
          measure: request.measure,
          dimensions: [dimension],
          series: sourceRows.map((row, index) => ({
            ...fx.spendQuery.series[0],
            keys: { [dimension]: row.key },
            labels: { [dimension]: row.label },
            provider: row.provider,
            values: fx.spendQuery.buckets.map((_item, day) => (day === index ? value(index) : 0)),
            total: value(index),
          })),
        };
      },
    );
    mocked.queries.mockImplementation(
      async (
        org: string,
        request: {
          measures: string[];
          projection?: string;
          dimensions?: string[];
          filters?: { provider?: string };
        },
      ) => {
        const one = mocked.query.getMockImplementation() as
          | ((
              org: string,
              request: {
                measure: string;
                projection?: string;
              },
            ) => Promise<unknown>)
          | undefined;
        const results = [];
        for (const measure of request.measures) {
          results.push(
            await one?.(org, {
              ...request,
              measure,
              projection: measure === "billed_usd" ? request.projection : "none",
            }),
          );
        }
        return { results };
      },
    );
    mocked.usage.mockResolvedValue(fx.usage);
    mocked.activity.mockResolvedValue([]);
    mocked.movers.mockResolvedValue(fx.movers);
    mocked.reconcile.mockResolvedValue(fx.reconcile);
    mocked.runs.mockResolvedValue({ runs: fx.runs });
    mocked.apiKeys.mockResolvedValue({ items: fx.apiKeys });
    mocked.workspaces.mockResolvedValue({ items: fx.workspaces });
    mocked.users.mockResolvedValue({ items: fx.users });
    mocked.apiKey.mockResolvedValue(fx.apiKeys[0]);
    // The lookup route names the provider an id belongs to; here every id is Anthropic's unless
    // the view is one concrete provider, which the fixtures then treat as its own.
    mocked.entityLookup.mockImplementation(
      (_org: string, _kind: string, _id: string, scope?: string) =>
        Promise.resolve({
          provider: scope && scope !== "all" ? scope : "anthropic",
          provider_account_id: null,
        }),
    );
    mocked.workspace.mockResolvedValue(fx.workspaces[0]);
    mocked.user.mockResolvedValue(fx.users[0]);
    mocked.connection.mockResolvedValue(fx.connection);
    mocked.anomalies.mockResolvedValue(fx.noAnomalies);
    mocked.signals.mockResolvedValue(fx.noSignals);
    mocked.signalHistory.mockResolvedValue({ items: [] });
    mocked.teams.mockResolvedValue({ teams: [] });
    mocked.anomaly.mockResolvedValue(fx.anomalyDetail);
    mocked.alerts.mockResolvedValue(fx.alertsOff);
    mocked.webhook.mockResolvedValue(fx.webhookOff);
    mocked.audit.mockResolvedValue({ events: [], total: 0, limit: 50, offset: 0 });
    mocked.projection.mockResolvedValue(fx.noProjections);
    mocked.budgets.mockResolvedValue({ budgets: [] });
    mocked.budgetStatuses.mockResolvedValue(fx.noBudgets);
    mocked.invoices.mockResolvedValue({ month: "2026-08", items: [] });
  });
}
