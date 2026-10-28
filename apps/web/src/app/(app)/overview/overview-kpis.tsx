import Link from "next/link";

import { Sparkline } from "@/components/charts/sparkline";
import { KpiCard } from "@/components/kpi-card";
import { MethodHint } from "@/components/method-hint";
import type { Anomalies, BudgetStatus, SpendQuery, Summary } from "@/lib/api";
import { SEVERITY_LABEL } from "@/lib/anomaly-impact";
import { anomalyHref, signedImpact } from "@/lib/anomaly-text";
import {
  formatDayRange,
  formatDayShort,
  formatDelta,
  formatMonth,
  formatPercent,
  formatSignedUsd,
  formatUsd,
} from "@/lib/format";
import { providerVerdict, type ScopeProjection } from "@/lib/overview";
import { cn } from "@/lib/utils";
import { intervalLabel, rangeDays, type QueryInterval } from "@/lib/time-range";

type OverviewFigures = {
  summary: Summary;
  series: SpendQuery;
  projection: ScopeProjection | null;
  orgBudget: BudgetStatus | null;
  anomalies: Anomalies | null;
  from: string;
  to: string;
  interval: QueryInterval;
  inPeriod: string;
  currency: string;
  isMonthView: boolean;
  /** The figures cover part of the period they compare with a complete one. */
  partial: boolean;
  rangeTotal: string;
  displayedTotal: string;
  displayedChange: string | null;
  previousRangeTotal: string | null;
};

/** "; 87% of budget" appended to the projection KPI hint when an org budget exists. */
function budgetHint(status: BudgetStatus | null): string {
  if (!status) return "";
  const percent = status.projected_percent ?? status.percent;
  return `; ${formatPercent(percent)} of the ${formatUsd(status.budget.amount)} budget`;
}

/** The highest bucket of the range with spend, or null when every bucket is empty. */
function peakBucket(totals: readonly string[]): { index: number; value: number } | null {
  return totals.reduce<{ index: number; value: number } | null>((current, value, index) => {
    const amount = Number(value);
    return Number.isFinite(amount) && amount > 0 && (!current || amount > current.value)
      ? { index, value: amount }
      : current;
  }, null);
}

/** The four headline figures: total, projection or daily average, open anomalies, and a fourth
 * that depends on the view (peak day, cache reads, key concentration or days with spend). */
export function OverviewKpis(figures: OverviewFigures) {
  return (
    <section aria-label="Headline figures" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <TotalKpi {...figures} />
      <PaceKpi {...figures} />
      <AnomaliesKpi {...figures} />
      <FourthKpi {...figures} />
    </section>
  );
}

function ProviderCheck({ summary }: { summary: Summary }) {
  const verdict = providerVerdict(summary);
  return (
    <p>
      <Link
        href="/reconcile"
        className={cn(
          "hover:underline",
          verdict.tone === "success" && "text-severity-success",
          verdict.tone === "critical" && "text-severity-critical",
        )}
      >
        {verdict.text}
      </Link>
    </p>
  );
}

function dailyAverageOf({
  summary,
  isMonthView,
  rangeTotal,
  from,
  to,
}: OverviewFigures): number | string | null {
  return isMonthView ? summary.daily_average : Number(rangeTotal) / rangeDays(from, to);
}

function TotalKpi(figures: OverviewFigures) {
  const { summary, series, from, to, currency, isMonthView, partial } = figures;
  const { displayedTotal, displayedChange, previousRangeTotal } = figures;
  const days = rangeDays(from, to);
  const change = Number.parseFloat(displayedChange ?? "0");
  const mixed = isMonthView ? (summary.currency_totals ?? null) : null;
  return (
    <KpiCard
      label="Total"
      emphasis="primary"
      value={mixed ? "-" : formatUsd(displayedTotal)}
      unit={mixed ? "several currencies" : currency}
      delta={formatDelta(displayedChange)}
      deltaTone={change > 0 ? "critical" : change < 0 && !partial ? "success" : "neutral"}
      hint={
        isMonthView && summary.previous_total
          ? `${summary.comparison_basis === "month_to_date" ? formatDayRange(summary.previous_start, summary.previous_end) : formatMonth(summary.previous_month)}: ${formatUsd(summary.previous_total)}`
          : previousRangeTotal !== null && Number(previousRangeTotal) > 0
            ? `previous period: ${formatUsd(previousRangeTotal)}`
            : undefined
      }
    >
      <Sparkline values={series.total.map(String)} />
      {Number(displayedTotal) > 0 ? (
        <p>
          {isMonthView ? summary.days_with_data : days} days{" "}
          {isMonthView ? "with spend" : "selected"}, {formatUsd(dailyAverageOf(figures))} a day
          {isMonthView && summary.last_day_with_data
            ? `, last ${formatDayShort(summary.last_day_with_data)}`
            : ""}
        </p>
      ) : null}
      {mixed ? (
        <p>
          {Object.entries(mixed)
            .map(([code, amount]) => `${formatUsd(amount)} ${code}`)
            .join(" + ")}
          ; amounts in different currencies are not added.
        </p>
      ) : null}
      {isMonthView ? <ProviderCheck summary={summary} /> : null}
      {isMonthView && summary.byok_total !== null ? (
        <p>
          plus {formatUsd(summary.byok_total)} {currency} on your own provider keys, billed by those
          providers
        </p>
      ) : null}
    </KpiCard>
  );
}

