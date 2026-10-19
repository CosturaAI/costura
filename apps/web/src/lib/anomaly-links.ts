import type { Anomaly } from "@/lib/api";
import { encodeFilterClause } from "@/lib/query-export";

function daysBefore(day: string, days: number): string {
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() - days);
  return date.toISOString().slice(0, 10);
}

export function investigateHref(anomaly: Anomaly): string {
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
  return `/explore?${params.toString()}`;
}
