import type { Tone } from "@/lib/ui-types";
import type { Anomaly, AnomalySeverity } from "@/lib/api";

/**
 * Severity comes from the detector, which weighs the money against the series' own history:
 * a small spike on a series that never moves outranks a big one on a series that swings
 * every day. The web reads `severity` and never recomputes
 * it, so the page and the list agree.
 */
type Severity = AnomalySeverity;

export const SEVERITY_TONE: Record<Severity, Tone> = {
  low: "neutral",
  medium: "warning",
  high: "critical",
};

export const SEVERITY_LABEL: Record<Severity, string> = {
  low: "low severity",
  medium: "medium severity",
  high: "high severity",
};

/** "3.4 x the series' usual swing", the deviation behind the severity; null when the series
 * has no swing to measure (a flat series, or a key with no history). */
export function deviationSentence(deviation: string | null): string | null {
  if (deviation === null) return null;
  const value = Number(deviation);
  if (!Number.isFinite(value) || value <= 0) return null;
  return `${value.toFixed(1)} x the series' usual swing`;
}

/** "12.3% of its month's spend to date": the share the detector stored, against the spend of
 * the anomaly's month up to its day; null when that spend is unknown. */
export function shareSentence(share: string | null): string | null {
  if (share === null) return null;
  const value = Number(share);
  if (!Number.isFinite(value)) return null;
  return `${percentText(value)} of its month's spend to date`;
}

export function periodShareSentence(anomaly: Anomaly, periodTotal: string): string | null {
  const total = Number(periodTotal);
  const impact = Math.abs(Number(episodeImpact(anomaly)));
  if (!Number.isFinite(total) || total <= 0 || !Number.isFinite(impact)) return null;
  return `${percentText((impact / total) * 100)} of the period's spend`;
}

function percentText(value: number): string {
  return value < 0.05 ? "<0.1%" : `${value.toFixed(1)}%`;
}

/** The figure a reader compares across anomalies: the whole episode, not one of its days. */
function episodeImpact(anomaly: Anomaly): string {
  return anomaly.total_impact;
}
