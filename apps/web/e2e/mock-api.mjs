import { createServer } from "node:http";

/**
 * Stand-in for the Costura API behind the production Next.js server under Playwright. Answers
 * the reads the shell and the audited pages issue with fixed data; writes are recorded and
 * listed at `/__e2e/requests` so a spec can assert which provider a form targeted without any
 * external side effect. The list is append-only because specs run in parallel: a spec notes
 * its length before acting and reads the tail. The inbox routes are the exception:
 * they keep the opt-in and the read marks in memory so the bell flow can be replayed;
 * `DELETE /__e2e/requests` resets that inbox state. Invitations are stateful for the same reason: the
 * owner creates one, and a second identity claims it through the link.
 *
 * Two identities: `Bearer e2e-session` is the owner e2e@example.com, `Bearer e2e-invitee` is
 * newcomer@example.com, who belongs to nothing until an invitation is claimed.
 */

/** `MOCK_API_PORT` lets the schema conformance test run its own copy beside Playwright's. */
const port = Number(process.env.MOCK_API_PORT ?? 3200);
const MONTH = "2026-08";
const PREVIOUS_MONTH = "2026-07";
const DAYS = Array.from({ length: 31 }, (_, i) => `${MONTH}-${String(i + 1).padStart(2, "0")}`);

const organizations = [
  { slug: "default", name: "Default organization", is_demo: false, role: "owner" },
  { slug: "acme", name: "Acme", is_demo: false, role: "owner" },
  { slug: "codex", name: "Codex test", is_demo: false, role: "owner" },
  { slug: "demo", name: "Sample organization", is_demo: true, role: null },
];

const run = {
  id: 10,
  provider: "anthropic",
  provider_account_id: 1,
  provider_account_label: "Anthropic",
  endpoint: "cost_report",
  status: "succeeded",
  window_start: `${MONTH}-01T00:00:00+00:00`,
  window_end: "2026-09-01T00:00:00+00:00",
  started_at: "2026-09-14T12:00:00+00:00",
  finished_at: "2026-09-14T12:00:03+00:00",
  duration_seconds: 3.2,
  pages_fetched: 1,
  raw_results: 120,
  rows_upserted: 1201,
  error: null,
};

const registry = [
  {
    provider: "anthropic",
    connection_type: "provider_api",
    label: "Anthropic",
    vendor: "Anthropic",
    surface: "Claude Platform",
    key_label: "admin key",
    key_prefix: "sk-ant-admin",
    console_label: "Anthropic Console",
    console_url: "https://console.anthropic.com",
    env_var: "ANTHROPIC_ADMIN_KEY",
    attribution: "token_share",
    experimental: false,
  },
  {
    provider: "openrouter",
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
  },
  {
    provider: "openai",
    connection_type: "provider_api",
    label: "OpenAI",
    vendor: "OpenAI",
    surface: "OpenAI Platform",
    key_label: "admin key",
    key_prefix: "sk-admin-",
    console_label: "OpenAI platform",
    console_url: "https://platform.openai.com/settings/organization/admin-keys",
    env_var: "OPENAI_ADMIN_KEY",
    attribution: "key_attributed",
    experimental: false,
  },
  {
    provider: "cursor",
    connection_type: "provider_api",
    label: "Cursor",
    vendor: "Cursor",
    surface: "Cursor",
    key_label: "team API key",
    key_prefix: "key_",
    console_label: "Cursor dashboard",
    console_url: "https://cursor.com/dashboard?tab=integrations",
    env_var: "CURSOR_API_KEY",
    attribution: "direct",
    experimental: false,
  },
];
const codexRegistry = {
  provider: "codex",
  connection_type: "provider_api",
  label: "Codex",
  vendor: "OpenAI",
  surface: "Codex",
  key_label: "Admin API key",
  key_prefix: "sk-admin-",
  console_label: "OpenAI Admin Console",
  console_url: "https://chatgpt.com/admin",
  env_var: "CODEX_ADMIN_KEY",
  attribution: "direct",
  experimental: false,
};

const KEY_HINTS = {
  anthropic: "1234",
  codex: "c0de",
  openrouter: "5678",
  openai: "9abc",
  cursor: "cdef",
};
const COST_ENDPOINTS = {
  anthropic: "cost_report",
  codex: "codex_workspace_usage",
  openrouter: "analytics_cost",
  openai: "costs",
  cursor: "filtered_usage_events",
};

/** The default account of each provider carries the provider's name. */
const ACCOUNT_IDS = { anthropic: 1, openrouter: 2, openai: 3, cursor: 5, codex: 7 };
const ACCOUNT_LABELS = {
  anthropic: "Anthropic",
  codex: "Codex",
  openrouter: "OpenRouter",
  openai: "OpenAI",
  cursor: "Cursor",
};
/** `acme` connected a second Anthropic console; its rows carry the "Research" name. */
const RESEARCH_ACCOUNT = { id: 4, provider: "anthropic", label: "Research" };
const accountOf = (provider) => ({
  provider_account_id: ACCOUNT_IDS[provider],
  provider_account_label: ACCOUNT_LABELS[provider],
});

const connectedState = (provider) => ({
  connected: true,
  source: "stored",
  key_hint: KEY_HINTS[provider],
  last_validated_at: "2026-08-31T10:00:00+00:00",
  last_error: null,
  last_run: {
    ...run,
    provider,
    ...accountOf(provider),
    endpoint: COST_ENDPOINTS[provider],
  },
});

/** A provider whose key was removed after it synced: months exist, no credential remains. */
const disconnectedState = (provider) => ({
  connected: false,
  source: null,
  key_hint: null,
  last_validated_at: null,
  last_error: null,
  last_run: {
    ...run,
    provider,
    ...accountOf(provider),
    endpoint: COST_ENDPOINTS[provider],
  },
});

/** `acme`: all three stored (three disconnect forms). `default`: OpenRouter disconnected with data.
 * `demo`: the sample organization, nothing connected. */
function providersOf(org) {
  const specs = org === "codex" ? [codexRegistry] : registry;
  return specs.map((spec) => {
    const connected =
      org === "acme" || org === "codex" || (org === "default" && spec.provider === "anthropic");
    const state = (connected ? connectedState : disconnectedState)(spec.provider);
    return { ...spec, ...state, accounts: accountsOf(org, spec.provider, state) };
  });
}

const schedule = {
  last_run_id: null,
  last_run_at: null,
  last_finished_at: null,
  status: null,
  trigger: null,
  error: null,
  failed_steps: [],
  next_run_at: "2026-09-16T06:00:00Z",
  schedule_at: "06:00",
};

/** One account per provider, two for Anthropic in `acme`; a disconnected provider keeps its
 * account without a key, so its months stay reachable. */
function accountsOf(org, provider, state) {
  const account = (id, label, externalId) => ({
    id,
    provider,
    label,
    external_id: externalId,
    connected: state.connected,
    source: state.source,
    key_hint: state.key_hint,
    last_validated_at: state.last_validated_at,
    last_error: null,
    schedule,
    first_sync_run_id: null,
    seat_price_usd: provider === "cursor" ? "40.00000000" : null,
    include_included_in_business: provider === "cursor" ? true : null,
    settings_effective_from: provider === "cursor" ? "2026-09-18" : null,
  });
  const accounts = [
    account(
      ACCOUNT_IDS[provider],
      ACCOUNT_LABELS[provider],
      provider === "codex" ? "11111111-2222-4333-8444-555555555555" : null,
    ),
  ];
  if (org === "acme" && provider === RESEARCH_ACCOUNT.provider) {
    accounts.push(account(RESEARCH_ACCOUNT.id, RESEARCH_ACCOUNT.label, "org_research"));
  }
  return accounts;
}

function connectionOf(provider, known) {
  return {
    provider,
    connected: known?.connected ?? false,
    source: known?.source ?? null,
    key_hint: known?.key_hint ?? null,
    last_validated_at: known?.last_validated_at ?? null,
    last_error: null,
    writes_enabled: true,
    secret_key_configured: true,
    schedule,
    first_sync_run_id: null,
    accounts: known?.accounts ?? [],
  };
}

const zeroTokens = {
  uncached_input_tokens: 0,
  cache_creation_5m_tokens: 0,
  cache_creation_1h_tokens: 0,
  cache_read_tokens: 0,
  output_tokens: 0,
};

