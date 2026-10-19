/**
 * Provider connections and accounts, credit prices, setup, sync runs and sync now.
 */

import type { Schema } from "./schema";
import { get, scope, send } from "./transport";

export type AnomalySettings = Schema<"AnomalySettingsOut">;

export type RunStatus = "queued" | "running" | "succeeded" | "failed" | "skipped";

export type Run = Omit<Schema<"RunOut">, "status"> & {
  status: RunStatus;
};

export type Schedule = Omit<Schema<"ScheduleOut">, "status"> & {
  status: RunStatus | null;
};

/** One account of a provider and the state of its key. The provider-level
 * `Connection` and `ProviderInfo` summarize these: connected when any account is. */
export type Account = Omit<Schema<"AccountOut">, "schedule"> & {
  schedule: Schedule;
};

export type CreditPrice = Schema<"CreditPriceOut">;

export type Connection = Omit<Schema<"ConnectionOut">, "schedule" | "accounts"> & {
  schedule: Schedule;
  accounts: Account[];
};

export type SyncStep = Omit<Schema<"SyncStepOut">, "status"> & {
  status: "ok" | "failed" | "skipped";
};

export type SchedulerRunStatus = RunStatus;

/** One scheduler cycle for one provider; queued until it owns the lock, then running. */
export type SchedulerRun = Omit<Schema<"SchedulerRunOut">, "status" | "steps"> & {
  status: SchedulerRunStatus;
  steps: SyncStep[];
};

/** Entry of the 202 answer to `POST .../sync`: the run is queued, progress comes from `setup`. */
export type SyncResult = Omit<Schema<"SyncResultOut">, "status" | "steps"> & {
  status: SchedulerRunStatus;
  steps: SyncStep[];
};

/** One scheduler run per provider the POST covered: one under a concrete provider, one per
 * connected provider under `all`. */
type SyncResults = { results: SyncResult[] };

type SetupState = "connect" | "syncing" | "ready" | "needs_pricing";

/**
 * First-run state of an organization: `connect` while no provider has a key, `ready` once a
 * month with cost lines exists, `syncing` in between (including a failed first run).
 */
export type Setup = Omit<Schema<"SetupOut">, "state" | "providers" | "runs"> & {
  state: SetupState;
  providers: ProviderInfo[];
  runs: SchedulerRun[];
};

/** Registry facts plus this organization's connection state, one entry per provider. */
export type ProviderInfo = Omit<
  Schema<"ProviderOut">,
  "connection_type" | "attribution" | "last_run" | "accounts"
> & {
  connection_type: "provider_api";
  attribution: "token_share" | "direct" | "key_attributed";
  last_run: Run | null;
  accounts: Account[];
};

type CopilotLogins = { account_id: number; logins: Record<string, string> };

export const connectionsApi = {
  providers: (org: string) => get<ProviderInfo[]>(`/orgs/${encodeURIComponent(org)}/providers`),
  setup: (org: string) => get<Setup>(`/orgs/${encodeURIComponent(org)}/setup`),
  dismissSetup: (org: string) =>
    send<Setup>("POST", `/orgs/${encodeURIComponent(org)}/setup/dismiss`),
  /** Removes the stored keys, the dismissed flag and every synced row of the organization;
   * keys read from environment variables stay, so the answer can be `syncing`. */
  resetSetup: (org: string) => send<Setup>("POST", `/orgs/${encodeURIComponent(org)}/setup/reset`),
  runs: (org: string, provider: string, limit = 50, endpoint?: string) =>
    get<{ runs: Run[]; as_of?: string | null }>(`${scope(org, provider)}/runs`, {
      limit,
      endpoint,
    }),
  connection: (org: string, provider: string) =>
    get<Connection>(`${scope(org, provider)}/connection`),
  /** Connects the provider's only account (or its first); 409 once it has several. */
  connect: (
    org: string,
    provider: string,
    adminKey: string,
    settings?: {
      seat_price_usd?: string;
      include_included_in_business?: boolean;
      workspace_id?: string;
    },
  ) =>
    send<Connection>("PUT", `${scope(org, provider)}/connection`, {
      admin_key: adminKey,
      ...settings,
    }),
  disconnect: (org: string, provider: string) =>
    send<Connection>("DELETE", `${scope(org, provider)}/connection`),
  accounts: (org: string, provider: string) =>
    get<{ accounts: Account[] }>(`${scope(org, provider)}/accounts`),
  /** Connects one more account of the provider; the label defaults to what the provider
   * reports for the key. 422 when the key already connects an account or the label is taken. */
  addAccount: (
    org: string,
    provider: string,
    adminKey: string,
    label?: string,
    settings?: {
      seat_price_usd?: string;
      include_included_in_business?: boolean;
      workspace_id?: string;
    },
  ) =>
    send<Account>("POST", `${scope(org, provider)}/accounts`, {
      admin_key: adminKey,
      label: label || undefined,
      ...settings,
    }),
  renameAccount: (
    org: string,
    provider: string,
    accountId: number,
    label: string,
    settings?: { seat_price_usd: string; include_included_in_business: boolean },
  ) =>
    send<Account>("PATCH", `${scope(org, provider)}/accounts/${accountId}`, {
      label,
      ...settings,
    }),
  replaceAccountKey: (org: string, provider: string, accountId: number, adminKey: string) =>
    send<Account>("PUT", `${scope(org, provider)}/accounts/${accountId}/key`, {
      admin_key: adminKey,
    }),
  disconnectAccount: (org: string, provider: string, accountId: number) =>
    send<Account>("DELETE", `${scope(org, provider)}/accounts/${accountId}/key`),
  /** Removes the account with every row synced under it; 409 while a sync of it runs. */
  removeAccount: (org: string, provider: string, accountId: number) =>
    send<void>("DELETE", `${scope(org, provider)}/accounts/${accountId}`),
  creditPrices: (org: string, accountId: number) =>
    get<CreditPrice[]>(`/orgs/${encodeURIComponent(org)}/accounts/${accountId}/credit-prices`),
  addCreditPrice: (
    org: string,
    accountId: number,
    body: { effective_from: string; price_per_credit: string },
  ) =>
    send<CreditPrice>(
      "POST",
      `/orgs/${encodeURIComponent(org)}/accounts/${accountId}/credit-prices`,
      body,
    ),
  deleteCreditPrice: (org: string, accountId: number, priceId: number) =>
    send<void>(
      "DELETE",
      `/orgs/${encodeURIComponent(org)}/accounts/${accountId}/credit-prices/${priceId}`,
    ),
  syncNow: (org: string, provider: string, account?: number) =>
    send<SyncResults>(
      "POST",
      `${scope(org, provider)}/sync${account === undefined ? "" : `?account=${account}`}`,
    ),
  anomalySettings: (org: string) =>
    get<AnomalySettings>(`/orgs/${encodeURIComponent(org)}/anomaly-settings`),
  saveAnomalySettings: (org: string, body: AnomalySettings) =>
    send<AnomalySettings>("PUT", `/orgs/${encodeURIComponent(org)}/anomaly-settings`, body),
  /** GitHub login -> e-mail table of a Copilot account; the next inventory sync applies it. */
  copilotLogins: (org: string, accountId: number) =>
    get<CopilotLogins>(`${scope(org, "copilot")}/accounts/${accountId}/logins`),
  setCopilotLogins: (org: string, accountId: number, logins: Record<string, string>) =>
    send<CopilotLogins>("PUT", `${scope(org, "copilot")}/accounts/${accountId}/logins`, {
      logins,
    }),
};
