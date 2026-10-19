import { KpiCard } from "@/components/kpi-card";
import type { AnomalyDetail } from "@/lib/api";
import { SEVERITY_LABEL, deviationSentence, shareSentence } from "@/lib/anomaly-impact";
import { episodeSentence, formatAnomalyValue, impactAmount, isDrop } from "@/lib/anomaly-text";
import { formatPercent } from "@/lib/format";

/** Impact, severity, distance from the baseline and the first day's figure. */
export function AnomalyFigures({ detail }: { detail: AnomalyDetail }) {
  const severity = detail.severity;
  const share = shareSentence(detail.impact_share);
  const episode = episodeSentence(detail);
  const deviation = deviationSentence(detail.deviation);
  const falling = isDrop(detail);
  return (
    <section aria-label="Headline figures" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <KpiCard
        label="Impact"
        value={impactAmount(detail)}
        unit={detail.unit === "USD" ? detail.currency : undefined}
        hint={[
          episode
            ? `over ${detail.duration_days} days; worst day ${formatAnomalyValue(detail, detail.max_impact)}`
            : falling
              ? "missing from the expected amount on the day"
              : "spent above the expected amount on the day",
          share,
        ]
          .filter(Boolean)
          .join("; ")}
      />
      <KpiCard
        label="Severity"
        value={SEVERITY_LABEL[severity].replace(" severity", "")}
        hint={
          deviation
            ? `${deviation}; impact and swing together`
            : "the series has no usual swing to compare against"
        }
      />
      <KpiCard
        label={falling ? "Under the baseline" : "Over the baseline"}
        value={detail.impact_percent ? `${formatPercent(detail.impact_percent)}` : "-"}
        hint={
          detail.impact_percent
            ? `expected ${formatAnomalyValue(detail, detail.expected)}`
            : `nothing expected; upper bound ${formatAnomalyValue(detail, detail.upper_bound)}`
        }
      />
      <KpiCard
        label={
          detail.unit === "USD"
            ? episode
              ? "Spent on the first day"
              : "Spent that day"
            : episode
              ? "Observed on the first day"
              : "Observed that day"
        }
        value={formatAnomalyValue(detail, detail.actual)}
        unit={detail.unit === "USD" ? detail.currency : undefined}
        hint={
          falling
            ? `lower bound ${formatAnomalyValue(detail, detail.lower_bound ?? detail.expected)}`
            : detail.kind === "new_principal"
              ? "its first days; no baseline yet"
              : `upper bound ${formatAnomalyValue(detail, detail.upper_bound)}`
        }
      />
    </section>
  );
}
