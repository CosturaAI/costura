/** Anomaly fixtures: anomalies, evidence, detail and the alert inbox. */

import type {
  Alerts,
  Anomalies,
  Anomaly,
  AnomalyDetail,
  AnomalyEvidence,
  InboxSignal,
  Signals,
} from "@/lib/api";

import { MONTH, OTHER_PROVIDER, PROVIDER, ZERO_TOKENS } from "./common";

/** A Claude Code login spiking: the user is the series and the owner. */
export const anomaly: Anomaly = {
  explanation:
    "ana@example.com spent 810.00 USD more than expected (133% over); claude-opus-4-1 accounts for 100% of the increase.",
  id: 7,
  provider: PROVIDER,
  provider_account_id: 1,
  provider_account_label: "Anthropic",
  series_kind: "account",
  series_id: "user_01",
  label: "ana@example.com",
  kind: "spike",
  day: "2026-08-11",
  end_day: "2026-08-11",
  ongoing: false,
  duration_days: 1,
  actual: "1420.00",
  expected: "610.00",
  upper_bound: "890.00",
  lower_bound: null,
  baseline_method: "weekday",
  baseline_samples: 8,
  impact: "810.00",
  impact_percent: "132.79",
  impact_share: "12.40",
  total_actual: "1420.00",
  total_expected: "610.00",
  total_impact: "810.00",
  max_impact: "810.00",
  deviation: "12.87",
  severity: "high",
  currency: "USD",
  unit: "USD",
  status: "open",
  root_causes: [
    {
      kind: "model",
      id: "claude-opus-4-1",
      label: "claude-opus-4-1",
      actual: "900.00",
      baseline: "300.00",
      delta: "600.00",
    },
  ],
  owners: [
    { email: "ana@example.com", role: "used their own login", source: "login user_01" },
    { email: "owner@example.com", role: "organization owner", source: "Costura organization" },
  ],
  owners_gap: null,
  investigate: {
    by: "account",
    filters: { provider: "anthropic", provider_account: "1", account: "user_01" },
    measure: "billed_usd",
  },
  detected_at: "2026-08-12T06:02:00Z",
  updated_at: "2026-08-12T06:02:00Z",
};

export const orgAnomaly: Anomaly = {
  ...anomaly,
  id: 8,
  series_kind: "org",
  series_id: "__org__",
  label: "organization total",
  actual: "1900.00",
  expected: "1000.00",
  upper_bound: "1300.00",
  impact: "900.00",
  impact_percent: "90.00",
  total_actual: "1900.00",
  total_expected: "1000.00",
  total_impact: "900.00",
  max_impact: "900.00",
  deviation: "6.00",
  investigate: {
    by: "workspace",
    filters: { provider: "anthropic", provider_account: "1" },
    measure: "billed_usd",
  },
  root_causes: [
    {
      kind: "api_key",
      id: "apikey_1",
      label: "prod-backend (apikey_1)",
      actual: "1200.00",
      baseline: "400.00",
      delta: "800.00",
      share: "71.00",
    },
    {
      kind: "account",
      id: "user_01",
      label: "ana@example.com",
      actual: "1420.00",
      baseline: "610.00",
      delta: "810.00",
    },
  ],
  owners: [
    { email: "bruno@example.com", role: "created the key", source: "prod-backend (apikey_1)" },
    { email: "ana@example.com", role: "used their own login", source: "login user_01" },
    { email: "owner@example.com", role: "organization owner", source: "Costura organization" },
  ],
};

/** A key that never spent on that weekday before: trailing baseline, expected 0, no percent. */
export const newKeyAnomaly: Anomaly = {
  ...anomaly,
  id: 9,
  series_kind: "api_key",
  series_id: "apikey_9",
  label: "experiment (apikey_9)",
  day: "2026-08-09",
  end_day: "2026-08-09",
  actual: "58.47",
  expected: "0.00",
  upper_bound: "5.00",
  baseline_method: "trailing",
  baseline_samples: 12,
  impact: "58.47",
  impact_percent: null,
  total_actual: "58.47",
  total_expected: "0.00",
  total_impact: "58.47",
  max_impact: "58.47",
  deviation: null,
  severity: "medium",
  root_causes: [
    {
      kind: "model",
      id: "claude-sonnet-4",
      label: "claude-sonnet-4",
      actual: "58.33",
      baseline: "0.00",
      delta: "58.33",
    },
  ],
};

