import Link from "next/link";

import { AnomalyBaseline } from "@/components/anomaly-baseline";
import { AnomalyChecks } from "@/components/anomaly-checks";
import { AnomalyDayTable } from "@/components/anomaly-day-table";
import { CardHeading } from "@/components/card-heading";
import { Notice } from "@/components/notice";
import { StatusBadge, runTone } from "@/components/status-badge";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { AnomalyDetail, UsageTotals } from "@/lib/api";
import {
  changedSentence,
  checksVerdict,
  economicsMoves,
  economicsSentence,
  tokenMix,
} from "@/lib/anomaly-evidence";
import {
  KIND_LABELS,
  STATUS_TONE,
  anomalyHref,
  formatAnomalyValue,
  signedImpact,
  weekdayName,
} from "@/lib/anomaly-text";
import { splitLabel } from "@/lib/dimensions";
import {
  formatDateTime,
  formatDayShort,
  formatInteger,
  formatSignedUsd,
  formatUsd,
} from "@/lib/format";
import { providerLabel } from "@/lib/providers";
import { endpointLabel } from "@/lib/run-labels";
import { openOrgHref } from "@/lib/setup";

/** The supporting tables of one anomaly, folded under "Evidence": why it counts, the
 * baseline, the day's spend against its history, volume against price, the syncs behind the
 * data, the series' earlier anomalies and the other anomalies of the same day. */
export function AnomalyEvidence({ detail, org }: { detail: AnomalyDetail; org: string }) {
  return (
    <details className="rounded-md border border-border bg-background px-4 py-3 text-sm">
      <summary className="cursor-pointer font-medium text-secondary-foreground">Evidence</summary>
      <div className="mt-3 space-y-4">
        <WhyCard detail={detail} />
        <BaselineCard detail={detail} />
        <SpentThatDayCard detail={detail} />
        <div className="grid gap-4 lg:grid-cols-2">
          <VolumeOrPriceCard detail={detail} />
          <DataBehindCard detail={detail} org={org} />
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <SeriesHistoryCard detail={detail} />
          <SameDayCard detail={detail} />
        </div>
      </div>
    </details>
  );
}

function WhyCard({ detail }: { detail: AnomalyDetail }) {
  const { evidence } = detail;
  const changed = evidence.baseline ? changedSentence(evidence.baseline) : null;
  return (
    <Card>
      <CardHeader>
        <CardHeading>Why this counts as an anomaly</CardHeading>
        <CardDescription>{checksVerdict(evidence.checks, evidence.baseline)}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {changed ? <Notice>{changed}</Notice> : null}
        <AnomalyChecks checks={evidence.checks} />
      </CardContent>
    </Card>
  );
}

