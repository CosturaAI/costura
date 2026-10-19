import { StatusBadge } from "@/components/status-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  BASELINE_METHOD_LABELS,
  MARGIN_RULE_LABELS,
  SENSITIVITY_LABELS,
} from "@/lib/anomaly-evidence";
import { weekdayName } from "@/lib/anomaly-text";
import type { BaselineEvidence, MarginRule } from "@/lib/api";
import { formatDayShort, formatMeasure, formatUsd } from "@/lib/format";
import { MethodHint } from "@/components/method-hint";

const RULES: MarginRule[] = ["mad", "relative", "absolute"];

/** The sample days the detector used, their median and spread, the trend it carried them
 * along, and the margin that fixed the bounds at the organization's sensitivity. */
export function AnomalyBaseline({ baseline, unit }: { baseline: BaselineEvidence; unit: string }) {
  const amount = (value: string) => (unit === "USD" ? formatUsd(value) : formatMeasure(value));
  const margins: Record<MarginRule, string> = {
    mad: baseline.margin_mad,
    relative: baseline.margin_relative,
    absolute: baseline.margin_absolute,
  };
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div>
        <h3 className="mb-2 text-sm font-medium">
          Sample days ({baseline.samples.length}, {BASELINE_METHOD_LABELS[baseline.method]})
        </h3>
        <Table aria-label="Baseline samples">
          <TableHeader>
            <TableRow>
              <TableHead>day</TableHead>
              <TableHead className="text-right">amount</TableHead>
              <TableHead className="text-right">read as</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {baseline.samples.map((sample) => (
              <TableRow key={sample.day}>
                <TableCell>
                  <span className="text-muted-foreground">{weekdayName(sample.day)}</span>{" "}
                  <span className="font-mono text-xs">{formatDayShort(sample.day)}</span>
                </TableCell>
                <TableCell className="text-right font-mono text-xs">
                  {amount(sample.amount)}
                </TableCell>
                <TableCell className="text-right font-mono text-xs">
                  {amount(sample.value)}
                  {sample.adjusted ? (
                    <span className="ml-1 text-muted-foreground">
                      <MethodHint
                        text="acknowledged"
                        method="An acknowledged episode covers this day, so the baseline reads its expected amount instead."
                      />
                    </span>
                  ) : null}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <dl className="space-y-3 text-sm">
        <Figure label="Median (the expected amount)" value={amount(baseline.median)} unit={unit} />
        <Figure label="Median absolute deviation (MAD)" value={amount(baseline.mad)} unit={unit} />
        <div>
          <dt className="text-xs text-muted-foreground">Candidate margins; the largest wins</dt>
          <dd>
            <ul className="mt-1 divide-y divide-border">
              {RULES.map((rule) => (
                <li key={rule} className="flex items-center justify-between gap-3 py-1.5">
                  <span className="flex items-center gap-2">
                    {MARGIN_RULE_LABELS[rule]}
                    {rule === baseline.margin_rule ? (
                      <StatusBadge tone="info">fixed the bound</StatusBadge>
                    ) : null}
                  </span>
                  <span className="font-mono text-xs">{amount(margins[rule])}</span>
                </li>
              ))}
            </ul>
          </dd>
        </div>
        <Figure
          label="Upper bound (median + margin)"
          value={`${amount(baseline.median)} + ${amount(baseline.margin)} = ${amount(baseline.upper_bound)}`}
          unit={unit}
        />
        <Figure
          label="Lower bound (median - margin, never below zero)"
          value={`${amount(baseline.median)} - ${amount(baseline.margin)} = ${amount(baseline.lower_bound)}`}
          unit={unit}
        />
        <div>
          <dt className="text-xs text-muted-foreground">Trend carried into the samples</dt>
          <dd className="font-mono">
            {amount(baseline.trend_per_week)}{" "}
            <span className="text-xs text-muted-foreground">{unit} per week</span>
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Sensitivity</dt>
          <dd>{SENSITIVITY_LABELS[baseline.sensitivity]}</dd>
        </div>
      </dl>
    </div>
  );
}

function Figure({ label, value, unit }: { label: string; value: string; unit: string }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-mono">
        {value} <span className="text-xs text-muted-foreground">{unit}</span>
      </dd>
    </div>
  );
}
