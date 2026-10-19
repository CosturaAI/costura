/** Connection fixtures: accounts, connections, provider info, runs and setup states. */

import type {
  Account,
  Connection,
  ProviderInfo,
  Run,
  Schedule,
  SchedulerRun,
  Setup,
} from "@/lib/api";

import { MONTH, OTHER_PROVIDER, PROVIDER } from "./common";

export const runs: Run[] = [
  {
    id: 10,
    provider: PROVIDER,
    provider_account_id: 1,
    provider_account_label: "Anthropic",
    endpoint: "allocation",
    status: "succeeded",
    window_start: "2026-08-01T00:00:00+00:00",
    window_end: "2026-09-01T00:00:00+00:00",
    started_at: "2026-09-14T12:00:00+00:00",
    finished_at: "2026-09-14T12:00:03+00:00",
    duration_seconds: 3.2,
    pages_fetched: 0,
    raw_results: 120,
    rows_upserted: 1201,
    error: null,
  },
  {
    id: 8,
    provider: PROVIDER,
    provider_account_id: 1,
    provider_account_label: "Anthropic",
    endpoint: "usage_report_messages",
    status: "failed",
    window_start: "2026-08-01T00:00:00+00:00",
    window_end: "2026-09-01T00:00:00+00:00",
    started_at: "2026-09-14T11:00:00+00:00",
    finished_at: "2026-09-14T11:00:01+00:00",
    duration_seconds: 1.0,
    pages_fetched: 0,
    raw_results: 0,
    rows_upserted: 0,
    error:
      "AnthropicApiError: Anthropic request failed: status=400 body='Cannot specify more than 5 group_by[] dimensions'",
  },
];

export const openRouterRun: Run = {
  ...runs[0]!,
  id: 11,
  provider: OTHER_PROVIDER,
  endpoint: "analytics_cost",
  started_at: "2026-09-14T13:00:00+00:00",
  finished_at: "2026-09-14T13:00:02+00:00",
};

const schedule: Schedule = {
  last_run_id: 7,
  last_run_at: "2026-09-14T06:02:00+00:00",
  last_finished_at: "2026-09-14T06:04:10+00:00",
  status: "succeeded",
  trigger: "scheduler",
  error: null,
  failed_steps: [],
  next_run_at: "2026-09-15T06:00:00+00:00",
  schedule_at: "06:00",
};

/** The single account behind `connection`: one console, labelled after the provider. */
export const anthropicAccount: Account = {
  id: 1,
  provider: PROVIDER,
  label: "Anthropic",
  external_id: "org_redacted_main",
  connected: true,
  source: "stored",
  key_hint: "4321",
  last_validated_at: "2026-09-14T09:00:00+00:00",
  last_error: null,
  schedule,
  first_sync_run_id: null,
  seat_price_usd: null,
  include_included_in_business: null,
  settings_effective_from: null,
};

/** A second Anthropic console connected to the same organization. */
export const secondAnthropicAccount: Account = {
  ...anthropicAccount,
  id: 4,
  label: "Research",
  external_id: "org_redacted_second",
  key_hint: "cond",
};

const openRouterAccount: Account = {
  id: 2,
  provider: OTHER_PROVIDER,
  label: "OpenRouter",
  external_id: null,
  connected: true,
  source: "stored",
  key_hint: "or99",
  last_validated_at: "2026-09-14T09:30:00+00:00",
  last_error: null,
  schedule,
  first_sync_run_id: null,
  seat_price_usd: null,
  include_included_in_business: null,
  settings_effective_from: null,
};

export const connection: Connection = {
  provider: PROVIDER,
  connected: true,
  source: "stored",
  key_hint: "4321",
  last_validated_at: "2026-09-14T09:00:00+00:00",
  last_error: null,
  writes_enabled: true,
  secret_key_configured: true,
  first_sync_run_id: null,
  schedule,
  accounts: [anthropicAccount],
};

/** Both consoles of Anthropic connected. */
export const connectionWithTwoAccounts: Connection = {
  ...connection,
  accounts: [anthropicAccount, secondAnthropicAccount],
};

const neverRan: Schedule = {
  ...schedule,
  last_run_id: null,
  last_run_at: null,
  last_finished_at: null,
  status: null,
  trigger: null,
};

export const connectionFromEnvironment: Connection = {
  ...connection,
  source: "environment",
  key_hint: "env9",
  last_validated_at: null,
  schedule: neverRan,
  accounts: [
    {
      ...anthropicAccount,
      external_id: null,
      source: "environment",
      key_hint: "env9",
      last_validated_at: null,
      schedule: neverRan,
    },
  ],
};

export const notConnected: Connection = {
  ...connectionFromEnvironment,
  connected: false,
  source: null,
  key_hint: null,
  schedule: { ...neverRan, next_run_at: null },
  accounts: [],
};