function PaceKpi(figures: OverviewFigures) {
  const { summary, projection, orgBudget, from, to, currency, isMonthView } = figures;
  const projecting = summary.is_current_month;
  if (projecting && projection) {
    return (
      <KpiCard
        label="Projected end of month"
        value={formatUsd(projection.projected_total)}
        unit={currency}
        hint={
          <MethodHint
            text={`${formatUsd(projection.low)} to ${formatUsd(projection.high)}${budgetHint(orgBudget)}`}
            method={`Same weekday over the last 4 weeks; band from the last 8; as of ${formatDayShort(projection.as_of_day)}.`}
          />
        }
      />
    );
  }
  if (projecting && isMonthView) {
    return (
      <KpiCard
        label="Projected end of month"
        value={formatUsd(summary.projected_total)}
        unit={currency}
        hint={
          <MethodHint
            text={`run rate${budgetHint(orgBudget)}`}
            method="Daily average x days in the month, until the scheduler stores a projection."
          />
        }
      />
    );
  }
  return (
    <KpiCard
      label="Daily average"
      value={formatUsd(dailyAverageOf(figures))}
      unit={currency}
      hint={
        isMonthView && summary.last_day_with_data
          ? `over the ${summary.days_with_data} days with spend`
          : `over the ${rangeDays(from, to)} selected days`
      }
    />
  );
}

function AnomaliesKpi({ anomalies, inPeriod, currency }: OverviewFigures) {
  const worst = anomalies?.anomalies[0];
  return (
    <KpiCard
      label="Open anomalies"
      value={anomalies ? String(anomalies.open_count) : "-"}
      hint={
        !anomalies ? (
          "could not be loaded; reload to retry"
        ) : anomalies.open_count === 0 || !worst ? (
          `nothing left its baseline ${inPeriod}`
        ) : (
          <Link href={anomalyHref(worst.id)} className="text-primary hover:underline">
            worst: {SEVERITY_LABEL[worst.severity].toLowerCase()},{" "}
            {formatSignedUsd(signedImpact(worst, worst.total_impact))} {currency} off baseline
          </Link>
        )
      }
    />
  );
}

function FourthKpi({
  summary,
  series,
  from,
  to,
  interval,
  currency,
  isMonthView,
}: OverviewFigures) {
  const days = rangeDays(from, to);
  if (!isMonthView) {
    const peak = peakBucket(series.total.map(String));
    if (peak) {
      return (
        <KpiCard
          label="Peak day"
          value={formatUsd(peak.value)}
          unit={currency}
          hint={`${formatDayShort(series.buckets[peak.index] ?? "")}; highest ${intervalLabel(interval, { lower: true })} bucket`}
        />
      );
    }
    const daysWithSpend = series.total.filter((value) => Number(value) > 0).length;
    return (
      <KpiCard
        label="Days with spend"
        value={String(daysWithSpend)}
        hint={`of ${days} selected days`}
      />
    );
  }
  if (summary.cache_read_share !== null) {
    return (
      <KpiCard
        label="Cache reads"
        value={formatPercent(summary.cache_read_share)}
        hint="of input tokens served from the prompt cache"
      />
    );
  }
  if (summary.top_keys_share !== null) {
    return (
      <KpiCard
        label="Top 5 keys"
        value={formatPercent(summary.top_keys_share)}
        hint={`of spend, across ${summary.top_key_count} keys with usage`}
      />
    );
  }
  return (
    <KpiCard
      label="Days with spend"
      value={String(summary.days_with_data)}
      hint={`of ${summary.days_in_month} days in the month`}
    />
  );
}