/** Cost-only attribution: dollars from the cost report, no usage lines behind them. */
const ZERO_TOKEN_ID = "key-zero-tokens";
const ZERO_TOKEN_NAME = "zero-token-key";
const zeroTokenRow = {
  key: ZERO_TOKEN_ID,
  label: `${ZERO_TOKEN_NAME} (${ZERO_TOKEN_ID})`,
  provider: "anthropic",
  ...accountOf("anthropic"),
  details: {
    hint: "sk-ant-api03-...zero",
    workspace: "Platform (wrkspc_platform)",
    created_by: "bob@example.com",
    status: "active",
  },
  amount: "123.45",
  share: "17.63",
  tokens: zeroTokens,
  byok_amount: null,
  total_tokens: 0,
  web_search_requests: 0,
  person: null,
};

const batchRow = {
  ...zeroTokenRow,
  key: "apikey_demo_batch",
  label: "batch-ingest (apikey_demo_batch)",
  provider_account_id: RESEARCH_ACCOUNT.id,
  provider_account_label: RESEARCH_ACCOUNT.label,
  details: { ...zeroTokenRow.details, hint: "sk-ant-api03-...btch" },
  amount: "576.55",
  share: "82.37",
  tokens: { ...zeroTokens, uncached_input_tokens: 20000, output_tokens: 10000 },
  total_tokens: 30000,
};

const modelRow = {
  key: "claude-sonnet-4",
  label: "claude-sonnet-4",
  provider: "anthropic",
  provider_account_id: null,
  provider_account_label: null,
  details: {},
  amount: "123.45",
  share: "100.00",
  tokens: zeroTokens,
  byok_amount: null,
  total_tokens: 0,
  web_search_requests: 0,
  person: null,
};

/** Two providers, so the overview's provider strip has a comparison to draw. */
const providerRows = [
  {
    key: "anthropic",
    label: "Anthropic",
    provider: "anthropic",
    provider_account_id: null,
    provider_account_label: null,
    details: {},
    amount: "576.55",
    share: "82.36",
    tokens: zeroTokens,
    byok_amount: null,
    total_tokens: 30000,
    web_search_requests: 0,
    person: null,
  },
  {
    key: "openrouter",
    label: "OpenRouter",
    provider: "openrouter",
    provider_account_id: null,
    provider_account_label: null,
    details: {},
    amount: "123.45",
    share: "17.64",
    tokens: zeroTokens,
    byok_amount: null,
    total_tokens: 0,
    web_search_requests: 0,
    person: null,
  },
];

const PERSON_EMAIL = "ana@example.com";
/** ana@example.com on two providers, the aggregated person page's subject. */
const person = {
  email: PERSON_EMAIL,
  identities: [
    {
      provider: "anthropic",
      external_id: "user_ana",
      role: "admin",
      added_at: "2026-01-01T00:00:00+00:00",
      missing: false,
      keys_created: 1,
    },
    {
      provider: "openai",
      external_id: "user-ana",
      role: "owner",
      added_at: "2026-03-01T00:00:00+00:00",
      missing: false,
      keys_created: 2,
    },
  ],
  providers: ["anthropic", "openai"],
};

const personRow = {
  ...modelRow,
  key: PERSON_EMAIL,
  label: PERSON_EMAIL,
  provider: null,
  details: { kind: "person", providers: "anthropic,openai" },
  amount: "700.00",
  share: "100.00",
  person: PERSON_EMAIL,
};

function filterClauses(query) {
  return query.getAll("f").flatMap((raw) => {
    const parts = raw.split(":");
    const opIndex = parts[0] === "tag" ? 2 : 1;
    if (parts.length <= opIndex + 1) return [];
    return [
      {
        dimension: parts.slice(0, opIndex).join(":"),
        op: parts[opIndex],
        values: parts
          .slice(opIndex + 1)
          .join(":")
          .split(",")
          .filter(Boolean),
      },
    ];
  });
}

function filterMatches(value, clause) {
  const candidate = value == null ? "" : String(value).toLowerCase();
  const values = clause.values.map((item) => item.toLowerCase());
  if (clause.op === "exists") return candidate !== "";
  if (clause.op === "not_exists") return candidate === "";
  if (clause.op === "is" || clause.op === "one_of") return values.includes(candidate);
  if (clause.op === "is_not" || clause.op === "not_one_of") return !values.includes(candidate);
  if (clause.op === "contains") return candidate.includes(values[0] ?? "");
  if (clause.op === "not_contains") return !candidate.includes(values[0] ?? "");
  return true;
}

function filterRows(rows, query, dimension) {
  return filterClauses(query)
    .filter((clause) => clause.dimension === dimension)
    .reduce((current, clause) => current.filter((row) => filterMatches(row.key, clause)), rows);
}

function usageFor(query, provider) {
  const by = query.get("by") ?? "api_key";
  if (query.has("person")) {
    if (query.get("person") !== PERSON_EMAIL) {
      return { dimension: by, allocated: true, cost_total: "0.00", rows: [] };
    }
    const rows =
      by === "person" ? [personRow] : by === "provider" ? providerRows : [batchRow, modelRow];
    return { dimension: by, allocated: true, cost_total: "700.00", rows };
  }
  if (by === "person") {
    return { dimension: by, allocated: true, cost_total: "700.00", rows: [personRow] };
  }
  if (query.get("api_key") === ZERO_TOKEN_ID) {
    return by === "api_key"
      ? { dimension: by, allocated: true, cost_total: "123.45", rows: [zeroTokenRow] }
      : { dimension: by, allocated: true, cost_total: "123.45", rows: [modelRow] };
  }
  if (query.has("api_key")) return { dimension: by, allocated: true, cost_total: "0.00", rows: [] };
  const rows =
    by === "api_key"
      ? [batchRow, zeroTokenRow]
      : by === "model"
        ? [modelRow]
        : by === "provider"
          ? providerRows
          : [zeroTokenRow];
  const filtered = filterRows(rows, query, by);
  const scoped =
    provider === "all" ? filtered : filtered.filter((row) => row.provider === provider);
  return { dimension: by, allocated: true, cost_total: "700.00", rows: scoped };
}

/** One key up (new this month), one down (stopped): the two cases the card labels. */
function moversFor(query, provider) {
  const by = query.get("by") ?? "api_key";
  const rows = [
    {
      key: batchRow.key,
      label: batchRow.label,
      provider: "anthropic",
      provider_account_id: RESEARCH_ACCOUNT.id,
      provider_account_label: RESEARCH_ACCOUNT.label,
      amount: "576.55",
      previous_amount: "0.00",
      delta: "576.55",
      change_percent: null,
      is_new: true,
      is_gone: false,
    },
    {
      key: ZERO_TOKEN_ID,
      label: zeroTokenRow.label,
      provider: "anthropic",
      ...accountOf("anthropic"),
      amount: "123.45",
      previous_amount: "300.00",
      delta: "-176.55",
      change_percent: "-58.85",
      is_new: false,
      is_gone: false,
    },
  ];
  const scoped = provider === "all" ? rows : rows.filter((row) => row.provider === provider);
  const { previous_start, previous_end } = periodOf(query);
  return {
    dimension: by,
    allocated: true,
    previous_month: PREVIOUS_MONTH,
    previous_start,
    previous_end,
    rows: scoped,
  };
}

function seriesFor(query) {
  const by = query.get("by") ?? "api_key";
  const values = DAYS.map((_, i) => (i === 0 ? "123.45" : "0.00"));
  return {
    month: MONTH,
    dimension: by,
    source: "allocated",
    days: DAYS,
    series: [
      {
        key: ZERO_TOKEN_ID,
        label: zeroTokenRow.label,
        provider: "anthropic",
        values,
        total: "123.45",
      },
    ],
    other: null,
    total: values,
    month_total: "123.45",
  };
}

