import type { Schema } from "./schema";
/**
 * Anomalies, their evidence and the caller's anomaly inbox.
 */

import type { RunStatus } from "./connections";
import type { Owner } from "./inventory";
import type { QueryMeasure } from "./spend";
import { get, periodPath, periodQuery, scope, send, type Period } from "./transport";

/** Every kind a daily series exists for: projections use the first four, root causes and
 * Explore the dimensions, anomalies only `AnomalySeriesKind`. */
export type SeriesKind = "org" | "workspace" | "model" | "api_key" | "account";

/** Anomaly series: the organization total and the principals, an API key or the
 * user behind a Claude Code login. */
export type AnomalySeriesKind =
  | "org"
  | "api_key"
  | "account"
  | "workspace"
  | "model"
  | "model_brand"
  | "model_family"
  | "provider"
  | "origin"
  | "person"
  | "token_type"
  | "cost_type"
  | `tag:${string}`;

export type AnomalyStatus = "open" | "acknowledged" | "ignored";

type RootCause = {
  kind: SeriesKind;
  id: string;
  label: string;
  actual: string;
  baseline: string;
  delta: string;
  share?: string | null;
};

/** Which rule found the anomaly: a day above the upper bound, a day below the
 * lower bound, or a key or login spending a share of the day before it has any history. */
export type AnomalyKind = "spike" | "drop" | "new_principal";

export type AnomalySeverity = "low" | "medium" | "high";

/** How the expected amount was computed: the same weekday, the days the series actually ran,
 * the trailing 28 days, or nothing at all for a series younger than 12 days. */
export type BaselineMethod =
  "weekday" | "monthly" | "window" | "active_days" | "trailing" | "new_series";

/** One row per episode: consecutive days under the same rule share one frozen baseline, so
 * `day` is the first anomalous day and `end_day` the last one found so far. */
export type Anomaly = Omit<
  Schema<"AnomalyOut">,
  | "series_kind"
  | "kind"
  | "baseline_method"
  | "severity"
  | "status"
  | "root_causes"
  | "owners"
  | "investigate"
> & {
  series_kind: AnomalySeriesKind;
  kind: AnomalyKind;
  baseline_method: BaselineMethod;
  severity: AnomalySeverity;
  status: AnomalyStatus;
  root_causes: RootCause[];
  owners: Owner[];
  investigate: {
    by: string;
    filters: Record<string, string>;
    measure: QueryMeasure;
  };
};

export type Anomalies = Omit<Schema<"AnomaliesOut">, "anomalies"> & {
  anomalies: Anomaly[];
};

/** How wide the detector's bounds are. `low` flags less and asks for more money before it
 * does; `high` flags more. */
export type Sensitivity = "low" | "normal" | "high";

export type SeriesPoint = { day: string; amount: string; baseline_sample: boolean };

type SameDayAnomaly = {
  id: number;
  kind: AnomalyKind;
  series_kind: AnomalySeriesKind;
  series_id: string;
  label: string;
  impact: string;
  status: AnomalyStatus;
};

/** `amount` is what the day spent; `value` is what the baseline read, which differs when an
 * acknowledged episode covers the day and its expected amount stands in for it. */
type BaselineSample = {
  day: string;
  amount: string;
  value: string;
  adjusted: boolean;
};

export type MarginRule = "mad" | "relative" | "absolute";

/** The detector's arithmetic recomputed from the data: the sample days, median and MAD, the
 * three candidate margins and the one that fixed the bounds, next to the stored figures. */
export type BaselineEvidence = Omit<
  Schema<"BaselineEvidenceOut">,
  "method" | "samples" | "sensitivity" | "margin_rule"
> & {
  method: BaselineMethod;
  samples: BaselineSample[];
  sensitivity: Sensitivity;
  margin_rule: MarginRule;
};

export type CheckName =
  | "above_upper_bound"
  | "amount_floor"
  | "impact_floor"
  | "organization_share"
  | "recent_average"
  | "previous_day"
  | "below_lower_bound"
  | "expected_floor"
  | "complete_day"
  | "provider_reported"
  | "new_series"
  | "new_principal_floor"
  | "new_principal_share"
  | "history"
  | "suppression";

export type AnomalyCheck = Omit<Schema<"CheckOut">, "name"> & {
  name: CheckName;
};

export type DayRow = {
  key: string | null;
  label: string;
  amount: string | null;
  tokens: Record<string, number>;
  request_count: number;
  cost_per_million: string | null;
  trailing_average: string | null;
  delta: string | null;
  /** No spend in the eight weeks before the day. */
  new: boolean;
};

export type DayBreakdown = { dimension: string; rows: DayRow[] };

export type UsageTotals = {
  amount: string;
  tokens: Record<string, number>;
  total_tokens: number;
  request_count: number;
  cost_per_million: string | null;
};

export type UnitEconomics = { day: UsageTotals; baseline: UsageTotals; sample_days: number };