function BaselineCard({ detail }: { detail: AnomalyDetail }) {
  const { evidence } = detail;
  return (
    <Card>
      <CardHeader>
        <CardHeading>The baseline</CardHeading>
        <CardDescription>
          The exact days the detector compared this one against, recomputed from the data now.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {evidence.baseline ? (
          <AnomalyBaseline baseline={evidence.baseline} unit={detail.unit} />
        ) : (
          <p className="text-sm text-muted-foreground">
            The series has no data before this day any more; the stored expected amount was{" "}
            {formatAnomalyValue(detail, detail.expected)} from {detail.baseline_samples} samples.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function SpentThatDayCard({ detail }: { detail: AnomalyDetail }) {
  const { evidence } = detail;
  const flaggedDrivers = detail.same_day.filter((own) =>
    detail.root_causes.some(
      (cause) => cause.kind === own.series_kind && cause.id === own.series_id,
    ),
  );
  return (
    <Card>
      <CardHeader>
        <CardHeading>What was spent that day</CardHeading>
        <CardDescription>
          Every row below this series on {formatDayShort(detail.day)}, against its own trailing
          7-day average; &quot;new&quot; marks a row with no spend in the eight weeks before.
          {flaggedDrivers.length > 0 ? (
            <>
              {" "}
              Flagged on their own that day:{" "}
              {flaggedDrivers.map((own, index) => (
                <span key={own.id}>
                  {index > 0 ? ", " : null}
                  <Link href={anomalyHref(own.id)} className="text-primary hover:underline">
                    {splitLabel(own.label).name}
                  </Link>
                </span>
              ))}
              .
            </>
          ) : null}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <AnomalyDayTable breakdowns={evidence.breakdowns} />
      </CardContent>
    </Card>
  );
}

function VolumeOrPriceCard({ detail }: { detail: AnomalyDetail }) {
  const { evidence } = detail;
  return (
    <Card>
      <CardHeader>
        <CardHeading>Volume or price</CardHeading>
        <CardDescription>
          {evidence.unit_economics
            ? economicsSentence(evidence.unit_economics)
            : "No baseline days to compare tokens and price against."}
        </CardDescription>
      </CardHeader>
      {evidence.unit_economics ? (
        <CardContent>
          <Table aria-label="Volume or price">
            <TableHeader>
              <TableRow>
                <TableHead>figure</TableHead>
                <TableHead className="text-right">this day</TableHead>
                <TableHead className="text-right">
                  baseline day (mean of {evidence.unit_economics.sample_days})
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {economicsMoves(evidence.unit_economics).map((move) => (
                <TableRow key={move.key}>
                  <TableCell>{move.label}</TableCell>
                  <TableCell className="text-right font-mono text-xs">{move.day}</TableCell>
                  <TableCell className="text-right font-mono text-xs">{move.baseline}</TableCell>
                </TableRow>
              ))}
              <TableRow>
                <TableCell>Token mix</TableCell>
                <TableCell className="text-right font-mono text-xs">
                  {mixSentence(evidence.unit_economics.day)}
                </TableCell>
                <TableCell className="text-right font-mono text-xs">
                  {mixSentence(evidence.unit_economics.baseline)}
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </CardContent>
      ) : null}
    </Card>
  );
}

function DataBehindCard({ detail, org }: { detail: AnomalyDetail; org: string }) {
  const month = detail.day.slice(0, 7);
  const quality = detail.evidence.data_quality;
  return (
    <Card>
      <CardHeader>
        <CardHeading>Data behind the day</CardHeading>
        <CardDescription>
          The syncs whose window covers {formatDayShort(detail.day)} and the lines they left for
          this series.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {quality.changed_since_detection ? (
          <Notice>
            A cost or usage sync finished after this anomaly was detected; the figures above are
            recomputed from today&apos;s data.
          </Notice>
        ) : null}
        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Count label="cost lines" value={quality.cost_lines} />
          <Count label="usage lines" value={quality.usage_lines} />
          <Count label="allocated lines" value={quality.allocated_lines} />
          <div>
            <dt className="text-xs text-muted-foreground">unallocated</dt>
            <dd className="font-mono">{formatUsd(quality.unallocated_amount)}</dd>
          </div>
        </dl>
        {quality.runs.length === 0 ? (
          <p className="text-muted-foreground">No sync run covers this day.</p>
        ) : (
          <ul className="divide-y divide-border">
            {quality.runs.map((run) => (
              <li key={run.id} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
                <span className="flex items-center gap-2">
                  <StatusBadge tone={runTone(run.status)}>{run.status}</StatusBadge>
                  <Link
                    href={`/runs?endpoint=${encodeURIComponent(run.endpoint)}`}
                    className="text-primary hover:underline"
                  >
                    {endpointLabel(run.endpoint)}
                  </Link>
                  <span className="font-mono text-xs text-muted-foreground">#{run.id}</span>
                </span>
                <span className="text-xs text-muted-foreground">
                  {run.finished_at ? formatDateTime(run.finished_at) : "running"}
                  {run.rows_upserted > 0 ? `; ${run.rows_upserted} rows` : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
        <p className="text-xs">
          <Link
            prefetch={false}
            href={openOrgHref(org, "/reconcile", { scope: detail.provider, month })}
            className="text-primary hover:underline"
          >
            Reconcile the month
          </Link>
        </p>
      </CardContent>
    </Card>
  );
}

function SeriesHistoryCard({ detail }: { detail: AnomalyDetail }) {
  const { evidence } = detail;
  return (
    <Card>
      <CardHeader>
        <CardHeading>This series before</CardHeading>
        <CardDescription>Other anomalies of the same series, newest first.</CardDescription>
      </CardHeader>
      <CardContent>
        {evidence.history.length === 0 ? (
          <p className="text-sm text-muted-foreground">First anomaly of this series.</p>
        ) : (
          <ul className="divide-y divide-border text-sm">
            {evidence.history.map((item) => (
              <li
                key={item.id}
                className="flex flex-wrap items-baseline justify-between gap-x-4 py-2"
              >
                <span className="flex items-baseline gap-2">
                  <StatusBadge tone={STATUS_TONE[item.status]}>{item.status}</StatusBadge>
                  <Link href={anomalyHref(item.id)} className="text-primary hover:underline">
                    {weekdayName(item.day)}, {formatDayShort(item.day)}
                  </Link>
                </span>
                <span className="font-mono text-xs text-secondary-foreground">
                  {formatUsd(item.actual)} spent; {formatSignedUsd(signedImpact(item, item.impact))}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function SameDayCard({ detail }: { detail: AnomalyDetail }) {
  return (
    <Card>
      <CardHeader>
        <CardHeading>Same day</CardHeading>
        <CardDescription>
          Other series of {providerLabel(detail.provider)} flagged on {formatDayShort(detail.day)}.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {detail.same_day.length === 0 ? (
          <p className="text-sm text-muted-foreground">No other anomaly that day.</p>
        ) : (
          <ul className="divide-y divide-border text-sm">
            {detail.same_day.map((other) => (
              <li
                key={other.id}
                className="flex flex-wrap items-baseline justify-between gap-x-4 py-2"
              >
                <span className="flex min-w-0 items-baseline gap-2">
                  <StatusBadge tone={STATUS_TONE[other.status]}>{other.status}</StatusBadge>
                  <span className="text-xs text-muted-foreground">
                    {KIND_LABELS[other.series_kind]}
                  </span>
                  <Link
                    href={anomalyHref(other.id)}
                    className="truncate text-primary hover:underline"
                    title={other.label}
                  >
                    {splitLabel(other.label).name}
                  </Link>
                </span>
                <span className="font-mono text-xs text-secondary-foreground">
                  {formatSignedUsd(signedImpact(other, other.impact))}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function Count({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-mono">{formatInteger(value)}</dd>
    </div>
  );
}

/** "62% input, 30% cache, 8% output" for a token total; "-" when there are no tokens. */
function mixSentence(totals: UsageTotals): string {
  if (totals.total_tokens === 0) return "-";
  return tokenMix(totals)
    .filter((part) => part.percent > 0)
    .map((part) => `${part.percent.toFixed(0)}% ${part.label.toLowerCase()}`)
    .join(", ");
}