function queryFor(query, org) {
  const measure = query.get("measure") ?? "billed_usd";
  const dimensions = (query.get("dimensions") ?? "").split(",").filter(Boolean);
  const dimension = dimensions[0];
  const tagged = dimension?.startsWith("tag:");
  const sourceRows = tagged
    ? [
        { key: "Backend", label: "Backend", provider: "anthropic", billed: 576.55, tokens: 30000 },
        { key: null, label: "No team", provider: "anthropic", billed: 123.45, tokens: 0 },
      ]
    : dimension === "api_key"
      ? [
          {
            key: batchRow.key,
            label: batchRow.label,
            provider: batchRow.provider,
            billed: 576.55,
            tokens: 30000,
          },
          {
            key: zeroTokenRow.key,
            label: zeroTokenRow.label,
            provider: zeroTokenRow.provider,
            billed: 123.45,
            tokens: 0,
          },
        ]
      : dimension === "model"
        ? [
            {
              key: org === "codex" ? "gpt-5" : modelRow.key,
              label: org === "codex" ? "GPT-5" : modelRow.label,
              provider: org === "codex" ? "codex" : modelRow.provider,
              billed: 700,
              tokens: 30000,
            },
          ]
        : dimension === "provider"
          ? [
              {
                key: "anthropic",
                label: "Anthropic",
                provider: "anthropic",
                billed: 576.55,
                tokens: 30000,
              },
              {
                key: "openrouter",
                label: "OpenRouter",
                provider: "openrouter",
                billed: 123.45,
                tokens: 0,
              },
            ]
          : dimension === "person"
            ? [
                {
                  key: PERSON_EMAIL,
                  label: PERSON_EMAIL,
                  provider: null,
                  billed: 700,
                  tokens: 30000,
                },
              ]
            : [
                {
                  key: batchRow.key,
                  label: batchRow.label,
                  provider: "anthropic",
                  billed: 700,
                  tokens: 30000,
                },
              ];
  const valueFor = (row) => {
    if (measure === "billed_usd") return row.billed.toFixed(2);
    if (measure === "estimated_usd") return (row.billed / 10).toFixed(2);
    if (measure === "tokens_total") return row.tokens;
    if (measure === "tokens_input") return Math.round(row.tokens * (2 / 3));
    if (measure === "tokens_output") return Math.round(row.tokens / 3);
    return 0;
  };
  const filteredRows = filterRows(sourceRows, query, dimension);
  const series = filteredRows.map((row) => {
    const value = valueFor(row);
    return {
      keys: { [dimension ?? "api_key"]: row.key },
      labels: { [dimension ?? "api_key"]: row.label },
      provider: row.provider,
      values: [value],
      total: value,
    };
  });
  const totalValue = filteredRows.reduce((sum, row) => sum + Number(valueFor(row)), 0);
  const total =
    measure === "billed_usd" || measure === "estimated_usd" ? totalValue.toFixed(2) : totalValue;
  const projectionMode = query.get("projection") ?? "none";
  const horizon = Number(query.get("horizon") ?? 4);
  const lookback = Number(query.get("lookback") ?? 8);
  return {
    measure,
    dimensions,
    start: query.get("start"),
    end: query.get("end"),
    interval: query.get("interval") ?? "day",
    source: tagged ? "allocated" : measure === "billed_usd" ? "allocated" : "usage",
    buckets: [query.get("start")],
    series,
    other: null,
    total: [total],
    comparison: null,
    projection:
      projectionMode === "linear"
        ? {
            mode: "linear",
            lookback,
            horizon,
            buckets: futureBuckets(query.get("end"), query.get("interval") ?? "day", horizon),
            anchor: total,
            values: Array.from({ length: horizon }, (_, index) =>
              measure === "billed_usd" || measure === "estimated_usd"
                ? (Number(total) + (index + 1) * 10).toFixed(2)
                : Number(total) + (index + 1) * 10,
            ),
          }
        : null,
  };
}

