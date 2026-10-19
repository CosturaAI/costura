import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "./index";

vi.mock("next/navigation", () => ({ redirect: vi.fn() }));
vi.mock("next/headers", () => ({
  cookies: () => Promise.resolve({ get: () => undefined }),
  headers: () => Promise.resolve(new Headers()),
}));

const SNAPSHOT = resolve(__dirname, "../../../../api/tests/snapshots/openapi.json");
type JsonSchema = {
  properties?: Record<string, unknown>;
  required?: string[];
};
type OpenApi = {
  paths: Record<
    string,
    Record<
      string,
      {
        responses?: {
          "200"?: { content?: { "application/json"?: { schema?: { $ref?: string } } } };
        };
      }
    >
  >;
  components: { schemas: Record<string, JsonSchema> };
};
const openapi = JSON.parse(readFileSync(SNAPSHOT, "utf8")) as OpenApi;

function responseSchema(template: string, method: string): JsonSchema {
  const ref =
    openapi.paths[template]?.[method]?.responses?.["200"]?.content?.["application/json"]?.schema
      ?.$ref;
  const name = ref?.split("/").pop();
  const schema = name ? openapi.components.schemas[name] : undefined;
  if (!schema) throw new Error(`no JSON schema for ${method.toUpperCase()} ${template}`);
  return schema;
}
const routes = Object.entries(openapi.paths).flatMap(([template, operations]) =>
  Object.keys(operations).map((method) => ({
    method: method.toUpperCase(),
    template,
    pattern: new RegExp(`^${template.replace(/\{[^}]+\}/g, "[^/]+")}$`),
  })),
);

type Api = typeof api;
type Call = { method: string; path: string; query: Record<string, string[]>; body: unknown };

const fetchMock = vi.fn();

