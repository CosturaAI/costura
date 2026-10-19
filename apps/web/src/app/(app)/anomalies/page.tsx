import type { Metadata } from "next";
import { ClosedSignals } from "@/components/closed-signals";
import { AreaNav, GUARDRAILS } from "@/components/area-nav";
import { KpiCard } from "@/components/kpi-card";
import { PageHeader } from "@/components/page-header";
import { QueryChips } from "@/components/query-chips";
import { api } from "@/lib/api";
import { formatUsd } from "@/lib/format";
import { periodPhrase } from "@/lib/time-range";
import { first, oneOf, type Search } from "@/lib/search";
import { canOperate } from "@/lib/roles";
import { SEVERITY_LABEL } from "@/lib/anomaly-impact";
import { impactTotals } from "@/lib/anomaly-text";

import { requireView } from "@/lib/view";
import { AnomalyList } from "./anomaly-list";

export const metadata: Metadata = { title: "Anomalies" };

const STATUS_FILTERS = ["open", "acknowledged", "ignored", "all"] as const;
const STATUS_OPTIONS = [
  { value: "open", label: "Open" },
  { value: "acknowledged", label: "Acknowledged" },
  { value: "ignored", label: "Ignored" },
  { value: "all", label: "All" },
] as const;

const SORT_OPTIONS_VALUES = ["day", "impact", "severity"] as const;
const SORT_OPTIONS = [
  { value: "day", label: "By day" },
  { value: "impact", label: "By impact" },
  { value: "severity", label: "By severity" },
] as const;

const KIND_FILTERS = ["all", "org", "account", "api_key"] as const;
const KIND_OPTIONS = [
  { value: "all", label: "Everything" },
  { value: "org", label: "Organization" },
  { value: "account", label: "Users" },
  { value: "api_key", label: "API keys" },
] as const;

export default async function AnomaliesPage({ searchParams }: { searchParams?: Promise<Search> }) {
  const { org, provider, period } = await requireView();
  const inPeriod = periodPhrase(period.from, period.to);
  const query = (await searchParams) ?? {};
  const status = oneOf(first(query.status), STATUS_FILTERS, "open");
  const kind = oneOf(first(query.kind), KIND_FILTERS, "all");
  const sort = oneOf(first(query.sort), SORT_OPTIONS_VALUES, "day");
  const anomalyRequest = api.anomalies(
    org,
    provider,
    period,
    status === "all" ? undefined : status,
    undefined,
    sort,
  );

  const [result, organization, setup, history] = await Promise.all([
    anomalyRequest,
    api.org(org),
    api.setup(org),
    api.signalHistory(org).catch(() => null),
  ]);
  const canWrite = setup.writes_enabled && !organization.is_demo && canOperate(organization.role);
  const anomalies =
    kind === "all" ? result.anomalies : result.anomalies.filter((a) => a.series_kind === kind);
  const unscopedOpen =
    status === "open"
      ? result
      : await api.anomalies(org, provider, period, "open", undefined, "impact");
  const open = unscopedOpen.anomalies;
  const currency = open[0]?.currency ?? result.anomalies[0]?.currency ?? "USD";
  const impact = impactTotals(open);
  const days = new Set(open.map((anomaly) => anomaly.day)).size;
  const ongoing = open.filter((anomaly) => anomaly.ongoing).length;
  const worst = [...unscopedOpen.anomalies].sort(
    (a, b) =>
      ({ low: 0, medium: 1, high: 2 })[b.severity] - { low: 0, medium: 1, high: 2 }[a.severity],
  )[0];
  return (
    <div className="space-y-5">
      <AreaNav label="Guardrails" items={GUARDRAILS} current="/anomalies" />
      <PageHeader
        title={`Anomalies ${inPeriod}`}
        description={`Days ${inPeriod} that left their own baseline; consecutive days are one episode.`}
      />

      <section
        aria-label="Summary"
        className="grid grid-cols-1 gap-2 min-[480px]:grid-cols-3 sm:gap-4"
      >
        <KpiCard
          label="Open"
          value={String(unscopedOpen.open_count)}
          className="min-w-0 py-3 sm:py-4 [&_[data-slot=card-header]]:px-3 sm:[&_[data-slot=card-header]]:px-4 [&_[data-slot=card-title]]:text-lg sm:[&_[data-slot=card-title]]:text-2xl"
          hint={
            worst
              ? `worst: ${SEVERITY_LABEL[worst.severity]}`
              : status === "open" || status === "all"
                ? `none ${inPeriod}`
                : `${status} shown below; open ones on the Open filter`
          }
        />
        <KpiCard
          label="Open impact"
          value={formatUsd(impact.over)}
          unit={currency}
          className="min-w-0 py-3 sm:py-4 [&_[data-slot=card-header]]:px-3 sm:[&_[data-slot=card-header]]:px-4 [&_[data-slot=card-title]]:text-lg sm:[&_[data-slot=card-title]]:text-2xl"
          hint={
            impact.under > 0
              ? `spend above expected, summed; drops are ${formatUsd(impact.under)} under it`
              : "spend above expected over every episode, summed"
          }
        />
        <KpiCard
          label="Days affected"
          value={String(days)}
          className="min-w-0 py-3 sm:py-4 [&_[data-slot=card-header]]:px-3 sm:[&_[data-slot=card-header]]:px-4 [&_[data-slot=card-title]]:text-lg sm:[&_[data-slot=card-title]]:text-2xl"
          hint={
            ongoing > 0
              ? `with at least one open anomaly; ${ongoing} still running`
              : days > 0
                ? "with at least one open anomaly"
                : `none ${inPeriod}`
          }
        />
      </section>

      <details className="rounded-md border border-border bg-background px-4 py-3 text-sm">
        <summary className="cursor-pointer font-medium text-secondary-foreground">
          How detection works
        </summary>
        <p className="mt-2 max-w-4xl text-muted-foreground">
          A series is flagged when a day rises above its upper bound, falls below its lower bound,
          or a new key or login takes an unusual share before it has history. Severity weighs the
          money against that series&apos; usual swing.
        </p>
      </details>

      <details className="rounded-md border border-border bg-background px-4 py-3 text-sm">
        <summary className="cursor-pointer font-medium text-secondary-foreground">Filters</summary>
        <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-3">
          <QueryChips
            name="status"
            value={status}
            options={STATUS_OPTIONS}
            label="Status"
            size="sm"
          />
          <QueryChips
            name="kind"
            value={kind === "all" ? "" : kind}
            options={KIND_OPTIONS.map((o) => ({
              value: o.value === "all" ? "" : o.value,
              label: o.label,
            }))}
            label="Series"
            size="sm"
          />
          <QueryChips name="sort" value={sort} options={SORT_OPTIONS} label="Order" size="sm" />
        </div>
      </details>

      {anomalies.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border bg-background p-8 text-center text-sm text-muted-foreground">
          {status === "open" && kind === "all"
            ? `No open anomalies ${inPeriod}. Anomalies are re-evaluated with every import.`
            : `No ${status === "all" ? "" : status + " "}anomalies${kind === "all" ? "" : ` for ${KIND_OPTIONS.find((o) => o.value === kind)?.label.toLowerCase()}`} ${inPeriod}.`}
        </div>
      ) : (
        <section aria-label="Anomaly feed">
          <AnomalyList
            anomalies={anomalies}
            org={org}
            provider={provider}
            periodTotal={result.window_total}
            canWrite={canWrite}
            sort={sort}
          />
        </section>
      )}

      <ClosedSignals history={history} />
    </div>
  );
}