function futureBuckets(end, interval, count) {
  const cursor = new Date(`${end}T00:00:00Z`);
  if (interval === "month") {
    cursor.setUTCMonth(cursor.getUTCMonth() + 1, 1);
  } else if (interval === "week") {
    cursor.setUTCDate(cursor.getUTCDate() + (7 - ((cursor.getUTCDay() + 6) % 7)));
  } else {
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return Array.from({ length: count }, (_, index) => {
    const day = new Date(cursor);
    if (interval === "month") day.setUTCMonth(day.getUTCMonth() + index);
    else day.setUTCDate(day.getUTCDate() + index * (interval === "week" ? 7 : 1));
    return day.toISOString().slice(0, 10);
  });
}

function periodOf(query) {
  const start = query.get("start") ?? `${MONTH}-01`;
  const end = query.get("end") ?? `${MONTH}-31`;
  if (start === `${MONTH}-01` && end === `${MONTH}-31`) {
    return {
      start,
      end,
      previous_start: `${PREVIOUS_MONTH}-01`,
      previous_end: `${PREVIOUS_MONTH}-31`,
    };
  }
  const day = 86_400_000;
  const from = Date.parse(`${start}T00:00:00Z`);
  const length = Date.parse(`${end}T00:00:00Z`) - from + day;
  const iso = (time) => new Date(time).toISOString().slice(0, 10);
  return { start, end, previous_start: iso(from - length), previous_end: iso(from - day) };
}

function summaryFor(provider, query) {
  const total = { openrouter: "456.78", openai: "89.10" }[provider] ?? "700.00";
  const period = periodOf(query);
  return {
    month: MONTH,
    ...period,
    comparison_basis:
      period.start === `${MONTH}-01` && period.end === `${MONTH}-31`
        ? "full_month"
        : "preceding_period",
    currency: "USD",
    total,
    previous_month: PREVIOUS_MONTH,
    previous_total: null,
    change_percent: null,
    days_in_month: 31,
    days_with_data: 1,
    last_day_with_data: DAYS[0],
    complete_through: null,
    data_stale: false,
    detection_through: null,
    duplicate_accounts: [],
    daily_average: total,
    is_current_month: false,
    projected_total: null,
    top_keys_share: "100.00",
    top_key_count: 1,
    cache_read_share: "0.00",
    tokens: zeroTokens,
    allocation: null,
    provider_total: total,
    provider_matches: true,
    provider_difference: "0.00",
    currency_totals: null,
    byok_total: null,
  };
}

const zeroTokenKey = {
  limit_reported: false,
  creator_left: false,
  provider: "anthropic",
  ...accountOf("anthropic"),
  external_id: ZERO_TOKEN_ID,
  name: ZERO_TOKEN_NAME,
  partial_key_hint: "sk-ant-api03-...zero",
  workspace_external_id: "wrkspc_platform",
  workspace: "Platform (wrkspc_platform)",
  created_by_external_id: "user_bob",
  created_by: "bob@example.com",
  status: "active",
  created_at: "2026-01-02T00:00:00+00:00",
  expires_at: null,
  last_seen_at: "2026-09-14T12:00:00+00:00",
  missing_since: null,
  missing: false,
};

const longKey = {
  ...zeroTokenKey,
  external_id: "key-platform-billing-very-long-identifier",
  name: "Platform billing key with a very long display name that must wrap instead of widening the page",
  partial_key_hint: "sk-ant-api03-...long",
  status: "active",
};

const inventoryKeys = [zeroTokenKey, longKey];

const inventoryWorkspaces = [
  {
    provider: "anthropic",
    ...accountOf("anthropic"),
    external_id: "wrkspc_platform",
    name: "Platform",
    archived_at: null,
    admins: ["bob@example.com"],
    api_keys: 2,
    created_at: "2026-01-02T00:00:00+00:00",
    last_seen_at: "2026-09-14T12:00:00+00:00",
    missing_since: null,
    missing: false,
  },
];

const inventoryUsers = [
  {
    provider: "anthropic",
    external_id: "user_bob",
    email: "bob@example.com",
    role: "admin",
    kind: "user",
    added_at: "2026-01-02T00:00:00+00:00",
    last_seen_at: "2026-09-14T12:00:00+00:00",
    missing_since: null,
    missing: false,
    limit_reported: false,
  },
  {
    provider: "anthropic",
    ...accountOf("anthropic"),
    external_id: "svc_billing",
    email: "billing-bot",
    role: "service",
    kind: "service_account",
    added_at: "2026-01-02T00:00:00+00:00",
    last_seen_at: "2026-09-14T12:00:00+00:00",
    missing_since: null,
    missing: false,
    limit_reported: false,
  },
];

function inventoryItems(kind) {
  if (kind === "api-keys") return inventoryKeys;
  if (kind === "workspaces") return inventoryWorkspaces;
  return inventoryUsers;
}

const sampleRuns = [
  {
    id: 41,
    provider: "anthropic",
    provider_account_id: 1,
    provider_account_label: "Production",
    endpoint: "cost_report",
    status: "succeeded",
    window_start: "2026-08-01",
    window_end: "2026-08-31",
    started_at: "2026-08-31T12:00:00+00:00",
    finished_at: "2026-08-31T12:01:00+00:00",
    duration_seconds: 64,
    pages_fetched: 3,
    raw_results: 120,
    rows_upserted: 118,
    error: null,
  },
  {
    id: 42,
    provider: "anthropic",
    provider_account_id: 1,
    provider_account_label: "Production",
    endpoint: "usage_report_messages",
    status: "failed",
    window_start: "2026-08-01",
    window_end: "2026-08-31",
    started_at: "2026-08-31T12:05:00+00:00",
    finished_at: "2026-08-31T12:06:00+00:00",
    duration_seconds: 12,
    pages_fetched: 1,
    raw_results: 0,
    rows_upserted: 0,
    error: "ProviderError: the usage report timed out after three attempts",
  },
];

const sampleBudget = {
  id: 1,
  provider: "anthropic",
  scope_kind: "org",
  scope_id: "__org__",
  label: "Organization total",
  amount: "500.00",
  currency: "USD",
  thresholds: [80, 100],
  period: "month",
  created_at: "2026-08-01T00:00:00+00:00",
  updated_at: "2026-08-15T00:00:00+00:00",
};

const sampleBudgetStatus = {
  budget: sampleBudget,
  period_start: null,
  period_end: null,
  spent: "320.00",
  percent: "64.00",
  projected: "480.00",
  projected_percent: "96.00",
  thresholds: [
    { percent: 80, crossed_at: null },
    { percent: 100, crossed_at: null },
  ],
  highest_crossed: null,
  projection_exceeds: false,
  alerts: [],
};

const openAnomaly = {
  explanation:
    "zero-token-key spent 810.00 USD more than expected (133% over); claude-opus-4-1 accounts for 100% of the increase.",
  id: 7,
  provider: "anthropic",
  ...accountOf("anthropic"),
  series_kind: "api_key",
  series_id: ZERO_TOKEN_ID,
  label: zeroTokenRow.label,
  kind: "spike",
  day: `${MONTH}-11`,
  end_day: `${MONTH}-11`,
  ongoing: false,
  duration_days: 1,
  actual: "1420.00",
  expected: "610.00",
  upper_bound: "890.00",
  lower_bound: "330.00",
  baseline_method: "weekday",
  baseline_samples: 8,
  impact: "810.00",
  impact_percent: "132.79",
  impact_share: "12.40",
  total_actual: "1420.00",
  total_expected: "610.00",
  total_impact: "810.00",
  max_impact: "810.00",
  deviation: "2.89",
  severity: "high",
  currency: "USD",
  unit: "USD",
  status: "open",
  root_causes: [],
  owners: [
    { email: "ana@example.com", role: "created the key", source: zeroTokenRow.label },
    { email: "e2e@example.com", role: "organization owner", source: "Costura organization" },
  ],
  owners_gap: null,
  investigate: {
    by: "api_key",
    filters: { provider: "anthropic", provider_account: "1", api_key: zeroTokenRow.key },
    measure: "billed_usd",
  },
  detected_at: `${MONTH}-12T06:02:00Z`,
  updated_at: `${MONTH}-12T06:02:00Z`,
};

const anomalies = {
  month: MONTH,
  open_count: 3,
  open_total: 3,
  anomalies: [
    openAnomaly,
    {
      ...openAnomaly,
      id: 8,
      provider: "openrouter",
      ...accountOf("openrouter"),
      series_kind: "org",
      series_id: "__org__",
      label: "organization total",
      impact: "95.00",
      impact_share: "1.50",
      total_impact: "95.00",
      max_impact: "95.00",
      deviation: "1.20",
      severity: "medium",
      root_causes: [
        {
          kind: "api_key",
          id: "apikey_new",
          label: "migration-script (apikey_new)",
          actual: "220.00",
          baseline: "0.00",
          delta: "220.00",
        },
      ],
      owners: [
        { email: "e2e@example.com", role: "organization owner", source: "Costura organization" },
      ],
      owners_gap: "None of the top contributors is tied to a person in the provider inventory.",
    },
    {
      ...openAnomaly,
      id: 9,
      series_id: batchRow.key,
      label: batchRow.label,
      kind: "drop",
      day: `${MONTH}-08`,
      end_day: `${MONTH}-10`,
      ongoing: true,
      duration_days: 3,
      actual: "120.00",
      expected: "610.00",
      impact: "490.00",
      impact_percent: "80.33",
      impact_share: "7.50",
      total_actual: "360.00",
      total_expected: "1830.00",
      total_impact: "1470.00",
      max_impact: "490.00",
      deviation: "1.75",
      severity: "high",
      detected_at: `${MONTH}-09T06:02:00Z`,
      updated_at: `${MONTH}-11T06:02:00Z`,
    },
  ],
};

for (const item of anomalies.anomalies) {
  const drop = item.kind === "drop";
  item.explanation =
    item.kind === "new_principal"
      ? `${item.label} is new: ${item.actual} USD on its first day.`
      : `${item.label} spent ${item.impact} USD ${drop ? "less" : "more"} than expected; ${item.root_causes?.[0]?.label ?? item.label} moved the most.`;
}

/** Eight weeks ending on the anomaly day; Tuesdays are the baseline samples. */
function anomalySeries(anomaly) {
  const end = Date.parse(`${anomaly.day}T00:00:00Z`);
  const points = [];
  for (let k = 56; k >= 0; k -= 1) {
    const day = new Date(end - k * 86_400_000).toISOString().slice(0, 10);
    const sample = k > 0 && k % 7 === 0;
    points.push({
      day,
      amount: k === 0 ? anomaly.actual : sample ? anomaly.expected : "500.00",
      baseline_sample: sample,
    });
  }
  return points;
}

const NO_TOKENS = {
  uncached_input_tokens: 0,
  cache_creation_5m_tokens: 0,
  cache_creation_1h_tokens: 0,
  cache_read_tokens: 0,
  output_tokens: 0,
  reasoning_tokens: 0,
};

function dayRow(key, label, amount, trailing, tokens, requests, isNew = false) {
  const total = Object.values(tokens).reduce((a, b) => a + b, 0);
  return {
    key,
    label,
    amount,
    tokens,
    request_count: requests,
    cost_per_million: total > 0 ? ((Number(amount) / total) * 1_000_000).toFixed(4) : null,
    trailing_average: trailing,
    delta: (Number(amount) - Number(trailing)).toFixed(2),
    new: isNew,
  };
}

/** The child dimensions the API tables for each series kind (`DAY_DIMENSIONS`). */
const DAY_DIMENSIONS = {
  org: ["api_key", "account", "model", "workspace"],
  api_key: ["model"],
  account: ["model"],
};

function dayBreakdown(dimension) {
  if (dimension === "model") {
    return {
      dimension,
      rows: [
        dayRow(
          "claude-opus-4-1",
          "claude-opus-4-1",
          "900.00",
          "300.00",
          { ...NO_TOKENS, uncached_input_tokens: 40_000_000, output_tokens: 5_000_000 },
          12_000,
        ),
        dayRow(
          "claude-sonnet-4",
          "claude-sonnet-4",
          "520.00",
          "310.00",
          { ...NO_TOKENS, uncached_input_tokens: 150_000_000, output_tokens: 8_000_000 },
          30_000,
        ),
      ],
    };
  }
  if (dimension === "api_key") {
    return {
      dimension,
      rows: [
        dayRow(
          ZERO_TOKEN_ID,
          zeroTokenRow.label,
          "1200.00",
          "400.00",
          { ...NO_TOKENS, uncached_input_tokens: 180_000_000, output_tokens: 12_000_000 },
          40_000,
        ),
        dayRow(
          "apikey_new",
          "migration-script (apikey_new)",
          "220.00",
          "0.00",
          { ...NO_TOKENS, uncached_input_tokens: 10_000_000, output_tokens: 1_000_000 },
          2_000,
          true,
        ),
      ],
    };
  }
  if (dimension === "account") {
    return { dimension, rows: [] };
  }
  return {
    dimension,
    rows: [
      dayRow(
        "wrkspc_01",
        "Platform (wrkspc_01)",
        "1420.00",
        "610.00",
        { ...NO_TOKENS, uncached_input_tokens: 190_000_000, output_tokens: 13_000_000 },
        42_000,
      ),
    ],
  };
}

/** The detector's arithmetic for the mock anomaly: median 610, MAD margin 280, bound 890. */
function anomalyEvidence(anomaly) {
  const series = anomalySeries(anomaly);
  const samples = series
    .filter((p) => p.baseline_sample)
    .reverse()
    .map((p) => ({ day: p.day, amount: p.amount, value: p.amount, adjusted: false }));
  const check = (name, observed, threshold, reason, passed = true) => ({
    name,
    passed,
    observed,
    threshold,
    reason,
  });
  return {
    baseline: {
      method: anomaly.baseline_method,
      samples,
      trend_per_week: "0.00",
      sensitivity: "normal",
      median: anomaly.expected,
      mad: "62.95",
      margin_mad: "280.00",
      margin_relative: "122.00",
      margin_absolute: "5.00",
      margin_rule: "mad",
      margin: "280.00",
      upper_bound: anomaly.upper_bound,
      lower_bound: anomaly.lower_bound ?? "330.00",
      stored_actual: anomaly.actual,
      stored_expected: anomaly.expected,
      stored_upper_bound: anomaly.upper_bound,
      actual_now: anomaly.actual,
      matches_stored: true,
    },
    checks:
      anomaly.kind === "drop"
        ? [
            check("below_lower_bound", anomaly.actual, anomaly.lower_bound, "within lower bound"),
            check("expected_floor", anomaly.expected, "20.00", "expected below 20 USD"),
            check("impact_floor", anomaly.impact, "10.00", "money missing below 10 USD"),
            check("complete_day", anomaly.end_day, `${MONTH}-14`, "the day is still open"),
            check("provider_reported", "3120.00", "0.00", "the provider reported nothing"),
            check(
              "recent_average",
              anomaly.actual,
              "480.00",
              "not 20% below the trailing 7-day average",
            ),
            check("history", "71", "12", "fewer than 12 days of history"),
            check("suppression", anomaly.max_impact, null, "an earlier drop covers this one"),
          ]
        : [
            check("above_upper_bound", anomaly.actual, anomaly.upper_bound, "within upper bound"),
            check("amount_floor", anomaly.actual, "5.00", "below 5 USD"),
            check("impact_floor", anomaly.impact, "10.00", "impact below 10 USD"),
            check(
              "organization_share",
              anomaly.actual,
              "18.20",
              "below 0.5% of the organization total",
            ),
            check(
              "recent_average",
              anomaly.actual,
              "540.00",
              "not 20% above the trailing 7-day average",
            ),
            check("previous_day", anomaly.actual, "500.00", "not above the previous day"),
            check("history", "71", "12", "fewer than 12 days of history"),
            check(
              "suppression",
              anomaly.actual,
              null,
              "not above another anomaly in the same series within 7 days",
            ),
          ],
    breakdowns: DAY_DIMENSIONS[anomaly.series_kind].map(dayBreakdown),
    unit_economics: {
      day: {
        amount: anomaly.actual,
        tokens: { ...NO_TOKENS, uncached_input_tokens: 190_000_000, output_tokens: 13_000_000 },
        total_tokens: 203_000_000,
        request_count: 42_000,
        cost_per_million: "6.9951",
      },
      baseline: {
        amount: anomaly.expected,
        tokens: { ...NO_TOKENS, uncached_input_tokens: 170_000_000, output_tokens: 11_000_000 },
        total_tokens: 181_000_000,
        request_count: 38_000,
        cost_per_million: "3.3702",
      },
      sample_days: samples.length,
    },
    data_quality: {
      runs: [
        {
          id: 41,
          endpoint: "anomaly_detection",
          status: "succeeded",
          started_at: `${MONTH}-12T06:02:00Z`,
          finished_at: `${MONTH}-12T06:02:04Z`,
          rows_upserted: 2,
        },
        {
          id: 40,
          endpoint: "cost_report",
          status: "succeeded",
          started_at: `${MONTH}-12T06:00:00Z`,
          finished_at: `${MONTH}-12T06:01:30Z`,
          rows_upserted: 240,
        },
      ],
      cost_lines: 12,
      usage_lines: 48,
      allocated_lines: 96,
      unallocated_amount: "0.00",
      changed_since_detection: false,
    },
    history: [],
  };
}

function anomalyDetail(anomaly) {
  const others = anomalies.anomalies.filter(
    (item) => item.id !== anomaly.id && item.provider === anomaly.provider,
  );
  return {
    ...anomaly,
    series: anomalySeries(anomaly),
    same_day: others.map((item) => ({
      id: item.id,
      kind: item.kind,
      series_kind: item.series_kind,
      series_id: item.series_id,
      label: item.label,
      impact: item.impact,
      status: item.status,
    })),
    evidence: anomalyEvidence(anomaly),
  };
}

/**
 * The signed-in user's inbox per organization: the opt-in flag and the ids read. Unlike the
 * other writes, the alert routes apply, so the specs can walk opt-in -> unread -> read.
 */
const inbox = { optedIn: false, read: new Set(), signalsRead: new Set() };

const ALERTS_OFF = {
  opted_in: false,
  unread_count: 0,
  items: [],
  signals: [],
  unread_by_kind: {},
};

const inboxSignals = [
  {
    kind: "budget",
    provider: "anthropic",
    entity_kind: "org",
    entity_id: "default",
    label: "organization total",
    detail: "projected over the budget",
    dollars_at_risk: "320.00",
    currency: "USD",
    owner: null,
    owner_role: null,
    detected_at: "2026-09-14T08:00:00Z",
    reference: "1",
    read_reference: "1",
    occurrences: 1,
  },
];

function signalKey(signal) {
  return `${signal.kind}:${signal.provider}:${signal.read_reference}`;
}

function alertsBody() {
  if (!inbox.optedIn) return ALERTS_OFF;
  const items = anomalies.anomalies.map((item) => ({
    ...item,
    read_at: inbox.read.has(item.id) ? "2026-09-15T12:00:00Z" : null,
  }));
  const signals = inboxSignals.map((signal) => ({
    ...signal,
    read_at: inbox.signalsRead.has(signalKey(signal)) ? "2026-09-15T12:00:00Z" : null,
  }));
  const unreadAnomalies = items.filter((item) => item.read_at === null).length;
  const unread_by_kind = unreadAnomalies > 0 ? { anomaly: unreadAnomalies } : {};
  for (const signal of signals) {
    if (signal.read_at === null) {
      unread_by_kind[signal.kind] = (unread_by_kind[signal.kind] ?? 0) + 1;
    }
  }
  return {
    opted_in: true,
    unread_count: Object.values(unread_by_kind).reduce((sum, count) => sum + count, 0),
    items,
    signals,
    unread_by_kind,
  };
}

const anomalySettings = {
  sensitivity: "normal",
  detect_drops: true,
  detect_new_principals: true,
  retention_days: 90,
  idle_days: 30,
  new_key_days: 7,
};

function readBody(request) {
  return new Promise((resolve) => {
    let raw = "";
    request.on("data", (chunk) => {
      raw += chunk;
    });
    request.on("end", () => {
      try {
        resolve(raw ? JSON.parse(raw) : {});
      } catch {
        resolve({});
      }
    });
  });
}

const OWNER = { email: "e2e@example.com", name: "E2E" };
const INVITEE = { email: "newcomer@example.com", name: "Newcomer" };

const members = [
  {
    id: 1,
    email: OWNER.email,
    name: OWNER.name,
    role: "owner",
    created_at: "2026-09-14T10:00:00Z",
  },
];

/**
 * Invitations per organization slug, plus the memberships a claim creates. `accepted` holds the
 * slugs the invitee joined, which is what `/me` reports for that identity afterwards.
 */
const invites = { rows: [], nextId: 1, accepted: new Set() };

function resetInvites() {
  invites.rows = [];
  invites.nextId = 1;
  invites.accepted.clear();
}

/** 14 days out, like the API. */
function expiry() {
  return new Date(Date.now() + 14 * 86_400_000).toISOString();
}

function invitationBody(invitation, withUrl = false) {
  return {
    id: invitation.id,
    email: invitation.email,
    role: invitation.role,
    invited_by: OWNER.email,
    created_at: invitation.created_at,
    expires_at: invitation.expires_at,
    status: "pending",
    url: withUrl ? invitation.url : null,
  };
}

function pendingFor(email) {
  return invites.rows
    .filter((row) => row.email === email && !row.accepted && !row.revoked)
    .map((row) => ({
      id: row.id,
      organization: organizations.find((item) => item.slug === row.org),
      role: row.role,
      invited_by: OWNER.email,
      expires_at: row.expires_at,
    }));
}

/** Stamps the invitation and answers with the organization the caller now belongs to. */
function settle(row) {
  row.accepted = true;
  invites.accepted.add(row.org);
  const organization = organizations.find((item) => item.slug === row.org);
  return { ...organization, role: row.role };
}

/** Writes the specs assert on; append-only for the life of the server. */
const recorded = [];
let codexCreditPrices = [];

function json(response, status, body) {
  response.writeHead(status, { "content-type": "application/json" }).end(JSON.stringify(body));
}

createServer((request, response) => {
  const url = new URL(request.url ?? "/", `http://127.0.0.1:${port}`);
  const method = request.method ?? "GET";
  if (url.pathname === "/health") {
    response.writeHead(200).end("ok");
    return;
  }
  if (url.pathname === "/__e2e/requests") {
    if (method === "DELETE") {
      inbox.optedIn = false;
      inbox.read.clear();
      inbox.signalsRead.clear();
    }
    json(response, 200, recorded);
    return;
  }
  if (url.pathname === "/__e2e/credit-prices") {
    if (method === "DELETE") codexCreditPrices = [];
    json(response, 200, codexCreditPrices);
    return;
  }
  // Invitations reset on their own, so the invite spec does not clear the inbox state another
  // spec is walking at the same time (the local run uses several workers).
  if (url.pathname === "/__e2e/invitations") {
    if (method === "DELETE") resetInvites();
    json(response, 200, invites.rows);
    return;
  }
  // Same reason as the invitations reset: the detection settings are one row for the whole
  // mock, so the spec that saves them puts the defaults back on its own.
  const bearer = request.headers.authorization;
  const invitee = bearer === "Bearer e2e-invitee";
  const signedIn = bearer === "Bearer e2e-session" || invitee;
  const caller = invitee ? INVITEE : OWNER;
  if (method !== "GET" && !signedIn) {
    json(response, 401, { detail: "unauthorized" });
    return;
  }
  // Like the API: the caller's own organizations exclude the public sample one.
  const own = organizations.filter((item) => !item.is_demo);
  // The invitee belongs to nothing until a claim lands.
  const callerOrgs = invitee ? own.filter((item) => invites.accepted.has(item.slug)) : own;
  if (method === "GET" && url.pathname === "/api/v1/auth/google") {
    json(response, 200, {
      enabled: false,
      dev_sign_in_enabled: true,
      operator_sign_in_enabled: false,
    });
    return;
  }
  if (method === "GET" && url.pathname === "/api/v1/me") {
    if (!signedIn) {
      json(response, 401, { detail: "unauthorized" });
      return;
    }
    json(response, 200, {
      user: caller,
      organizations: callerOrgs,
      demo_org: "demo",
      invitations: pendingFor(caller.email),
    });
    return;
  }
  // Accepting and claiming sit outside the organization scope, like `POST /orgs`.
  if (method === "POST" && url.pathname === "/api/v1/invitations/claim") {
    recorded.push({ method, path: url.pathname });
    readBody(request).then((body) => {
      const row = invites.rows.find((item) => item.token === body.token && !item.revoked);
      if (!row) {
        json(response, 404, { detail: "unknown invitation" });
        return;
      }
      if (row.email !== caller.email) {
        json(response, 403, {
          detail: `this invitation was sent to ${row.email}; sign in with that address`,
        });
        return;
      }
      json(response, 200, settle(row));
    });
    return;
  }
  const acceptMatch = /^\/api\/v1\/invitations\/(\d+)\/accept$/.exec(url.pathname);
  if (method === "POST" && acceptMatch) {
    recorded.push({ method, path: url.pathname });
    const row = invites.rows.find((item) => item.id === Number(acceptMatch[1]) && !item.revoked);
    if (!row) {
      json(response, 404, { detail: "unknown invitation" });
      return;
    }
    if (row.email !== caller.email) {
      json(response, 403, {
        detail: `this invitation was sent to ${row.email}; sign in with that address`,
      });
      return;
    }
    json(response, 200, settle(row));
    return;
  }
  if (method === "GET" && url.pathname === "/api/v1/orgs") {
    if (!signedIn) {
      json(response, 401, { detail: "unauthorized" });
      return;
    }
    json(response, 200, callerOrgs);
    return;
  }
  const orgMatch = /^\/api\/v1\/orgs\/([^/]+)(\/.*)?$/.exec(url.pathname);
  if (!orgMatch) {
    json(response, 404, { detail: "not found" });
    return;
  }
  const org = decodeURIComponent(orgMatch[1]);
  const rest = orgMatch[2] ?? "";
  const organization = organizations.find((item) => item.slug === org);
  if (!organization) {
    json(response, 404, { detail: "organization not found" });
    return;
  }
  // The sample organization reads without a session; every other one asks to sign in.
  if (!organization.is_demo && !signedIn) {
    json(response, 401, { detail: "unauthorized" });
    return;
  }
  if (method === "GET" && rest === "") {
    json(response, 200, organization);
    return;
  }
  const providers = providersOf(org);
  if (method === "GET" && rest === "/providers") {
    json(response, 200, providers);
    return;
  }
  if (method === "GET" && rest === "/members") {
    json(
      response,
      200,
      members.map((member) => ({ ...member, is_you: member.email === caller.email })),
    );
    return;
  }
  if (rest === "/invitations" || rest.startsWith("/invitations/")) {
    if (method === "GET" && rest === "/invitations") {
      json(
        response,
        200,
        invites.rows
          .filter((row) => row.org === org && !row.accepted && !row.revoked)
          .map((row) => invitationBody(row)),
      );
      return;
    }
    if (method === "POST" && rest === "/invitations") {
      recorded.push({ method, path: url.pathname });
      readBody(request).then((body) => {
        const id = invites.nextId++;
        const token = `e2e-token-${id}`;
        const row = {
          id,
          org,
          email: String(body.email ?? "").toLowerCase(),
          role: body.role ?? "member",
          token,
          url: `http://127.0.0.1:3100/join/${token}`,
          created_at: new Date().toISOString(),
          expires_at: expiry(),
          accepted: false,
          revoked: false,
        };
        invites.rows.push(row);
        json(response, 201, invitationBody(row, true));
      });
      return;
    }
    const revokeMatch = /^\/invitations\/(\d+)$/.exec(rest);
    if (method === "DELETE" && revokeMatch) {
      recorded.push({ method, path: url.pathname });
      const row = invites.rows.find((item) => item.id === Number(revokeMatch[1]));
      if (row) row.revoked = true;
      response.writeHead(204).end();
      return;
    }
    json(response, 405, { detail: "method not allowed" });
    return;
  }
  const memberMatch = /^\/members\/(\d+)$/.exec(rest);
  if (memberMatch && method === "DELETE") {
    recorded.push({ method, path: url.pathname });
    response.writeHead(204).end();
    return;
  }
  if (memberMatch && method === "PATCH") {
    recorded.push({ method, path: url.pathname });
    const member = members.find((item) => item.id === Number(memberMatch[1])) ?? members[0];
    readBody(request).then((body) => {
      json(response, 200, { ...member, role: body.role ?? member.role, is_you: true });
    });
    return;
  }
  if (rest === "/teams" && method === "GET") {
    json(response, 200, {
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
    return;
  }
  if (rest === "/audit" && method === "GET") {
    json(response, 200, {
      events: [
        {
          id: 1,
          event: "provider_key_connected",
          actor_email: "ana@example.com",
          target: "anthropic",
          details: { provider: "anthropic", key_hint: "1234" },
          request_id: "req-e2e-1",
          created_at: "2026-09-14T09:00:00Z",
        },
      ],
      limit: 50,
      offset: 0,
      total: 1,
    });
    return;
  }
  if (rest === "/signals/history" && method === "GET") {
    json(response, 200, {
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
    return;
  }
  if (rest === "/webhook" || rest === "/webhook/test") {
    if (method === "GET" && rest === "/webhook") {
      json(response, 200, {
        egress_enabled: false,
        allowed_hosts: [],
        configured: false,
        host: null,
        created_at: null,
        host_blocked: false,
        digest: "off",
        deliveries: [],
      });
      return;
    }
    json(response, 409, { detail: "outbound webhooks are off on this stack" });
    return;
  }
  if (rest === "/alerts" || rest === "/alerts/settings" || rest === "/alerts/read") {
    if (organization.is_demo && method !== "GET") {
      json(response, 403, { detail: "the sample organization is read-only" });
      return;
    }
    if (organization.is_demo) {
      json(response, 200, ALERTS_OFF);
      return;
    }
    if (method === "GET" && rest === "/alerts") {
      json(response, 200, alertsBody());
      return;
    }
    if (method === "PUT" && rest === "/alerts/settings") {
      recorded.push({ method, path: url.pathname });
      readBody(request).then((body) => {
        inbox.optedIn = body.opted_in === true;
        if (!inbox.optedIn) {
          inbox.read.clear();
          inbox.signalsRead.clear();
        }
        json(response, 200, alertsBody());
      });
      return;
    }
    if (method === "POST" && rest === "/alerts/read") {
      recorded.push({ method, path: url.pathname });
      readBody(request).then((body) => {
        const ids = body.all
          ? anomalies.anomalies.map((item) => item.id)
          : (body.anomaly_ids ?? []);
        for (const id of ids) inbox.read.add(id);
        const signals = body.all ? inboxSignals : (body.signals ?? []);
        for (const signal of signals) inbox.signalsRead.add(signalKey(signal));
        json(response, 200, alertsBody());
      });
      return;
    }
    json(response, 405, { detail: "method not allowed" });
    return;
  }
  // Rename: the slug stays. Recorded and answered with the new name; the fixture
  // is not changed because the specs run in parallel against one process.
  if (method === "PATCH" && rest === "") {
    recorded.push({ method, path: url.pathname });
    readBody(request).then((body) => {
      const name = String(body.name ?? "").trim();
      if (!name) {
        json(response, 422, { detail: "name must not be blank" });
        return;
      }
      json(response, 200, { ...organization, name });
    });
    return;
  }
  // Entity lookup: page addresses name no provider, so pages ask which provider owns an id
  // before reading it.
  const lookupMatch = /^\/entities\/(key|workspace|account|model|anomaly)\/([^/]+)$/.exec(rest);
  if (method === "GET" && lookupMatch) {
    const [, kind, rawId] = lookupMatch;
    const id = decodeURIComponent(rawId);
    const owners = {
      key: { [ZERO_TOKEN_ID]: "anthropic", apikey_new: "openrouter" },
      account: { "user-ana": "openai", svc_billing: "anthropic" },
      workspace: { wrkspc_platform: "anthropic" },
    };
    let owner = null;
    if (kind === "anomaly") {
      owner = anomalies.anomalies.find((item) => item.id === Number(id))?.provider ?? null;
    } else if (kind === "model") {
      owner = "anthropic";
    } else {
      owner = owners[kind][id] ?? null;
    }
    if (owner === null) {
      json(response, 404, { detail: `${kind} not found` });
      return;
    }
    const account = Number(url.searchParams.get("account"));
    json(response, 200, {
      provider: owner,
      provider_account_id:
        Number.isInteger(account) && account > 0 ? account : (ACCOUNT_IDS[owner] ?? null),
    });
    return;
  }
  if (rest === "/anomaly-settings") {
    if (method === "GET") {
      json(response, 200, anomalySettings);
      return;
    }
    if (method === "PUT") {
      recorded.push({ method, path: url.pathname });
      readBody(request).then((body) => json(response, 200, { ...anomalySettings, ...body }));
      return;
    }
    json(response, 405, { detail: "method not allowed" });
    return;
  }
  if (method === "GET" && rest === "/setup") {
    json(response, 200, {
      state: "ready",
      providers,
      runs: [],
      first_month: MONTH,
      dismissed_at: "2026-09-15T12:00:00Z",
      writes_enabled: true,
    });
    return;
  }
  if (method === "GET" && rest === "/query" && url.searchParams.get("format") === "csv") {
    const expected = {
      measure: "billed_usd",
      dimensions: "model",
      start: "2026-08-01",
      end: "2026-08-31",
      interval: "day",
      top: "10",
      provider: "anthropic",
      format: "csv",
    };
    if (JSON.stringify(Object.fromEntries(url.searchParams)) !== JSON.stringify(expected)) {
      json(response, 400, { detail: `unexpected query: ${url.search}` });
      return;
    }
    response
      .writeHead(200, {
        "content-disposition": `attachment; filename="costura-${org}-2026-08-01-2026-08-31-model.csv"`,
        "content-type": "text/csv; charset=utf-8",
      })
      .end("key,label,amount\nmodel-1,Claude,12.34\n");
    return;
  }
  if (method === "GET" && rest === "/query") {
    json(response, 200, queryFor(url.searchParams, org));
    return;
  }
  if (method === "GET" && rest === "/queries") {
    const measures = (url.searchParams.get("measures") ?? "").split(",").filter(Boolean);
    const results = measures.map((measure) => {
      const query = new URLSearchParams(url.searchParams);
      query.set("measure", measure);
      query.delete("measures");
      return queryFor(query, org);
    });
    json(response, 200, { results });
    return;
  }
  const creditPriceMatch = /^\/accounts\/(\d+)\/credit-prices(?:\/(\d+))?$/.exec(rest);
  if (creditPriceMatch) {
    const accountId = Number(creditPriceMatch[1]);
    const priceId = creditPriceMatch[2] ? Number(creditPriceMatch[2]) : null;
    if (accountId !== ACCOUNT_IDS.codex) {
      json(response, 404, { detail: "Codex account not found" });
      return;
    }
    if (method === "GET" && priceId === null) {
      json(response, 200, codexCreditPrices);
      return;
    }
    recorded.push({ method, path: url.pathname });
    if (method === "DELETE" && priceId !== null) {
      codexCreditPrices = codexCreditPrices.filter((price) => price.id !== priceId);
      response.writeHead(204).end();
      return;
    }
    if (method === "POST" && priceId === null) {
      readBody(request).then((body) => {
        const amount = Number(body.price_per_credit);
        if (!body.effective_from || !Number.isFinite(amount) || amount <= 0) {
          json(response, 422, { detail: "credit price is invalid" });
          return;
        }
        if (codexCreditPrices.some((price) => price.effective_from === body.effective_from)) {
          json(response, 422, {
            detail: `a credit price already starts on ${body.effective_from}`,
          });
          return;
        }
        const created = {
          id: Math.max(0, ...codexCreditPrices.map((price) => price.id)) + 1,
          organization_id: 3,
          provider_account_id: accountId,
          effective_from: body.effective_from,
          price_per_credit: amount.toFixed(8),
          created_by: 1,
          created_at: new Date().toISOString(),
        };
        codexCreditPrices.push(created);
        json(response, 201, created);
      });
      return;
    }
    json(response, 405, { detail: "method not allowed" });
    return;
  }
  const scopeMatch = /^\/providers\/([^/]+)(\/.*)$/.exec(rest);
  if (!scopeMatch) {
    json(response, 404, { detail: "not found" });
    return;
  }
  const provider = decodeURIComponent(scopeMatch[1]);
  const scoped = scopeMatch[2];
  const known = providers.find((item) => item.provider === provider);
  if (!known && provider !== "all") {
    json(response, 404, { detail: "provider not found" });
    return;
  }
  const keyMatch = /^\/accounts\/(\d+)\/key$/.exec(scoped);
  if (method === "DELETE" && (scoped === "/connection" || keyMatch)) {
    recorded.push({ method, path: url.pathname });
    // Only the OpenRouter form may reach this route in the specs; a disconnect aimed at another
    // provider or account is the H8 regression and must not read as success.
    const accountId = keyMatch ? Number(keyMatch[1]) : ACCOUNT_IDS[provider];
    if (provider !== "openrouter" || accountId !== ACCOUNT_IDS.openrouter) {
      json(response, 409, { detail: `disconnect targeted ${provider} account ${accountId}` });
      return;
    }
    const disconnected = {
      ...connectionOf(provider, known),
      connected: false,
      source: null,
      key_hint: null,
      last_validated_at: null,
    };
    json(
      response,
      200,
      keyMatch
        ? { ...disconnected.accounts[0], connected: false, source: null, key_hint: null }
        : { ...disconnected, accounts: [] },
    );
    return;
  }
  if (method !== "GET") {
    recorded.push({ method, path: url.pathname });
    json(response, 403, { detail: "writes are recorded, not applied" });
    return;
  }
  if (scoped === "/months") {
    json(response, 200, { months: [MONTH, PREVIOUS_MONTH] });
    return;
  }
  if (scoped === "/connection") {
    json(response, 200, connectionOf(provider, known));
    return;
  }
  if (scoped === "/accounts") {
    json(response, 200, { accounts: known?.accounts ?? [] });
    return;
  }
  if (scoped === "/signals") {
    const items = [
      ...anomalies.anomalies
        .filter(
          (item) => item.status === "open" && (provider === "all" || item.provider === provider),
        )
        .map((item) => ({
          kind: "anomaly",
          provider: item.provider,
          entity_kind: item.series_kind,
          entity_id: item.series_id,
          label: item.label,
          detail: `${item.kind}, ${item.severity} severity`,
          dollars_at_risk: item.total_impact,
          currency: item.currency,
          owner: item.owners?.[0]?.email ?? null,
          owner_role: item.owners?.[0]?.role ?? null,
          detected_at: item.detected_at,
          reference: String(item.id),
          occurrences: 1,
        })),
      ...(provider === "all" || provider === "anthropic"
        ? [
            {
              kind: "no_owner",
              provider: "anthropic",
              entity_kind: "api_key",
              entity_id: ZERO_TOKEN_ID,
              label: "zero-token-key",
              detail: "no owner in the provider inventory or in Costura",
              dollars_at_risk: "0.00",
              currency: "USD",
              owner: null,
              owner_role: null,
              detected_at: "2026-08-31T12:00:00+00:00",
              reference: ZERO_TOKEN_ID,
              occurrences: 3,
            },
          ]
        : []),
    ].sort((a, b) => Number(b.dollars_at_risk) - Number(a.dollars_at_risk));
    json(response, 200, { items, total: items.length, snoozed: [] });
    return;
  }
  if (scoped === "/runs") {
    const endpoint = url.searchParams.get("endpoint");
    const runs = sampleRuns.filter(
      (run) =>
        (provider === "all" || run.provider === provider) &&
        (endpoint === null || run.endpoint === endpoint),
    );
    json(response, 200, { runs, as_of: "2026-09-15T12:00:00Z" });
    return;
  }
  if (scoped === "/budgets") {
    const budgets = provider === "all" || provider === sampleBudget.provider ? [sampleBudget] : [];
    json(response, 200, { budgets });
    return;
  }
  const detailMatch = /^\/anomalies\/(\d+)$/.exec(scoped);
  if (detailMatch) {
    const found = anomalies.anomalies.find((item) => item.id === Number(detailMatch[1]));
    if (!found || (provider !== "all" && found.provider !== provider)) {
      json(response, 404, { detail: "anomaly not found" });
      return;
    }
    json(response, 200, anomalyDetail(found));
    return;
  }
  if (scoped === "/inventory/search") {
    const needle = (url.searchParams.get("q") ?? "").trim().toLowerCase();
    const limit = Number(url.searchParams.get("limit") ?? "5");
    const account = accountOf("anthropic");
    const catalog = [
      {
        kind: "person",
        id: PERSON_EMAIL,
        label: PERSON_EMAIL,
        providers: ["anthropic", "openai"],
        provider_account_id: null,
        provider_account_label: null,
        hint: null,
      },
      {
        kind: "service",
        id: "svc_billing",
        label: "billing-bot",
        providers: ["anthropic"],
        ...account,
        hint: "service",
      },
      {
        kind: "api_key",
        id: ZERO_TOKEN_ID,
        label: ZERO_TOKEN_NAME,
        providers: ["anthropic"],
        provider_account_id: RESEARCH_ACCOUNT.id,
        provider_account_label: RESEARCH_ACCOUNT.label,
        hint: "sk-ant-...zero",
      },
      {
        kind: "workspace",
        id: "wrkspc_platform",
        label: "Platform",
        providers: ["anthropic"],
        ...account,
        hint: null,
      },
    ];
    const items = [];
    for (const kind of ["person", "service", "api_key", "workspace"]) {
      items.push(
        ...catalog
          .filter(
            (item) =>
              item.kind === kind &&
              `${item.label} ${item.id} ${item.hint ?? ""}`.toLowerCase().includes(needle),
          )
          .slice(0, limit),
      );
    }
    json(response, 200, { items });
    return;
  }
  if (scoped === `/inventory/api-keys/${ZERO_TOKEN_ID}`) {
    json(response, 200, zeroTokenKey);
    return;
  }
  const inventoryList = /^\/inventory\/(api-keys|workspaces|users)$/.exec(scoped);
  if (inventoryList) {
    const items =
      provider === "all" || provider === "anthropic" ? inventoryItems(inventoryList[1]) : [];
    json(response, 200, { items });
    return;
  }
  const inventoryDetail = /^\/inventory\/(api-keys|workspaces|users)\/([^/]+)$/.exec(scoped);
  if (inventoryDetail) {
    const found = (
      provider === "all" || provider === "anthropic" ? inventoryItems(inventoryDetail[1]) : []
    ).find((item) => item.external_id === decodeURIComponent(inventoryDetail[2]));
    if (!found) {
      json(response, 404, { detail: "entity not found" });
      return;
    }
    json(response, 200, found);
    return;
  }
  const personMatch = /^\/months\/(\d{4}-\d{2})\/people\/([^/]+)$/.exec(scoped);
  if (personMatch) {
    if (decodeURIComponent(personMatch[2]).toLowerCase() !== PERSON_EMAIL) {
      json(response, 404, { detail: "person not found" });
      return;
    }
    const identities =
      provider === "all"
        ? person.identities
        : person.identities.filter((i) => i.provider === provider);
    json(response, 200, { ...person, identities, providers: identities.map((i) => i.provider) });
    return;
  }
  const monthMatch =
    /^\/months\/(\d{4}-\d{2})\/(usage|movers|series|summary|anomalies|projection|budgets)$/.exec(
      scoped,
    );
  if (!monthMatch) {
    json(response, 404, { detail: "not found" });
    return;
  }
  const [, month, resource] = monthMatch;
  const query = url.searchParams;
  if (month !== MONTH) {
    if (resource === "usage") {
      json(response, 200, {
        dimension: query.get("by") ?? "api_key",
        allocated: true,
        cost_total: "0.00",
        rows: [],
      });
      return;
    }
    json(response, 404, { detail: `no data for ${month}` });
    return;
  }
  switch (resource) {
    case "usage":
      json(response, 200, usageFor(query, provider));
      return;
    case "movers":
      json(response, 200, moversFor(query, provider));
      return;
    case "series":
      json(response, 200, seriesFor(query));
      return;
    case "summary":
      json(response, 200, summaryFor(provider, query));
      return;
    case "anomalies": {
      const scopedRows = anomalies.anomalies.filter(
        (item) =>
          (provider === "all" || item.provider === provider) &&
          (!query.get("series_id") || item.series_id === query.get("series_id")),
      );
      const { start, end } = periodOf(query);
      json(response, 200, {
        ...anomalies,
        start,
        end,
        window_total: summaryFor(provider, query).total,
        open_count: scopedRows.length,
        open_total: scopedRows.length,
        anomalies: scopedRows,
      });
      return;
    }
    case "projection":
      json(response, 200, { month, by: query.get("by") ?? "org", projections: [] });
      return;
    case "budgets": {
      const statuses =
        provider === "all" || provider === sampleBudget.provider ? [sampleBudgetStatus] : [];
      json(response, 200, { month, statuses, alerts: [] });
      return;
    }
    default:
      json(response, 404, { detail: "not found" });
  }
}).listen(port, "127.0.0.1");