async function sent(invoke: (client: Api) => Promise<unknown>): Promise<Call> {
  fetchMock.mockClear();
  await invoke(api);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const [url, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
  const query: Record<string, string[]> = {};
  for (const key of new Set(url.searchParams.keys())) query[key] = url.searchParams.getAll(key);
  return {
    method: init.method ?? "GET",
    path: url.pathname,
    query,
    body: typeof init.body === "string" ? JSON.parse(init.body) : undefined,
  };
}

/** One call per client method with the request it must produce. */
const CASES: Record<keyof Api, [(client: Api) => Promise<unknown>, Partial<Call>]> = {
  me: [(c) => c.me(), { method: "GET", path: "/api/v1/me" }],
  session: [(c) => c.session(), { method: "GET", path: "/api/v1/me" }],
  googleAuth: [(c) => c.googleAuth(), { method: "GET", path: "/api/v1/auth/google" }],
  googleAuthorization: [
    (c) => c.googleAuthorization(),
    { method: "POST", path: "/api/v1/auth/google/authorization" },
  ],
  googleCallback: [
    (c) => c.googleCallback({ code: "c", state: "s", nonce: "n", code_verifier: "v" }),
    {
      method: "POST",
      path: "/api/v1/auth/google/callback",
      body: { code: "c", state: "s", nonce: "n", code_verifier: "v" },
    },
  ],
  devSignIn: [
    (c) => c.devSignIn("ana@acme.com", "", "s3"),
    {
      method: "POST",
      path: "/api/v1/auth/dev-sign-in",
      body: { email: "ana@acme.com", secret: "s3" },
    },
  ],
  signOut: [(c) => c.signOut(), { method: "POST", path: "/api/v1/auth/sign-out" }],
  signOutEverywhere: [
    (c) => c.signOutEverywhere(),
    { method: "DELETE", path: "/api/v1/auth/sessions" },
  ],
  orgs: [(c) => c.orgs(), { method: "GET", path: "/api/v1/orgs" }],
  org: [(c) => c.org("acme co"), { method: "GET", path: "/api/v1/orgs/acme%20co" }],
  createOrg: [
    (c) => c.createOrg("Acme", "acme"),
    { method: "POST", path: "/api/v1/orgs", body: { name: "Acme", slug: "acme" } },
  ],
  renameOrg: [
    (c) => c.renameOrg("acme", "Acme Inc"),
    { method: "PATCH", path: "/api/v1/orgs/acme", body: { name: "Acme Inc" } },
  ],
  entityLookup: [
    (c) => c.entityLookup("acme", "model", "gpt-4o", "openai"),
    {
      method: "GET",
      path: "/api/v1/orgs/acme/entities/model/gpt-4o",
      query: { scope: ["openai"] },
    },
  ],
  members: [(c) => c.members("acme"), { method: "GET", path: "/api/v1/orgs/acme/members" }],
  setMemberRole: [
    (c) => c.setMemberRole("acme", 4, "viewer"),
    { method: "PATCH", path: "/api/v1/orgs/acme/members/4", body: { role: "viewer" } },
  ],
  removeMember: [
    (c) => c.removeMember("acme", 4),
    { method: "DELETE", path: "/api/v1/orgs/acme/members/4" },
  ],
  invite: [
    (c) => c.invite("acme", "bo@acme.com", "member"),
    {
      method: "POST",
      path: "/api/v1/orgs/acme/invitations",
      body: { email: "bo@acme.com", role: "member" },
    },
  ],
  invitations: [
    (c) => c.invitations("acme"),
    { method: "GET", path: "/api/v1/orgs/acme/invitations" },
  ],
  audit: [
    (c) => c.audit("acme"),
    { method: "GET", path: "/api/v1/orgs/acme/audit", query: { limit: ["100"], offset: ["0"] } },
  ],
  revokeInvitation: [
    (c) => c.revokeInvitation("acme", 9),
    { method: "DELETE", path: "/api/v1/orgs/acme/invitations/9" },
  ],
  acceptInvitation: [
    (c) => c.acceptInvitation(9),
    { method: "POST", path: "/api/v1/invitations/9/accept" },
  ],
  claimInvitation: [
    (c) => c.claimInvitation("tok"),
    { method: "POST", path: "/api/v1/invitations/claim", body: { token: "tok" } },
  ],
  providers: [(c) => c.providers("acme"), { method: "GET", path: "/api/v1/orgs/acme/providers" }],
  setup: [(c) => c.setup("acme"), { method: "GET", path: "/api/v1/orgs/acme/setup" }],
  dismissSetup: [
    (c) => c.dismissSetup("acme"),
    { method: "POST", path: "/api/v1/orgs/acme/setup/dismiss" },
  ],
  resetSetup: [
    (c) => c.resetSetup("acme"),
    { method: "POST", path: "/api/v1/orgs/acme/setup/reset" },
  ],
  deleteOrganization: [
    (c) => c.deleteOrganization("acme", "acme"),
    { method: "DELETE", path: "/api/v1/orgs/acme", body: { slug: "acme" } },
  ],
  anomalySettings: [
    (c) => c.anomalySettings("acme"),
    { method: "GET", path: "/api/v1/orgs/acme/anomaly-settings" },
  ],
  saveAnomalySettings: [
    (c) =>
      c.saveAnomalySettings("acme", {
        sensitivity: "normal",
        detect_drops: true,
        detect_new_principals: true,
        retention_days: 90,
        idle_days: 30,
        new_key_days: 7,
      }),
    {
      method: "PUT",
      path: "/api/v1/orgs/acme/anomaly-settings",
      body: {
        sensitivity: "normal",
        detect_drops: true,
        detect_new_principals: true,
        retention_days: 90,
        idle_days: 30,
        new_key_days: 7,
      },
    },
  ],
  runs: [
    (c) => c.runs("acme", "openai", 20, "costs"),
    {
      method: "GET",
      path: "/api/v1/orgs/acme/providers/openai/runs",
      query: { limit: ["20"], endpoint: ["costs"] },
    },
  ],
  connection: [
    (c) => c.connection("acme", "openai"),
    { method: "GET", path: "/api/v1/orgs/acme/providers/openai/connection" },
  ],
  connect: [
    (c) => c.connect("acme", "cursor", "key_1", { seat_price_usd: "40" }),
    {
      method: "PUT",
      path: "/api/v1/orgs/acme/providers/cursor/connection",
      body: { admin_key: "key_1", seat_price_usd: "40" },
    },
  ],
  disconnect: [
    (c) => c.disconnect("acme", "openai"),
    { method: "DELETE", path: "/api/v1/orgs/acme/providers/openai/connection" },
  ],
  accounts: [
    (c) => c.accounts("acme", "anthropic"),
    { method: "GET", path: "/api/v1/orgs/acme/providers/anthropic/accounts" },
  ],
  addAccount: [
    (c) => c.addAccount("acme", "anthropic", "key_2", ""),
    {
      method: "POST",
      path: "/api/v1/orgs/acme/providers/anthropic/accounts",
      body: { admin_key: "key_2" },
    },
  ],
  renameAccount: [
    (c) => c.renameAccount("acme", "anthropic", 3, "Research"),
    {
      method: "PATCH",
      path: "/api/v1/orgs/acme/providers/anthropic/accounts/3",
      body: { label: "Research" },
    },
  ],
  copilotLogins: [
    (c) => c.copilotLogins("acme", 3),
    { method: "GET", path: "/api/v1/orgs/acme/providers/copilot/accounts/3/logins" },
  ],
  setCopilotLogins: [
    (c) => c.setCopilotLogins("acme", 3, { octocat: "octo@acme.com" }),
    {
      method: "PUT",
      path: "/api/v1/orgs/acme/providers/copilot/accounts/3/logins",
      body: { logins: { octocat: "octo@acme.com" } },
    },
  ],
  replaceAccountKey: [
    (c) => c.replaceAccountKey("acme", "anthropic", 3, "key_3"),
    {
      method: "PUT",
      path: "/api/v1/orgs/acme/providers/anthropic/accounts/3/key",
      body: { admin_key: "key_3" },
    },
  ],
  disconnectAccount: [
    (c) => c.disconnectAccount("acme", "anthropic", 3),
    { method: "DELETE", path: "/api/v1/orgs/acme/providers/anthropic/accounts/3/key" },
  ],
  removeAccount: [
    (c) => c.removeAccount("acme", "anthropic", 3),
    { method: "DELETE", path: "/api/v1/orgs/acme/providers/anthropic/accounts/3" },
  ],
  creditPrices: [
    (c) => c.creditPrices("acme", 3),
    { method: "GET", path: "/api/v1/orgs/acme/accounts/3/credit-prices" },
  ],
  addCreditPrice: [
    (c) => c.addCreditPrice("acme", 3, { effective_from: "2026-09-01", price_per_credit: "0.04" }),
    {
      method: "POST",
      path: "/api/v1/orgs/acme/accounts/3/credit-prices",
      body: { effective_from: "2026-09-01", price_per_credit: "0.04" },
    },
  ],
  deleteCreditPrice: [
    (c) => c.deleteCreditPrice("acme", 3, 5),
    { method: "DELETE", path: "/api/v1/orgs/acme/accounts/3/credit-prices/5" },
  ],
  syncNow: [
    (c) => c.syncNow("acme", "openai", 3),
    { method: "POST", path: "/api/v1/orgs/acme/providers/openai/sync", query: { account: ["3"] } },
  ],
  months: [
    (c) => c.months("acme", "all"),
    { method: "GET", path: "/api/v1/orgs/acme/providers/all/months" },
  ],
  query: [
    (c) =>
      c.query("acme", {
        measure: "billed_usd",
        start: "2026-09-01",
        end: "2026-09-30",
        interval: "day",
      }),
    {
      method: "GET",
      path: "/api/v1/orgs/acme/query",
      query: {
        measure: ["billed_usd"],
        start: ["2026-09-01"],
        end: ["2026-09-30"],
        interval: ["day"],
      },
    },
  ],
  queries: [
    (c) =>
      c.queries("acme", {
        measures: ["billed_usd", "tokens_total"],
        start: "2026-09-01",
        end: "2026-09-30",
        interval: "day",
        projection: "linear",
      }),
    {
      method: "GET",
      path: "/api/v1/orgs/acme/queries",
      query: {
        measures: ["billed_usd,tokens_total"],
        start: ["2026-09-01"],
        end: ["2026-09-30"],
        interval: ["day"],
        projection: ["linear"],
      },
    },
  ],
  summary: [
    (c) => c.summary("acme", "all", "2026-09"),
    { method: "GET", path: "/api/v1/orgs/acme/providers/all/months/2026-09/summary" },
  ],
  series: [
    (c) => c.series("acme", "all", "2026-09", "model", 5, { workspace: "Backend" }),
    {
      method: "GET",
      path: "/api/v1/orgs/acme/providers/all/months/2026-09/series",
      query: { by: ["model"], top: ["5"], workspace: ["Backend"] },
    },
  ],
  usage: [
    (c) => c.usage("acme", "all", "2026-09", "api_key"),
    {
      method: "GET",
      path: "/api/v1/orgs/acme/providers/all/months/2026-09/usage",
      query: { by: ["api_key"] },
    },
  ],
  activity: [
    (c) => c.activity("acme", { since: "2026-09-01", until: "2026-09-30" }),
    {
      method: "GET",
      path: "/api/v1/orgs/acme/activity",
      query: { since: ["2026-09-01"], until: ["2026-09-30"] },
    },
  ],
  movers: [
    (c) => c.movers("acme", "all", "2026-09", "model", 3),
    {
      method: "GET",
      path: "/api/v1/orgs/acme/providers/all/months/2026-09/movers",
      query: { by: ["model"], top: ["3"] },
    },
  ],
  reconcile: [
    (c) => c.reconcile("acme", "openai", "2026-09", "api_key", 3),
    {
      method: "GET",
      path: "/api/v1/orgs/acme/providers/openai/months/2026-09/reconcile",
      query: { by: ["api_key"], account: ["3"] },
    },
  ],
  projection: [
    (c) => c.projection("acme", "all", "2026-09"),
    {
      method: "GET",
      path: "/api/v1/orgs/acme/providers/all/months/2026-09/projection",
      query: { by: ["org"] },
    },
  ],
  inventorySearch: [
    (c) => c.inventorySearch("acme", "all", "ana", 5),
    {
      method: "GET",
      path: "/api/v1/orgs/acme/providers/all/inventory/search",
      query: { q: ["ana"], limit: ["5"] },
    },
  ],
  apiKeys: [
    (c) => c.apiKeys("acme", "openai", false),
    {
      method: "GET",
      path: "/api/v1/orgs/acme/providers/openai/inventory/api-keys",
      query: { include_missing: ["false"], limit: ["2000"], offset: ["0"] },
    },
  ],
  workspaces: [
    (c) => c.workspaces("acme", "openai"),
    {
      method: "GET",
      path: "/api/v1/orgs/acme/providers/openai/inventory/workspaces",
      query: { include_missing: ["true"], limit: ["2000"], offset: ["0"] },
    },
  ],
  users: [
    (c) => c.users("acme", "openai"),
    {
      method: "GET",
      path: "/api/v1/orgs/acme/providers/openai/inventory/users",
      query: { include_missing: ["true"], limit: ["2000"], offset: ["0"] },
    },
  ],
  apiKey: [
    (c) => c.apiKey("acme", "openai", "key/1"),
    { method: "GET", path: "/api/v1/orgs/acme/providers/openai/inventory/api-keys/key%2F1" },
  ],
  workspace: [
    (c) => c.workspace("acme", "openai", "proj_a"),
    { method: "GET", path: "/api/v1/orgs/acme/providers/openai/inventory/workspaces/proj_a" },
  ],
  user: [
    (c) => c.user("acme", "openai", "user_a"),
    { method: "GET", path: "/api/v1/orgs/acme/providers/openai/inventory/users/user_a" },
  ],
  person: [
    (c) => c.person("acme", "all", "2026-09", "ana@acme.com"),
    {
      method: "GET",
      path: "/api/v1/orgs/acme/providers/all/months/2026-09/people/ana%40acme.com",
    },
  ],
  ownerAssignments: [
    (c) => c.ownerAssignments("acme", "openai"),
    { method: "GET", path: "/api/v1/orgs/acme/providers/openai/owners" },
  ],
  assignOwner: [
    (c) => c.assignOwner("acme", "openai", "api_key", "key_1", "ana@acme.com", null),
    {
      method: "PUT",
      path: "/api/v1/orgs/acme/providers/openai/owners/api_key/key_1",
      body: { email: "ana@acme.com", note: null },
    },
  ],
  unassignOwner: [
    (c) => c.unassignOwner("acme", "openai", "api_key", "key_1"),
    { method: "DELETE", path: "/api/v1/orgs/acme/providers/openai/owners/api_key/key_1" },
  ],
  invoices: [
    (c) => c.invoices("acme", "openai", "2026-09"),
    { method: "GET", path: "/api/v1/orgs/acme/providers/openai/months/2026-09/invoices" },
  ],
  setInvoice: [
    (c) => c.setInvoice("acme", "openai", 3, "2026-09", "120.50", "VAT"),
    {
      method: "PUT",
      path: "/api/v1/orgs/acme/providers/openai/accounts/3/invoices/2026-09",
      body: { amount: "120.50", note: "VAT" },
    },
  ],
  deleteInvoice: [
    (c) => c.deleteInvoice("acme", "openai", 3, "2026-09"),
    { method: "DELETE", path: "/api/v1/orgs/acme/providers/openai/accounts/3/invoices/2026-09" },
  ],
  personalKeys: [
    (c) => c.personalKeys("acme", "all"),
    { method: "GET", path: "/api/v1/orgs/acme/providers/all/personal-keys" },
  ],
  markPersonalKey: [
    (c) => c.markPersonalKey("acme", "openai", "key/1", "ana@acme.com"),
    {
      method: "PUT",
      path: "/api/v1/orgs/acme/providers/openai/personal-keys/key%2F1",
      body: { email: "ana@acme.com" },
    },
  ],
  unmarkPersonalKey: [
    (c) => c.unmarkPersonalKey("acme", "openai", "key_1"),
    { method: "DELETE", path: "/api/v1/orgs/acme/providers/openai/personal-keys/key_1" },
  ],
  anomalies: [
    (c) => c.anomalies("acme", "all", "2026-09", undefined, { kind: "workspace", id: "w1" }),
    {
      method: "GET",
      path: "/api/v1/orgs/acme/providers/all/months/2026-09/anomalies",
      query: { series_kind: ["workspace"], series_id: ["w1"] },
    },
  ],
  signals: [
    (c) => c.signals("acme", "all"),
    { method: "GET", path: "/api/v1/orgs/acme/providers/all/signals" },
  ],
  signalHistory: [
    (c) => c.signalHistory("acme"),
    { method: "GET", path: "/api/v1/orgs/acme/signals/history" },
  ],
  anomaly: [
    (c) => c.anomaly("acme", "all", 7),
    { method: "GET", path: "/api/v1/orgs/acme/providers/all/anomalies/7" },
  ],
  setAnomalyStatus: [
    (c) => c.setAnomalyStatus("acme", "all", 7, "acknowledged"),
    {
      method: "PATCH",
      path: "/api/v1/orgs/acme/providers/all/anomalies/7",
      body: { status: "acknowledged" },
    },
  ],
  alerts: [(c) => c.alerts("acme"), { method: "GET", path: "/api/v1/orgs/acme/alerts" }],
  setAlertSettings: [
    (c) => c.setAlertSettings("acme", false),
    { method: "PUT", path: "/api/v1/orgs/acme/alerts/settings", body: { opted_in: false } },
  ],
  markAlertsRead: [
    (c) => c.markAlertsRead("acme", { all: true }),
    { method: "POST", path: "/api/v1/orgs/acme/alerts/read", body: { all: true } },
  ],
  webhook: [(c) => c.webhook("acme"), { method: "GET", path: "/api/v1/orgs/acme/webhook" }],
  snoozeGap: [
    (c) => c.snoozeGap("acme", "anthropic", { kind: "no_owner", key_id: "k1", days: 30 }),
    {
      method: "PUT",
      path: "/api/v1/orgs/acme/providers/anthropic/signals/snoozes",
      body: { kind: "no_owner", key_id: "k1", days: 30 },
    },
  ],
  liftSnooze: [
    (c) => c.liftSnooze("acme", "anthropic", "no_owner", "k1"),
    { method: "DELETE", path: "/api/v1/orgs/acme/providers/anthropic/signals/snoozes/no_owner/k1" },
  ],
  saveWebhook: [
    (c) => c.saveWebhook("acme", "https://hooks.slack.com/services/x"),
    {
      method: "PUT",
      path: "/api/v1/orgs/acme/webhook",
      body: { url: "https://hooks.slack.com/services/x" },
    },
  ],
  removeWebhook: [
    (c) => c.removeWebhook("acme"),
    { method: "DELETE", path: "/api/v1/orgs/acme/webhook" },
  ],
  setWebhookDigest: [
    (c) => c.setWebhookDigest("acme", "weekly"),
    { method: "PUT", path: "/api/v1/orgs/acme/webhook/digest", body: { digest: "weekly" } },
  ],
  testWebhook: [
    (c) => c.testWebhook("acme"),
    { method: "POST", path: "/api/v1/orgs/acme/webhook/test" },
  ],
  resendWebhookDelivery: [
    (c) => c.resendWebhookDelivery("acme", 7),
    { method: "POST", path: "/api/v1/orgs/acme/webhook/deliveries/7/resend" },
  ],
  budgets: [
    (c) => c.budgets("acme", "all"),
    { method: "GET", path: "/api/v1/orgs/acme/providers/all/budgets" },
  ],
  budgetStatuses: [
    (c) => c.budgetStatuses("acme", "all", "2026-09"),
    { method: "GET", path: "/api/v1/orgs/acme/providers/all/months/2026-09/budgets" },
  ],
  setBudget: [
    (c) => c.setBudget("acme", "all", "workspace", "w 1", "500", [50, 90], "week"),
    {
      method: "PUT",
      path: "/api/v1/orgs/acme/providers/all/budgets/workspace/w%201",
      body: { amount: "500", thresholds: [50, 90], period: "week" },
    },
  ],
  teams: [(c) => c.teams("acme"), { method: "GET", path: "/api/v1/orgs/acme/teams" }],
  setTeam: [
    (c) => c.setTeam("acme", "growth", "Growth"),
    { method: "PUT", path: "/api/v1/orgs/acme/teams/growth", body: { name: "Growth" } },
  ],
  deleteTeam: [
    (c) => c.deleteTeam("acme", "growth"),
    { method: "DELETE", path: "/api/v1/orgs/acme/teams/growth" },
  ],
  setTeamMember: [
    (c) => c.setTeamMember("acme", "growth", "person", "all", "ana@acme.com"),
    { method: "PUT", path: "/api/v1/orgs/acme/teams/growth/members/person/all/ana%40acme.com" },
  ],
  deleteTeamMember: [
    (c) => c.deleteTeamMember("acme", "growth", "workspace", "anthropic", "ws 1"),
    { method: "DELETE", path: "/api/v1/orgs/acme/teams/growth/members/workspace/anthropic/ws%201" },
  ],
  deleteBudget: [
    (c) => c.deleteBudget("acme", "all", "org", "acme"),
    { method: "DELETE", path: "/api/v1/orgs/acme/providers/all/budgets/org/acme" },
  ],
};

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockImplementation(() =>
    Promise.resolve(
      new Response("{}", { status: 200, headers: { "content-type": "application/json" } }),
    ),
  );
  vi.stubGlobal("fetch", fetchMock);
});