export const anomalies: Anomalies = {
  month: MONTH,
  start: `${MONTH}-01`,
  end: `${MONTH}-31`,
  window_total: "6532.26",
  open_count: 3,
  open_total: 3,
  total: 0,
  limit: 500,
  offset: 0,
  anomalies: [orgAnomaly, anomaly, newKeyAnomaly],
};

/** A four-day level shift still running: one row, one frozen baseline, summed totals. */
const episodeAnomaly: Anomaly = {
  ...orgAnomaly,
  id: 11,
  day: "2026-08-14",
  end_day: "2026-08-17",
  ongoing: true,
  duration_days: 4,
  total_actual: "7600.00",
  total_expected: "4000.00",
  total_impact: "3600.00",
  max_impact: "900.00",
  severity: "high",
};

/** The organization's spend stopped on a settled day: a drop, with a lower bound. */
const dropAnomaly: Anomaly = {
  ...orgAnomaly,
  id: 12,
  kind: "drop",
  day: "2026-08-18",
  end_day: "2026-08-18",
  actual: "120.00",
  expected: "1000.00",
  lower_bound: "700.00",
  impact: "880.00",
  impact_percent: "88.00",
  total_actual: "120.00",
  total_expected: "1000.00",
  total_impact: "880.00",
  max_impact: "880.00",
  deviation: "5.87",
  severity: "high",
  root_causes: [
    {
      kind: "api_key",
      id: "apikey_1",
      label: "prod-backend (apikey_1)",
      actual: "20.00",
      baseline: "400.00",
      delta: "-380.00",
    },
  ],
};

/** A key in its first days spending a share of the organization's day: no baseline exists. */
const newPrincipalAnomaly: Anomaly = {
  ...newKeyAnomaly,
  id: 13,
  kind: "new_principal",
  day: "2026-08-19",
  end_day: "2026-08-20",
  duration_days: 2,
  actual: "240.00",
  expected: "0.00",
  upper_bound: "0.00",
  baseline_method: "new_series",
  baseline_samples: 0,
  impact: "240.00",
  total_actual: "420.00",
  total_expected: "0.00",
  total_impact: "420.00",
  max_impact: "240.00",
  deviation: null,
  severity: "medium",
};

/** The three rule families in one list, for the badges and the episode wording. */
export const mixedAnomalies: Anomalies = {
  month: MONTH,
  start: `${MONTH}-01`,
  end: `${MONTH}-31`,
  window_total: "6532.26",
  open_count: 3,
  open_total: 3,
  total: 0,
  limit: 500,
  offset: 0,
  anomalies: [dropAnomaly, newPrincipalAnomaly, episodeAnomaly],
};

export const noAnomalies: Anomalies = {
  month: MONTH,
  start: `${MONTH}-01`,
  end: `${MONTH}-31`,
  window_total: "6532.26",
  open_count: 0,
  open_total: 0,
  total: 0,
  limit: 500,
  offset: 0,
  anomalies: [],
};

/** Eight weeks of Tuesdays at 600 plus a flat 500 on other days, the spike on the last day. */
function anomalySeries(): AnomalyDetail["series"] {
  const points: AnomalyDetail["series"] = [];
  const end = Date.UTC(2026, 7, 11);
  for (let k = 56; k >= 0; k -= 1) {
    const day = new Date(end - k * 86_400_000).toISOString().slice(0, 10);
    const sample = k > 0 && k % 7 === 0;
    points.push({
      day,
      amount: k === 0 ? "1420.00" : sample ? "610.00" : "500.00",
      baseline_sample: sample,
    });
  }
  return points;
}

