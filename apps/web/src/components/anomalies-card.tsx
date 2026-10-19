import Link from "next/link";

import { CardHeading } from "@/components/card-heading";
import { StatusBadge } from "@/components/status-badge";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import type { Anomaly } from "@/lib/api";
import { SEVERITY_LABEL, SEVERITY_TONE, periodShareSentence } from "@/lib/anomaly-impact";
import {
  ANOMALY_KIND_LABELS,
  KIND_LABELS,
  anomalyHref,
  episodeSentence,
  impactAmount,
  isDrop,
} from "@/lib/anomaly-text";
import { splitLabel } from "@/lib/dimensions";
import { formatDayShort } from "@/lib/format";
import { hasAccountLabel, isAll, sourceLabel } from "@/lib/providers";
import { periodPhrase } from "@/lib/time-range";

const TOP = 3;

/**
 * The worst open episodes of the time frame, the card the overview leads its watch band with:
 * detection is what the product is for. Severity, not money, orders the list, since the
 * detector already weighs the money against the series' own history.
 */
export function AnomaliesCard({
  anomalies,
  provider,
  period,
  periodTotal,
}: {
  /** Open anomalies of the period in the API's `sort=severity` order; null when the call failed. */
  anomalies: Anomaly[] | null;
  provider: string;
  period: { from: string; to: string };
  periodTotal: string;
}) {
  const rows = (anomalies ?? []).slice(0, TOP);
  const showProvider = isAll(provider);

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div>
          <CardHeading>Open anomalies</CardHeading>
          <CardDescription>
            Days that left the series&apos; own baseline, worst first.
          </CardDescription>
        </div>
        <Link href={`/anomalies`} className="shrink-0 text-sm text-primary hover:underline">
          {anomalies && anomalies.length > TOP ? `All ${anomalies.length}` : "All anomalies"}
        </Link>
      </CardHeader>
      <CardContent>
        {anomalies === null ? (
          <p className="text-sm text-severity-critical">
            Could not load the anomalies; reload to retry.
          </p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Nothing off baseline {periodPhrase(period.from, period.to)}. The detector runs after
            every import and compares each key, account, model and workspace with its own history.
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {rows.map((anomaly) => {
              const episode = episodeSentence(anomaly);
              const share = periodShareSentence(anomaly, periodTotal);
              return (
                <li key={anomaly.id} className="py-2 text-sm first:pt-0 last:pb-0">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                    <span className="flex min-w-0 items-center gap-2">
                      <StatusBadge tone={SEVERITY_TONE[anomaly.severity]}>
                        {SEVERITY_LABEL[anomaly.severity]}
                      </StatusBadge>
                      {anomaly.kind === "spike" ? null : (
                        <StatusBadge tone={isDrop(anomaly) ? "info" : "warning"}>
                          {ANOMALY_KIND_LABELS[anomaly.kind]}
                        </StatusBadge>
                      )}
                      {showProvider ||
                      hasAccountLabel(anomaly.provider, anomaly.provider_account_label) ? (
                        <StatusBadge tone="neutral">
                          {sourceLabel(anomaly.provider, anomaly.provider_account_label)}
                        </StatusBadge>
                      ) : null}
                      <Link
                        href={anomalyHref(anomaly.id)}
                        className="min-w-0 font-medium break-words hover:text-primary"
                        title={anomaly.label}
                      >
                        {splitLabel(anomaly.label).name}
                      </Link>
                    </span>
                    <span className="shrink-0 font-mono text-xs text-foreground">
                      {impactAmount(anomaly)}{" "}
                      <span className="text-muted-foreground">{anomaly.currency}</span>
                    </span>
                  </div>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {KIND_LABELS[anomaly.series_kind]}; {formatDayShort(anomaly.day)}
                    {episode ? `; ${episode}` : ""}
                    {share ? `; ${share}` : ""}
                  </p>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
