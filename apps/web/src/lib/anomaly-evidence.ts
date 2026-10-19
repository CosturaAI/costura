import type {
  AnomalyCheck,
  BaselineEvidence,
  BaselineMethod,
  CheckName,
  MarginRule,
  Sensitivity,
  UnitEconomics,
  UsageTotals,
} from "@/lib/api";
import { formatInteger, formatUsd } from "@/lib/format";

/**
 * The detector's noise filters in the words a reader can verify against the numbers. The
 * thresholds that move with the organization's sensitivity (the impact floor, the share of
 * the 7-day average) are named, not quoted: the figure itself is in the threshold column of
 * the table, straight from the detector.
 */
export const CHECK_LABELS: Record<CheckName, { label: string; threshold: string }> = {
  above_upper_bound: { label: "Above the upper bound", threshold: "upper bound" },
  amount_floor: { label: "At least 5 USD spent", threshold: "5 USD" },
  impact_floor: { label: "Far enough from the expected amount", threshold: "impact floor" },
  organization_share: {
    label: "At least 0.5% of the organization's day",
    threshold: "0.5% of the organization total",
  },
  recent_average: {
    label: "Away from the trailing 7-day average",
    threshold: "share of the 7-day average",
  },
  previous_day: { label: "Above the previous day", threshold: "previous day" },
  below_lower_bound: { label: "Below the lower bound", threshold: "lower bound" },
  expected_floor: { label: "At least 20 USD was expected", threshold: "20 USD" },
  complete_day: {
    label: "The day is settled",
    threshold: "2 days after the day",
  },
  provider_reported: {
    label: "The provider reported the organization's day",
    threshold: "more than 0 USD",
  },
  new_series: { label: "Less than 12 days of history", threshold: "12 days" },
  new_principal_floor: { label: "At least 25 USD spent", threshold: "25 USD" },
  new_principal_share: {
    label: "At least 5% of the organization's day",
    threshold: "5% of the organization total",
  },
  history: { label: "At least 12 days of history", threshold: "12 days" },
  suppression: {
    label: "Above any episode of this series in the 7 days before",
    threshold: "largest recent episode",
  },
};

export const MARGIN_RULE_LABELS: Record<MarginRule, string> = {
  mad: "the MAD multiple of the sensitivity",
  relative: "the share of the median of the sensitivity",
  absolute: "5 USD",
};

/** Which history the expected amount came from. */
export const BASELINE_METHOD_LABELS: Record<BaselineMethod, string> = {
  weekday: "same weekday",
  monthly: "same day of month",
  window: "equal previous windows",
  active_days: "active days",
  trailing: "trailing 28 days",
  new_series: "no history",
};

export const SENSITIVITY_LABELS: Record<Sensitivity, string> = {
  low: "low: wide bounds, fewer flags",
  normal: "normal",
  high: "high: narrow bounds, more flags",
};

/** Checks measured in days rather than dollars. */
const DAY_CHECKS: ReadonlySet<CheckName> = new Set<CheckName>([
  "history",
  "new_series",
  "complete_day",
]);

export function checkValue(check: AnomalyCheck, value: string | null): string {
  if (value === null) return "-";
  if (DAY_CHECKS.has(check.name)) return `${Number(value).toFixed(0)} days`;
  return formatUsd(value);
}

export function checksVerdict(checks: AnomalyCheck[], baseline: BaselineEvidence | null): string {
  if (checks.length === 0) {
    return "The series has no data before this day any more, so the checks cannot be recomputed.";
  }
  const held = checks.filter((c) => c.passed).length;
  const rule = baseline ? `; the margin came from ${MARGIN_RULE_LABELS[baseline.margin_rule]}` : "";
  if (held === checks.length) return `${held} of ${checks.length} checks hold${rule}.`;
  const failing = checks
    .filter((c) => !c.passed)
    .map((c) => CHECK_LABELS[c.name].label.toLowerCase());
  return `${held} of ${checks.length} checks hold with today's data; failing: ${failing.join(", ")}${rule}.`;
}

