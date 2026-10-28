import type { Anomaly } from "@/lib/api";
import { encodeFilterClause } from "@/lib/query-export";
import { openOrgHref } from "@/lib/setup";

function daysBefore(day: string, days: number): string {
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() - days);
  return date.toISOString().slice(0, 10);
}

/**
 * Analyze over the 60 days up to the episode's end, filtered to its series, under the
 * anomaly's own provider: the filters name ids of that provider, so the cookie scope must not
 * decide. The dates stay on the Analyze address, which says that it changed the time frame.
 */
export function investigateHref(anomaly: Anomaly, org: string): string {
  const params = new URLSearchParams({
    by: anomaly.investigate.by,
    measure: anomaly.investigate.measure,
    from: daysBefore(anomaly.end_day, 59),
    to: anomaly.end_day,
    interval: "day",
  });
  for (const [dimension, value] of Object.entries(anomaly.investigate.filters)) {
    params.append("f", encodeFilterClause(dimension, { op: "is", values: [value] }));
  }
  return openOrgHref(org, `/explore?${params.toString()}`, { scope: anomaly.provider });
}
