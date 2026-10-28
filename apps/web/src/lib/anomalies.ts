import type { Marker } from "@/lib/ui-types";
import type { Anomaly } from "@/lib/api";
import { splitLabel } from "@/lib/dimensions";
import { signedImpact } from "@/lib/anomaly-text";
import { formatSignedUsd } from "@/lib/format";

const MARKER_CAUSES = 3;
const ORG_MARKER_RADIUS = 5;
const SERIES_MARKER_RADIUS = 3;

/**
 * One chart marker per first day with open anomalies, naming the top contributors by their
 * episode's impact, signed (a drop reads "-"). The marker runs to the last episode's end day.
 * A day where the organization total itself is off its baseline gets the larger dot.
 */
export function anomalyMarkers(anomalies: Anomaly[]): Marker[] {
  const byDay = new Map<string, Anomaly[]>();
  for (const anomaly of anomalies) {
    byDay.set(anomaly.day, [...(byDay.get(anomaly.day) ?? []), anomaly]);
  }
  return [...byDay.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([day, rows]) => {
      const ranked = [...rows].sort((a, b) => Number(b.total_impact) - Number(a.total_impact));
      const hasOrg = rows.some((a) => a.series_kind === "org");
      const causes = ranked
        .slice(0, MARKER_CAUSES)
        .map(
          (a) => `${splitLabel(a.label).name} ${formatSignedUsd(signedImpact(a, a.total_impact))}`,
        )
        .join("; ");
      const endDay = rows.reduce((last, a) => (a.end_day > last ? a.end_day : last), day);
      const count = rows.length === 1 ? "1 anomaly" : `${rows.length} anomalies`;
      return {
        day,
        endDay,
        kind: "open",
        label: rows.length === 1 ? `${count}: ${splitLabel(ranked[0]!.label).name}` : count,
        note: `${causes}${rows.length > MARKER_CAUSES ? "; ..." : ""}`,
        impact: ranked[0]!.total_impact,
        radius: hasOrg ? ORG_MARKER_RADIUS : SERIES_MARKER_RADIUS,
        emphasis: hasOrg ? ("primary" as const) : ("secondary" as const),
        count: rows.length,
        href: rows.length === 1 ? `/anomalies/${rows[0]!.id}` : "/anomalies",
      };
    });
}
