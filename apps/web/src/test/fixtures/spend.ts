/** Spend fixtures: usage rows, series, the range query, summary, movers and reconcile. */

import type {
  ActivityRow,
  DailySeries,
  Movers,
  Projection,
  Projections,
  Reconcile,
  SpendQuery,
  Summary,
  Usage,
  UsageRow,
} from "@/lib/api";
import type { Schema } from "@/lib/api/schema";

import { DAYS, MONTH, OTHER_PROVIDER, PROVIDER, tokens, zeros } from "./common";

export const usageRows: UsageRow[] = [
  {
    key: "apikey_redacted_2",
    label: "batch-ingest (apikey_redacted_2)",
    provider: PROVIDER,
    provider_account_id: 1,
    provider_account_label: "Anthropic",
    details: {
      hint: "sk-ant-api03-...bbbb",
      workspace: "Platform (wrkspc_redacted_a)",
      created_by: "bob@example.com",
      status: "active",
    },
    amount: "40000.00",
    share: "71.35",
    tokens: tokens(20000),
    byok_amount: null,
    total_tokens: 30000,
    web_search_requests: 0,
    person: null,
  },
  {
    key: "apikey_redacted_9",
    label: "retired (apikey_redacted_9)",
    provider: PROVIDER,
    provider_account_id: 1,
    provider_account_label: "Anthropic",
    details: {
      hint: "",
      workspace: "(default workspace)",
      created_by: "",
      status: "inactive [missing]",
    },
    amount: "16056.12",
    share: "28.65",
    tokens: tokens(1000),
    byok_amount: null,
    total_tokens: 1500,
    web_search_requests: 2,
    person: null,
  },
];

const allocation: Schema<"AllocationOut"> = {
  run_id: 10,
  allocated: "56056.12",
  unallocated: "0.00",
  by_reason: {},
  coverage_percent: "100.00",
  delta: "0.00",
  ok: true,
};

export const usage: Usage = {
  dimension: "api_key",
  allocated: true,
  cost_total: "56056.12",
  rows: usageRows,
};

export const movers: Movers = {
  dimension: "api_key",
  allocated: true,
  previous_month: "2026-07",
  previous_start: "2026-07-01",
  previous_end: "2026-07-31",
  rows: [
    {
      key: "apikey_redacted_2",
      label: "batch-ingest (apikey_redacted_2)",
      provider: PROVIDER,
      provider_account_id: 1,
      provider_account_label: "Anthropic",
      amount: "40000.00",
      previous_amount: "12000.00",
      delta: "28000.00",
      change_percent: "233.33",
      is_new: false,
      is_gone: false,
    },
    {
      key: "apikey_redacted_7",
      label: "nightly-eval (apikey_redacted_7)",
      provider: PROVIDER,
      provider_account_id: 1,
      provider_account_label: "Anthropic",
      amount: "0.00",
      previous_amount: "9000.00",
      delta: "-9000.00",
      change_percent: "-100.00",
      is_new: false,
      is_gone: true,
    },
    {
      key: "apikey_redacted_3",
      label: "agent-loop (apikey_redacted_3)",
      provider: PROVIDER,
      provider_account_id: 1,
      provider_account_label: "Anthropic",
      amount: "5200.00",
      previous_amount: "0.00",
      delta: "5200.00",
      change_percent: null,
      is_new: true,
      is_gone: false,
    },
  ],
};

/** Both months imported, neither attributed: the card says so instead of ranking. */
export const noMovers: Movers = {
  dimension: "api_key",
  allocated: false,
  previous_month: "2026-07",
  previous_start: "2026-07-01",
  previous_end: "2026-07-31",
  rows: [],
};

export const reconcile: Reconcile = {
  month: MONTH,
  currency: "USD",
  costura_total: "56056.12",
  costura_total_exact: "56056.12000000",
  reported_total: null,
  delta: null,
  delta_percent: null,
  matches: null,
  breakdown_dimension: "day",
  breakdown: [
    { label: "2026-08-01", amount: "1000.00" },
    { label: "2026-08-02", amount: "0.00" },
  ],
  raw_check: { run_id: 9, raw_total: "56056.12", delta: "0.00", ok: true },
  provider_check: {
    run_id: 10,
    provider_total: "56056.12",
    delta: "0.00",
    ok: true,
    label: "Provider-reported usage",
    derived_seat_total: "0.00",
  },
  allocation,
  key_check: null,
  key_check_supported: false,
  token_totals: { uncached_input_tokens: 134165, output_tokens: 20 },
  activity_coverage: null,
  account_id: null,
  account_label: null,
  accounts: [{ id: 1, provider: PROVIDER, label: "Anthropic" }],
};

export const activity: ActivityRow[] = [
  {
    family: "embeddings",
    unit: "input_tokens",
    quantity: "25000.00000000",
    requests: 5,
    billed_usd: "0.06",
    cost_per_unit: "0.00000240",
  },
];

export const series: DailySeries = {
  month: MONTH,
  dimension: "workspace",
  source: "allocated",
  days: DAYS,
  series: [
    {
      key: "wrkspc_redacted_a",
      label: "Platform (wrkspc_redacted_a)",
      provider: PROVIDER,
      values: zeros().map((v, i) => (i === 0 ? "1000.00" : v)),
      total: "1000.00",
    },
    {
      key: null,
      label: "(default workspace)",
      provider: PROVIDER,
      values: zeros().map((v, i) => (i === 1 ? "55056.12" : v)),
      total: "55056.12",
    },
  ],
  other: null,
  total: zeros().map((v, i) => (i === 0 ? "1000.00" : i === 1 ? "55056.12" : v)),
  month_total: "56056.12",
};

