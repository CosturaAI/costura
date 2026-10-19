import type { Tone } from "@/lib/ui-types";
import type { Anomaly, AnomalyKind, AnomalySeriesKind, AnomalyStatus } from "@/lib/api";
import { formatMeasure, formatUsd } from "@/lib/format";

/** Words shared by the anomaly list, the detail page and the alerts bell. */

export const KIND_LABELS: Record<string, string> = {
  org: "Organization",
  workspace: "Workspace",
  model: "Model",
  api_key: "API key",
  account: "Account",
  provider: "Provider",
  person: "Person",
  token_type: "Token type",
  cost_type: "Cost type",
};

export function kindLabel(kind: string): string {
  if (kind.startsWith("tag:")) return `Tag ${kind.slice(4)}`;
  return KIND_LABELS[kind] ?? kind;
}

/** The badge next to a principal: how the spend reached the provider. */
export const PRINCIPAL_BADGES: Partial<Record<AnomalySeriesKind, string>> = {
  account: "Claude Code login",
};

export const STATUS_TONE: Record<AnomalyStatus, Tone> = {
  open: "critical",
  acknowledged: "info",
  ignored: "neutral",
};

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export function weekdayName(day: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  if (!match) return "weekday";
  const utc = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return WEEKDAYS[(new Date(utc).getUTCDay() + 6) % 7] ?? "weekday";
}

/** What the rule looked for, as a badge on the card and the detail page. */
export const ANOMALY_KIND_LABELS: Record<AnomalyKind, string> = {
  spike: "spike",
  drop: "drop",
  new_principal: "new",
};

/** A drop is money that stopped arriving, not money spent: the amount is not an overspend,
 * so the list shows it in its own words and without the `+` sign. */
export function isDrop(anomaly: Pick<Anomaly, "kind">): boolean {
  return anomaly.kind === "drop";
}

export function signedImpact(anomaly: Pick<Anomaly, "kind">, impact: string): number {
  const value = Number(impact);
  return isDrop(anomaly) ? -value : value;
}

export function impactTotals(anomalies: Pick<Anomaly, "kind" | "total_impact">[]): {
  over: number;
  under: number;
} {
  let over = 0;
  let under = 0;
  for (const anomaly of anomalies) {
    if (isDrop(anomaly)) under += Number(anomaly.total_impact);
    else over += Number(anomaly.total_impact);
  }
  return { over, under };
}

/** Which baseline the detector used, in the words of the numbers stored next to it. */
export function baselineSentence(anomaly: Anomaly): string {
  const bound = isDrop(anomaly)
    ? `lower bound ${formatAnomalyValue(anomaly, anomaly.lower_bound ?? anomaly.expected)}`
    : `upper bound ${formatAnomalyValue(anomaly, anomaly.upper_bound)}`;
  if (anomaly.baseline_method === "new_series") {
    return `nothing to compare against: the series is less than 12 days old`;
  }
  const window =
    anomaly.baseline_method === "weekday"
      ? `the same ${weekdayName(anomaly.day)} over the last ${anomaly.baseline_samples} weeks`
      : anomaly.baseline_method === "monthly"
        ? `the same day over the last ${anomaly.baseline_samples} months`
        : anomaly.baseline_method === "window"
          ? `${anomaly.duration_days}-day total against ${anomaly.baseline_samples} prior periods`
          : anomaly.baseline_method === "active_days"
            ? `the ${anomaly.baseline_samples} days this series ran in the last 28`
            : `the trailing 28 days (${anomaly.baseline_samples} samples)`;
  if (Number(anomaly.expected) < 0.005) {
    return `nothing spent on ${window}, ${bound}`;
  }
  return `${window} was ${formatAnomalyValue(anomaly, anomaly.expected)}, ${bound}`;
}

/** The headline figure of the card, the bell and the detail page: the whole episode, signed
 * by direction. A `new_principal` has no baseline, so everything it spent is the figure. */
export function impactAmount(anomaly: Anomaly): string {
  const total = anomaly.kind === "new_principal" ? anomaly.total_actual : anomaly.total_impact;
  return `${isDrop(anomaly) ? "-" : "+"}${formatAnomalyValue(anomaly, total)}`;
}

export function formatAnomalyValue(anomaly: Pick<Anomaly, "unit">, value: string): string {
  if (anomaly.unit === "USD") return formatUsd(value);
  return `${formatMeasure(value)} ${anomaly.unit}`;
}

/** "ongoing, 4 days since 12 Sep" or null on a one-day episode. Consecutive days under the
 * same rule are one row with one frozen baseline. */
export function episodeSentence(anomaly: Anomaly): string | null {
  if (anomaly.duration_days <= 1) return null;
  const run = `${anomaly.duration_days} days`;
  return anomaly.ongoing ? `ongoing, ${run} so far` : run;
}

/** Anomalies grouped by day, newest first, each day ordered by impact. */
export function groupByDay(anomalies: Anomaly[]): { day: string; rows: Anomaly[] }[] {
  const byDay = new Map<string, Anomaly[]>();
  for (const anomaly of anomalies) {
    byDay.set(anomaly.day, [...(byDay.get(anomaly.day) ?? []), anomaly]);
  }
  return [...byDay.entries()]
    .sort(([a], [b]) => b.localeCompare(a))
    .map(([day, rows]) => ({
      day,
      rows: [...rows].sort((a, b) => Number(b.impact) - Number(a.impact)),
    }));
}

/** `/org/provider/month/anomalies/<id>`; under `all` the page stays under `all`, which the
 * API accepts for any provider of the organization. */
export function anomalyHref(id: number): string {
  return `/anomalies/${id}`;
}

/** "acknowledged by ana@example.com: expected: backfill", or null while the anomaly is open. */
export function triageLine(
  anomaly: Pick<Anomaly, "status" | "status_reason" | "status_changed_by">,
): string | null {
  if (anomaly.status === "open") return null;
  const who = anomaly.status_changed_by ? ` by ${anomaly.status_changed_by}` : "";
  const why = anomaly.status_reason ? `: ${anomaly.status_reason}` : "";
  return who || why ? `${anomaly.status}${who}${why}` : null;
}