export const anomalyEvidence: AnomalyEvidence = {
  baseline: {
    method: "weekday",
    trend_per_week: "0.00",
    sensitivity: "normal",
    samples: [
      { day: "2026-08-04", amount: "610.00", value: "610.00", adjusted: false },
      { day: "2026-07-28", amount: "590.00", value: "590.00", adjusted: false },
      { day: "2026-07-21", amount: "640.00", value: "640.00", adjusted: false },
      { day: "2026-07-14", amount: "610.00", value: "610.00", adjusted: false },
      { day: "2026-07-07", amount: "580.00", value: "580.00", adjusted: false },
      { day: "2026-06-30", amount: "620.00", value: "620.00", adjusted: false },
      { day: "2026-06-23", amount: "600.00", value: "600.00", adjusted: false },
      { day: "2026-06-16", amount: "615.00", value: "615.00", adjusted: false },
    ],
    median: "610.00",
    mad: "62.95",
    margin_mad: "280.00",
    margin_relative: "122.00",
    margin_absolute: "5.00",
    margin_rule: "mad",
    margin: "280.00",
    upper_bound: "890.00",
    lower_bound: "330.00",
    stored_actual: "1420.00",
    stored_expected: "610.00",
    stored_upper_bound: "890.00",
    actual_now: "1420.00",
    matches_stored: true,
  },
  checks: [
    {
      name: "above_upper_bound",
      passed: true,
      observed: "1420.00",
      threshold: "890.00",
      reason: "within upper bound",
    },
    {
      name: "amount_floor",
      passed: true,
      observed: "1420.00",
      threshold: "5.00",
      reason: "below 5 USD",
    },
    {
      name: "impact_floor",
      passed: true,
      observed: "810.00",
      threshold: "10.00",
      reason: "impact below 10 USD",
    },
    {
      name: "organization_share",
      passed: true,
      observed: "1420.00",
      threshold: "18.20",
      reason: "below 0.5% of the organization total",
    },
    {
      name: "recent_average",
      passed: true,
      observed: "1420.00",
      threshold: "540.00",
      reason: "not 20% above the trailing 7-day average",
    },
    {
      name: "previous_day",
      passed: true,
      observed: "1420.00",
      threshold: "600.00",
      reason: "not above the previous day",
    },
    {
      name: "history",
      passed: true,
      observed: "71",
      threshold: "12",
      reason: "fewer than 12 days of history",
    },
    {
      name: "suppression",
      passed: true,
      observed: "1420.00",
      threshold: null,
      reason: "not above another anomaly in the same series within 7 days",
    },
  ],
  breakdowns: [
    {
      dimension: "model",
      rows: [
        {
          key: "claude-opus-4-1",
          label: "claude-opus-4-1",
          amount: "900.00",
          tokens: { ...ZERO_TOKENS, uncached_input_tokens: 40_000_000, output_tokens: 5_000_000 },
          request_count: 12_000,
          cost_per_million: "20.0000",
          trailing_average: "300.00",
          delta: "600.00",
          new: false,
        },
        {
          key: "claude-sonnet-4",
          label: "claude-sonnet-4",
          amount: "520.00",
          tokens: { ...ZERO_TOKENS, uncached_input_tokens: 150_000_000, output_tokens: 8_000_000 },
          request_count: 30_000,
          cost_per_million: "3.2911",
          trailing_average: "310.00",
          delta: "210.00",
          new: false,
        },
      ],
    },
    {
      dimension: "api_key",
      rows: [
        {
          key: "apikey_1",
          label: "prod-backend (apikey_1)",
          amount: "1200.00",
          tokens: { ...ZERO_TOKENS, uncached_input_tokens: 180_000_000, output_tokens: 12_000_000 },
          request_count: 40_000,
          cost_per_million: "6.2500",
          trailing_average: "400.00",
          delta: "800.00",
          new: false,
        },
        {
          key: "apikey_9",
          label: "migration-script (apikey_9)",
          amount: "220.00",
          tokens: { ...ZERO_TOKENS, uncached_input_tokens: 10_000_000, output_tokens: 1_000_000 },
          request_count: 2_000,
          cost_per_million: "20.0000",
          trailing_average: "0.00",
          delta: "220.00",
          new: true,
        },
      ],
    },
  ],
  unit_economics: {
    day: {
      amount: "1420.00",
      tokens: { ...ZERO_TOKENS, uncached_input_tokens: 190_000_000, output_tokens: 13_000_000 },
      total_tokens: 203_000_000,
      request_count: 42_000,
      cost_per_million: "6.9951",
    },
    baseline: {
      amount: "610.00",
      tokens: { ...ZERO_TOKENS, uncached_input_tokens: 170_000_000, output_tokens: 11_000_000 },
      total_tokens: 181_000_000,
      request_count: 38_000,
      cost_per_million: "3.3702",
    },
    sample_days: 8,
  },
  data_quality: {
    runs: [
      {
        id: 41,
        endpoint: "anomaly_detection",
        status: "succeeded",
        started_at: "2026-08-12T06:05:00Z",
        finished_at: "2026-08-12T06:05:04Z",
        rows_upserted: 3,
      },
      {
        id: 40,
        endpoint: "allocation",
        status: "succeeded",
        started_at: "2026-08-12T06:04:00Z",
        finished_at: "2026-08-12T06:04:30Z",
        rows_upserted: 812,
      },
      {
        id: 39,
        endpoint: "cost_report",
        status: "succeeded",
        started_at: "2026-08-12T06:00:00Z",
        finished_at: "2026-08-12T06:03:00Z",
        rows_upserted: 240,
      },
    ],
    cost_lines: 12,
    usage_lines: 48,
    allocated_lines: 96,
    unallocated_amount: "0.00",
    changed_since_detection: false,
  },
  history: [
    {
      id: 3,
      kind: "spike",
      day: "2026-07-02",
      actual: "980.00",
      impact: "370.00",
      status: "acknowledged",
    },
  ],
};