export const spendQuery: SpendQuery = {
  measure: "billed_usd",
  dimensions: ["api_key"],
  start: "2026-08-01",
  end: "2026-08-31",
  interval: "day",
  source: "allocated",
  buckets: DAYS,
  series: usageRows.map((row, index) => ({
    keys: { api_key: row.key },
    labels: { api_key: row.label },
    provider: row.provider,
    values: zeros().map((value, day) => (day === index ? row.amount! : value)),
    total: row.amount!,
  })),
  other: null,
  total: series.total,
  comparison: null,
  projection: null,
};

export const summary: Summary = {
  month: MONTH,
  start: `${MONTH}-01`,
  end: `${MONTH}-31`,
  previous_start: "2026-07-01",
  previous_end: "2026-07-31",
  comparison_basis: "full_month",
  complete_through: null,
  data_stale: false,
  detection_through: null,
  duplicate_accounts: [],
  currency: "USD",
  total: "56056.12",
  previous_month: "2026-07",
  previous_total: "50000.00",
  change_percent: "12.11",
  days_in_month: 31,
  days_with_data: 2,
  last_day_with_data: "2026-08-02",
  daily_average: "28028.06",
  is_current_month: false,
  projected_total: null,
  top_keys_share: "100.00",
  top_key_count: 2,
  cache_read_share: "0.00",
  tokens: {
    uncached_input_tokens: 134165,
    cache_creation_5m_tokens: 0,
    cache_creation_1h_tokens: 0,
    cache_read_tokens: 0,
    output_tokens: 20,
  },
  allocation,
  provider_total: "56056.12",
  provider_matches: true,
  provider_difference: "0.00",
  currency_totals: null,
  byok_total: null,
  people_total: "16056.12",
  people_share: "28.64",
};

/** An OpenRouter month where part of the traffic ran on the customer's own provider keys. */
export const byokSummary: Summary = {
  ...summary,
  total: "8933.90",
  provider_total: "8933.90",
  byok_total: "56872.78",
};

const openRouterKeyRow: UsageRow = {
  key: "orkey_hash_1",
  label: "router-prod (orkey_hash_1)",
  provider: OTHER_PROVIDER,
  provider_account_id: 2,
  provider_account_label: "OpenRouter",
  details: { hint: "prod", workspace: "Default (ws_or_1)", created_by: "", status: "active" },
  amount: "1200.00",
  share: "2.10",
  tokens: {
    uncached_input_tokens: 5000,
    cache_read_tokens: 500,
    output_tokens: 2000,
    reasoning_tokens: 300,
  },
  byok_amount: "0.00",
  total_tokens: 7800,
  web_search_requests: 0,
  person: null,
};

/** An OpenRouter key whose traffic ran mostly on the customer's own provider keys. */
export const byokKeyRow: UsageRow = {
  ...openRouterKeyRow,
  key: "orkey_hash_2",
  label: "router-byok (orkey_hash_2)",
  amount: "17.00",
  share: "0.03",
  byok_amount: "5400.50",
};

/** Keys of an OpenRouter month with one BYOK row: the table shows the BYOK column. */
export const usageWithByok: Usage = {
  ...usage,
  cost_total: "1217.00",
  rows: [openRouterKeyRow, byokKeyRow],
};

/** Usage grouped by provider under `all`: labels come from the registry. */
export const usageByProvider: Usage = {
  dimension: "provider",
  allocated: true,
  cost_total: "57256.12",
  rows: [
    {
      key: PROVIDER,
      label: "Anthropic",
      provider: PROVIDER,
      provider_account_id: null,
      provider_account_label: null,
      details: {},
      amount: "56056.12",
      share: "97.90",
      tokens: tokens(21000),
      byok_amount: null,
      total_tokens: 31500,
      web_search_requests: 2,
      person: null,
    },
    {
      key: OTHER_PROVIDER,
      label: "OpenRouter",
      provider: OTHER_PROVIDER,
      provider_account_id: null,
      provider_account_label: null,
      details: {},
      amount: "1200.00",
      share: "2.10",
      tokens: openRouterKeyRow.tokens,
      byok_amount: "0.00",
      total_tokens: 7800,
      web_search_requests: 0,
      person: null,
    },
  ],
};

/** Keys from both providers, as the aggregated usage report lists them. */
export const usageAll: Usage = {
  ...usage,
  cost_total: "57256.12",
  rows: [...usageRows, openRouterKeyRow],
};

const projection: Projection = {
  provider: PROVIDER,
  series_kind: "org",
  series_id: "__org__",
  label: "organization total",
  as_of_day: "2026-08-02",
  mtd: "56056.12",
  projected_total: "52100.00",
  low: "48900.00",
  high: "55600.00",
  currency: "USD",
  days: [
    { day: "2026-08-03", expected: "1500.00", low: "1200.00", high: "1900.00", samples: 8 },
    { day: "2026-08-04", expected: "1500.00", low: "1200.00", high: "1900.00", samples: 8 },
  ],
  computed_at: "2026-08-03T06:02:00Z",
};

export const projections: Projections = { month: MONTH, by: "org", projections: [projection] };

export const noProjections: Projections = { month: MONTH, by: "org", projections: [] };