export function changedSentence(baseline: BaselineEvidence): string | null {
  if (baseline.matches_stored) return null;
  const parts: string[] = [];
  if (baseline.stored_actual !== baseline.actual_now) {
    parts.push(`spent ${formatUsd(baseline.stored_actual)}, now ${formatUsd(baseline.actual_now)}`);
  }
  if (baseline.stored_expected !== baseline.median) {
    parts.push(
      `expected ${formatUsd(baseline.stored_expected)}, now ${formatUsd(baseline.median)}`,
    );
  }
  if (baseline.stored_upper_bound !== baseline.upper_bound) {
    parts.push(
      `upper bound ${formatUsd(baseline.stored_upper_bound)}, now ${formatUsd(baseline.upper_bound)}`,
    );
  }
  return `The day's data changed after detection: ${parts.join("; ")}.`;
}

type EconomicsMove = {
  key: "tokens" | "price" | "requests";
  label: string;
  day: string;
  baseline: string;
  ratio: number | null;
};

function ratio(day: number, baseline: number): number | null {
  if (baseline <= 0) return day > 0 ? Infinity : null;
  return day / baseline;
}

export function economicsMoves(economics: UnitEconomics): EconomicsMove[] {
  const { day, baseline } = economics;
  const price = (t: UsageTotals) =>
    t.cost_per_million === null ? null : Number(t.cost_per_million);
  return [
    {
      key: "tokens",
      label: "Tokens",
      day: formatInteger(day.total_tokens),
      baseline: formatInteger(baseline.total_tokens),
      ratio: ratio(day.total_tokens, baseline.total_tokens),
    },
    {
      key: "price",
      label: "Cost per M tokens",
      day: price(day) === null ? "-" : formatUsd(price(day)),
      baseline: price(baseline) === null ? "-" : formatUsd(price(baseline)),
      ratio:
        price(day) === null || price(baseline) === null
          ? null
          : ratio(price(day)!, price(baseline)!),
    },
    {
      key: "requests",
      label: "Requests",
      day: formatInteger(day.request_count),
      baseline: formatInteger(baseline.request_count),
      ratio: ratio(day.request_count, baseline.request_count),
    },
  ];
}

/** Share of output, cache and reasoning tokens in the total, as percentages. */
export function tokenMix(totals: UsageTotals): { label: string; percent: number }[] {
  const total = totals.total_tokens;
  const groups: { label: string; keys: string[] }[] = [
    { label: "Input", keys: ["uncached_input_tokens"] },
    {
      label: "Cache",
      keys: ["cache_creation_5m_tokens", "cache_creation_1h_tokens", "cache_read_tokens"],
    },
    { label: "Output", keys: ["output_tokens"] },
    { label: "Reasoning", keys: ["reasoning_tokens"] },
  ];
  return groups.map(({ label, keys }) => {
    const sum = keys.reduce((acc, key) => acc + (totals.tokens[key] ?? 0), 0);
    return { label, percent: total > 0 ? (sum / total) * 100 : 0 };
  });
}

/** One sentence naming what moved most between the baseline days and the anomaly day. */
export function economicsSentence(economics: UnitEconomics): string {
  if (economics.day.total_tokens === 0 && economics.baseline.total_tokens === 0) {
    return "No usage report covers this series, so tokens and requests are unknown; the amounts come from the cost report alone.";
  }
  const moves = economicsMoves(economics).filter((m) => m.ratio !== null && m.key !== "requests");
  if (moves.length === 0)
    return "Tokens are known for one side only; the price cannot be compared.";
  const biggest = moves.reduce((a, b) =>
    Math.abs(Math.log(b.ratio!)) > Math.abs(Math.log(a.ratio!)) ? b : a,
  );
  if (!Number.isFinite(biggest.ratio!)) {
    return `${biggest.label} went from nothing on the baseline days to ${biggest.day} on this day.`;
  }
  const times = biggest.ratio!.toFixed(1);
  if (biggest.key === "tokens") {
    return `Volume moved most: ${times} x the tokens of a baseline day at a similar price per token.`;
  }
  return `Price moved most: ${times} x the cost per million tokens of a baseline day (a model switch, a cache miss or a price change).`;
}