export const anthropicInfo: ProviderInfo = {
  provider: PROVIDER,
  connection_type: "provider_api",
  label: "Anthropic",
  vendor: "Anthropic",
  surface: "Claude Platform",
  key_label: "admin key",
  key_prefix: "sk-ant-admin",
  console_label: "Anthropic Console",
  console_url: "https://console.anthropic.com/settings/admin-keys",
  env_var: "ANTHROPIC_ADMIN_KEY",
  attribution: "token_share",
  experimental: false,
  connected: true,
  source: "stored",
  key_hint: "4321",
  last_validated_at: "2026-09-14T09:00:00+00:00",
  last_error: null,
  last_run: runs[0]!,
  accounts: [anthropicAccount],
};

export const openRouterInfo: ProviderInfo = {
  provider: OTHER_PROVIDER,
  connection_type: "provider_api",
  label: "OpenRouter",
  vendor: "OpenRouter",
  surface: "OpenRouter",
  key_label: "management key",
  key_prefix: "sk-or-v1-",
  console_label: "OpenRouter console",
  console_url: "https://openrouter.ai/settings/management-keys",
  env_var: "OPENROUTER_ADMIN_KEY",
  attribution: "direct",
  experimental: false,
  connected: true,
  source: "stored",
  key_hint: "or99",
  last_validated_at: "2026-09-14T09:30:00+00:00",
  last_error: null,
  last_run: openRouterRun,
  accounts: [openRouterAccount],
};

/** Both registered providers connected, as `GET /orgs/{org}/providers` answers. */
export const providers: ProviderInfo[] = [anthropicInfo, openRouterInfo];

/** Only Anthropic connected; OpenRouter registered but without a key. */
export const providersOneConnected: ProviderInfo[] = [
  anthropicInfo,
  {
    ...openRouterInfo,
    connected: false,
    source: null,
    key_hint: null,
    last_validated_at: null,
    last_run: null,
  },
];

export const providersNoneConnected: ProviderInfo[] = providers.map((p) => ({
  ...p,
  connected: false,
  source: null,
  key_hint: null,
  last_validated_at: null,
  last_run: null,
  accounts: [],
}));

/** First sync of Anthropic in progress: inventory done, the cost report of the current month
 * being fetched. */
export const runningRun: SchedulerRun = {
  id: 31,
  provider: PROVIDER,
  provider_account_id: 1,
  provider_account_label: "Anthropic",
  trigger: "connect",
  status: "running",
  started_at: "2026-09-14T20:00:00+00:00",
  finished_at: null,
  error: null,
  steps: [
    {
      step: "inventory",
      month: null,
      status: "ok",
      attempts: 1,
      detail: "3 workspaces, 12 keys, 4 users",
      duration_seconds: 2.1,
    },
    {
      step: "cost",
      month: "2026-08",
      status: "ok",
      attempts: 1,
      detail: "1201 rows",
      duration_seconds: 14.8,
    },
  ],
};

export const succeededRun: SchedulerRun = {
  ...runningRun,
  id: 32,
  status: "succeeded",
  finished_at: "2026-09-14T20:01:30+00:00",
  steps: [
    ...runningRun.steps,
    {
      step: "cost",
      month: "2026-09",
      status: "ok",
      attempts: 1,
      detail: "300 rows",
      duration_seconds: 6.2,
    },
    {
      step: "allocate",
      month: "2026-08",
      status: "ok",
      attempts: 1,
      detail: null,
      duration_seconds: 1.1,
    },
  ],
};

export const failedRun: SchedulerRun = {
  ...runningRun,
  id: 33,
  status: "failed",
  finished_at: "2026-09-14T20:00:40+00:00",
  error: "1 of 2 steps failed",
  steps: [
    runningRun.steps[0]!,
    {
      step: "cost",
      month: "2026-08",
      status: "failed",
      attempts: 3,
      detail: "Anthropic request failed: status=429",
      duration_seconds: 31.0,
    },
  ],
};

/** No provider has a key yet: the welcome page shows one connect card per provider. */
export const setupConnect: Setup = {
  state: "connect",
  providers: providersNoneConnected,
  runs: [],
  first_month: null,
  dismissed_at: null,
  writes_enabled: true,
  worker_seen_at: null,
  secret_ready: true,
  needs_pricing: false,
};

/** Anthropic connected, its first run in progress, OpenRouter still without a key. */
export const setupSyncing: Setup = {
  ...setupConnect,
  state: "syncing",
  providers: providersOneConnected,
  runs: [runningRun],
};

export const setupSyncingFailed: Setup = { ...setupSyncing, runs: [failedRun] };

/** Both providers connected and a month with cost lines: `/` lands on that month's overview. */
export const setupReady: Setup = {
  ...setupConnect,
  state: "ready",
  providers,
  runs: [succeededRun, { ...succeededRun, id: 34, provider: OTHER_PROVIDER }],
  first_month: MONTH,
};

export const openRouterConnection: Connection = {
  ...connection,
  provider: OTHER_PROVIDER,
  key_hint: "or99",
  accounts: [openRouterAccount],
  schedule: {
    ...connection.schedule,
    last_run_id: 8,
    last_run_at: "2026-09-14T06:10:00+00:00",
    last_finished_at: "2026-09-14T06:12:00+00:00",
    status: "failed",
    failed_steps: ["usage 2026-09"],
  },
};