export const anomalyDetail: AnomalyDetail = {
  ...anomaly,
  series: anomalySeries(),
  same_day: [
    {
      id: orgAnomaly.id,
      kind: orgAnomaly.kind,
      series_kind: "org",
      series_id: "__org__",
      label: "organization total",
      impact: "900.00",
      status: "open",
    },
  ],
  evidence: anomalyEvidence,
};

export const alertsOff: Alerts = {
  opted_in: false,
  unread_count: 0,
  items: [],
  signals: [],
  unread_by_kind: {},
};

export const alerts: Alerts = {
  opted_in: true,
  unread_count: 2,
  items: [
    { ...orgAnomaly, read_at: null },
    { ...anomaly, read_at: null },
    { ...newKeyAnomaly, read_at: "2026-08-12T09:00:00Z" },
  ],
  signals: [],
  unread_by_kind: { anomaly: 2 },
};

const budgetSignal: InboxSignal = {
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
  detected_at: "2026-08-14T08:00:00Z",
  reference: "4",
  occurrences: 1,
  read_reference: "17",
  read_at: null,
};

const noOwnerSignal: InboxSignal = {
  kind: "no_owner",
  provider: "openrouter",
  entity_kind: "api_key",
  entity_id: "orkey_hash_1",
  label: "router-prod (orkey_hash_1)",
  detail: "no owner in the provider inventory or in Costura",
  dollars_at_risk: "120.00",
  currency: "USD",
  owner: null,
  owner_role: null,
  detected_at: "2026-08-14T08:00:00Z",
  reference: "orkey_hash_1",
  occurrences: 1,
  read_reference: "orkey_hash_1",
  read_at: null,
};

/** The anomalies of `alerts` plus one unread budget alert and one unread key gap. */
export const mixedAlerts: Alerts = {
  ...alerts,
  unread_count: 4,
  signals: [budgetSignal, noOwnerSignal],
  unread_by_kind: { anomaly: 2, budget: 1, no_owner: 1 },
};

export const openRouterAnomaly: Anomaly = {
  ...newKeyAnomaly,
  id: 21,
  provider: OTHER_PROVIDER,
  provider_account_id: 2,
  provider_account_label: "OpenRouter",
  series_id: "orkey_hash_1",
  label: "router-prod (orkey_hash_1)",
  root_causes: [],
};

export const noSignals: Signals = { items: [], total: 0, snoozed: [] };

export const signals: Signals = {
  total: 4,
  snoozed: [],
  items: [
    {
      kind: "anomaly",
      provider: "anthropic",
      entity_kind: "api_key",
      entity_id: "apikey_1",
      label: "prod-backend (apikey_1)",
      detail: "spike, high severity",
      dollars_at_risk: "900.00",
      currency: "USD",
      owner: "ana@example.com",
      owner_role: "created the key",
      detected_at: "2026-08-12T06:00:00Z",
      reference: "8",
      occurrences: 1,
    },
    {
      kind: "no_limit",
      provider: "openrouter",
      entity_kind: "api_key",
      entity_id: "or_gateway",
      label: "gateway (or_gateway)",
      detail: "no spend limit at the provider",
      dollars_at_risk: "740.00",
      currency: "USD",
      owner: null,
      owner_role: null,
      detected_at: "2026-08-31T12:00:00Z",
      reference: "or_gateway",
      occurrences: 1,
    },
    {
      kind: "budget",
      provider: "anthropic",
      entity_kind: "org",
      entity_id: "__org__",
      label: "organization total",
      detail: "projected over the budget",
      dollars_at_risk: "120.00",
      currency: "USD",
      owner: "owner@example.com",
      owner_role: "organization owner",
      detected_at: "2026-08-20T06:00:00Z",
      reference: "3",
      occurrences: 1,
    },
    {
      kind: "new_key",
      provider: "openai",
      entity_kind: "api_key",
      entity_id: "key_new",
      label: "fresh (key_new)",
      detail: "created 2026-08-30",
      dollars_at_risk: "0.00",
      currency: "USD",
      owner: "bob@example.com",
      owner_role: "creator",
      detected_at: "2026-08-31T12:00:00Z",
      reference: "key_new",
      occurrences: 1,
    },
  ],
};