describe("API client contract", () => {
  it("reads every page of an inventory list", async () => {
    const key = (id: number) => ({ id: `k${id}` });
    fetchMock.mockReset();
    fetchMock
      .mockResolvedValueOnce(
        Response.json({ items: Array.from({ length: 2000 }, (_, i) => key(i)), total: 2001 }),
      )
      .mockResolvedValueOnce(Response.json({ items: [key(2000)], total: 2001 }));
    const listed = await api.apiKeys("acme", "openai");
    expect(listed.items).toHaveLength(2001);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const second = new URL(String(fetchMock.mock.calls[1]![0]), "http://x");
    expect(second.searchParams.get("offset")).toBe("2000");
  });

  it("has a case for every client method", () => {
    expect(Object.keys(CASES).sort()).toEqual(Object.keys(api).sort());
  });

  it.each(Object.entries(CASES))(
    "%s sends the documented request",
    async (_name, [invoke, want]) => {
      const call = await sent(invoke);
      expect({ query: {}, body: undefined, ...want }).toEqual(call);
    },
  );

  it.each(Object.entries(CASES))(
    "%s targets a route of the OpenAPI snapshot",
    async (_name, [invoke]) => {
      const call = await sent(invoke);
      const route = routes.find((r) => r.method === call.method && r.pattern.test(call.path));
      expect(route, `${call.method} ${call.path}`).toBeDefined();
    },
  );

  it("requires the fields Explore and Overview read from critical responses", () => {
    const query = responseSchema("/api/v1/orgs/{org}/query", "get");
    expect(query.required).toEqual(
      expect.arrayContaining([
        "measure",
        "dimensions",
        "start",
        "end",
        "interval",
        "source",
        "buckets",
        "series",
        "total",
      ]),
    );
    expect(responseSchema("/api/v1/orgs/{org}/queries", "get").required).toEqual(["results"]);
    const summary = responseSchema(
      "/api/v1/orgs/{org}/providers/{provider}/months/{month}/summary",
      "get",
    );
    expect(summary.required).toEqual(expect.arrayContaining(["month", "total", "previous_total"]));
    expect(summary.properties?.byok_total).toBeDefined();
    expect(
      responseSchema("/api/v1/orgs/{org}/providers/{provider}/months/{month}/usage", "get")
        .required,
    ).toEqual(expect.arrayContaining(["dimension", "allocated", "rows"]));
  });

  it("calls every route of the snapshot except the technical probes", async () => {
    const technical = new Set(["GET /health", "GET /live", "GET /ready"]);
    const reached = new Set<string>();
    for (const [invoke] of Object.values(CASES)) {
      const call = await sent(invoke);
      const route = routes.find((r) => r.method === call.method && r.pattern.test(call.path));
      if (route) reached.add(`${route.method} ${route.template}`);
    }
    const unreached = routes
      .map((r) => `${r.method} ${r.template}`)
      .filter((key) => !reached.has(key) && !technical.has(key));
    expect(unreached).toEqual([]);
  });
});