type RunSummary = {
  id: number;
  endpoint: string;
  status: RunStatus;
  started_at: string;
  finished_at: string | null;
  rows_upserted: number;
};

type DataQuality = {
  runs: RunSummary[];
  cost_lines: number;
  usage_lines: number;
  allocated_lines: number;
  unallocated_amount: string;
  changed_since_detection: boolean;
};

type HistoryItem = {
  id: number;
  kind: AnomalyKind;
  day: string;
  actual: string;
  impact: string;
  status: AnomalyStatus;
};

export type AnomalyEvidence = Omit<
  Schema<"EvidenceOut">,
  "baseline" | "checks" | "breakdowns" | "unit_economics" | "data_quality" | "history"
> & {
  baseline: BaselineEvidence | null;
  checks: AnomalyCheck[];
  breakdowns: DayBreakdown[];
  unit_economics: UnitEconomics | null;
  data_quality: DataQuality;
  history: HistoryItem[];
};

/** `GET .../anomalies/{id}`: the anomaly, eight weeks of its series ending on its day, the
 * other anomalies of that day and the evidence recomputed from the data. */
export type AnomalyDetail = Anomaly & {
  series: SeriesPoint[];
  same_day: SameDayAnomaly[];
  evidence: AnomalyEvidence;
};

export type AlertItem = Anomaly & { read_at: string | null };
export type InboxSignal = Schema<"InboxSignalOut">;
export type SignalRead = Schema<"SignalReadIn">;

/** `GET /orgs/{org}/alerts`: the caller's inbox for one organization: anomalies in `items`,
 * budget alerts and key gaps in `signals`, unread counts per kind in `unread_by_kind`. */
export type Alerts = Omit<Schema<"AlertsOut">, "items"> & { items: AlertItem[] };

export type Signal = Schema<"SignalOut">;
export type SignalKind = Signal["kind"];
export type Signals = Schema<"SignalsOut">;
export type ClosedSignal = Omit<Schema<"ClosedSignalOut">, "kind"> & { kind: SignalKind };
export type SignalHistory = { items: ClosedSignal[] };
/** A key gap a member snoozed; it is out of `Signals.items` until `until`. */
export type Snooze = Schema<"SnoozeOut">;
type SnoozeIn = Schema<"SnoozeIn">;

export const anomaliesApi = {
  signals: (org: string, provider: string) => get<Signals>(`${scope(org, provider)}/signals`),
  /** Signals of every provider closed in the last 90 days, newest first. */
  signalHistory: (org: string) =>
    get<SignalHistory>(`/orgs/${encodeURIComponent(org)}/signals/history`),
  snoozeGap: (org: string, provider: string, body: SnoozeIn) =>
    send<Snooze>("PUT", `${scope(org, provider)}/signals/snoozes`, body),
  liftSnooze: (org: string, provider: string, kind: string, keyId: string) =>
    send<void>(
      "DELETE",
      `${scope(org, provider)}/signals/snoozes/${encodeURIComponent(kind)}/${encodeURIComponent(keyId)}`,
    ),
  anomalies: (
    org: string,
    provider: string,
    period: Period,
    status?: AnomalyStatus,
    series?: { kind: string; id: string },
    sort?: "day" | "impact" | "severity",
    person?: string,
  ) =>
    get<Anomalies>(`${scope(org, provider)}/months/${periodPath(period)}/anomalies`, {
      ...periodQuery(period),
      status,
      series_kind: series?.kind,
      series_id: series?.id,
      sort,
      person,
    }),
  /** One anomaly with owners, series and same-day anomalies; 404 outside the organization
   * or, under a concrete provider, for an anomaly of another provider. */
  anomaly: (org: string, provider: string, id: number) =>
    get<AnomalyDetail>(`${scope(org, provider)}/anomalies/${id}`),
  setAnomalyStatus: (
    org: string,
    provider: string,
    id: number,
    status: AnomalyStatus,
    reason?: string | null,
  ) =>
    send<Anomaly>(
      "PATCH",
      `${scope(org, provider)}/anomalies/${id}`,
      reason ? { status, reason } : { status },
    ),
  /** The caller's anomaly inbox; empty with `opted_in: false` before the opt-in and on the
   * sample organization. 401 without a session. */
  alerts: (org: string) => get<Alerts>(`/orgs/${encodeURIComponent(org)}/alerts`),
  setAlertSettings: (org: string, optedIn: boolean) =>
    send<Alerts>("PUT", `/orgs/${encodeURIComponent(org)}/alerts/settings`, {
      opted_in: optedIn,
    }),
  markAlertsRead: (
    org: string,
    selection: { ids: number[] } | { signals: SignalRead[] } | { all: true },
  ) =>
    send<Alerts>(
      "POST",
      `/orgs/${encodeURIComponent(org)}/alerts/read`,
      "all" in selection
        ? { all: true }
        : "signals" in selection
          ? { signals: selection.signals }
          : { anomaly_ids: selection.ids },
    ),
};
