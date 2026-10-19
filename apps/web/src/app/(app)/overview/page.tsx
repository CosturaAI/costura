import type { Metadata } from "next";
import Link from "next/link";

import { ActivityCard } from "@/components/activity-card";
import { AnomaliesCard } from "@/components/anomalies-card";
import { CardHeading } from "@/components/card-heading";
import { BucketedSpendChart } from "@/components/charts/daily-spend-chart";
import { CouldNotLoad } from "@/components/could-not-load";
import { GettingStartedCard } from "@/components/getting-started-card";
import { MoversCard } from "@/components/movers-card";
import { PageHeader } from "@/components/page-header";
import { ProviderStrip } from "@/components/provider-strip";
import { QueryChips } from "@/components/query-chips";
import { NeedsAPerson } from "@/components/needs-a-person";
import { WhatChanged } from "@/components/what-changed";
import { SignalStrip } from "@/components/signal-strip";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { anomalyMarkers } from "@/lib/anomalies";
import { api } from "@/lib/api";
import { drillDownHref } from "@/lib/dimensions";
import {
  changePercent,
  formatDayRange,
  formatDelta,
  formatMonth,
  formatPercent,
  formatUsd,
} from "@/lib/format";
import {
  ACCOUNT_DIMENSION,
  coverageNote,
  loadOverviewDetails,
  overviewQuery,
  overviewSignals,
  scopeBudget,
  scopeProjection,
  type OverviewView,
} from "@/lib/overview";
import { isAll } from "@/lib/providers";
import { canOperate } from "@/lib/roles";
import { first, oneOf, type Search } from "@/lib/search";
import { gettingStartedItems } from "@/lib/setup";
import { queryChartData, queryTotal, valuesTotal } from "@/lib/spend-query";
import { intervalLabel, periodPhrase, periodTitle, rangeDays, wholeMonth } from "@/lib/time-range";

import { requireView } from "@/lib/view";
import { dismissSetupAction } from "./actions";
import {
  OverviewBudgetsCard,
  OverviewModelsCard,
  TopCard,
  type TableContext,
} from "./overview-cards";
import { OverviewKpis } from "./overview-kpis";
import { NoSpend } from "./overview-empty";

export const metadata: Metadata = { title: "Overview" };

const GROUPS = ["workspace", "api_key", "account", "model", "provider"] as const;
const GROUP_OPTIONS = [
  { value: "provider", label: "Provider" },
  { value: "workspace", label: "Workspace" },
  { value: "api_key", label: "API key" },
  { value: "account", label: "Account" },
  { value: "model", label: "Model" },
] as const;
const CHART_TOP = 6;
const CHART_HEIGHT = 300;

export default async function OverviewPage({ searchParams }: { searchParams?: Promise<Search> }) {
  const { org, provider, from, to, period, interval } = await requireView();
  const query = (await searchParams) ?? {};
  const aggregated = isAll(provider);
  // The provider grouping only makes sense when more than one provider is in scope.
  const groups = aggregated ? GROUPS : GROUPS.filter((g) => g !== "provider");
  const groupOptions = GROUP_OPTIONS.filter((o) => aggregated || o.value !== "provider");
  const by = oneOf(first(query.by), groups, aggregated ? "provider" : "workspace");
  const view: OverviewView = { org, provider, from, to, interval };

  // The detail reads depend on nothing the headline answers, so they start together with it.
  // An empty range has already sent them by the time the total is known; the waterfall they
  // would cost on every range with spend is the larger price.
  const detailsRead = loadOverviewDetails(view);
  const [summary, series, activity] = await Promise.all([
    api.summary(org, provider, period),
    overviewQuery(view, by, CHART_TOP),
    provider === "openai"
      ? api.activity(org, { since: from, until: to }).catch(() => null)
      : Promise.resolve(null),
  ]);
  const currency = summary.currency ?? "USD";
  const month = wholeMonth(from, to);
  const isMonthView = month !== null;
  const displayRange = periodTitle(from, to);
  const inPeriod = periodPhrase(from, to);
  const projecting = summary.is_current_month;
  const rangeTotal = queryTotal(series);
  const displayedTotal = isMonthView ? summary.total : rangeTotal;
  const previousRangeTotal = series.comparison ? valuesTotal(series.comparison.total) : null;
  const rangeChange = changePercent(rangeTotal, previousRangeTotal);

  if (!(Number(displayedTotal) > 0)) {
    // Called rather than rendered: the empty state awaits its own `setup` read.
    return await NoSpend({ org, provider, displayRange, activity });
  }

  const details = await detailsRead;
  const { keys, accountsWithoutLogin, personAccounts, models, movers, byProvider } = details;
  const { projections, anomalies, budgets, setup, organization } = details;
  // The API dismisses the card on the sample organization; the flag guards a stale answer.
  const isDemo = organization?.is_demo === true;
  const projection = scopeProjection(projections?.projections ?? []);
  const orgBudget = scopeBudget(budgets?.statuses ?? [], provider);
  const signals = overviewSignals(details, provider, orgBudget);
  const table: TableContext = { allocated: series.source === "allocated", currency, provider };
  const days = rangeDays(from, to);
  const providerShares =
    aggregated && byProvider
      ? byProvider.rows.map((row) => ({
          key: `${row.provider ?? "scope"}:${row.key ?? row.label}`,
          label: row.label,
          amount: row.amount ?? "0.00",
          share: row.share,
          href: drillDownHref("provider", row.key),
        }))
      : [];

  const comparedWith =
    summary.comparison_basis === "month_to_date"
      ? formatDayRange(summary.previous_start, summary.previous_end)
      : formatMonth(summary.previous_month);

  return (
    <div className="space-y-5">
      <PageHeader
        title={isMonthView ? `Spend ${inPeriod}` : `Spend, ${displayRange}`}
        description={
          isMonthView
            ? [
                summary.previous_total
                  ? `${formatDelta(summary.change_percent)} against ${comparedWith} (${formatUsd(summary.previous_total)} ${currency}).`
                  : `No data for ${formatMonth(summary.previous_month)} to compare with.`,
                coverageNote(summary),
              ]
                .filter(Boolean)
                .join(" ")
            : previousRangeTotal !== null && Number(previousRangeTotal) > 0 && rangeChange !== null
              ? `${formatDelta(rangeChange)} against the previous ${days} days (${formatUsd(previousRangeTotal)} ${currency}).`
              : `No spend in the previous ${days} days to compare with.`
        }
      >
        {isMonthView ? (
          <Link
            href={`/review?scope=${encodeURIComponent(provider)}&month=${month}`}
            className="text-sm text-primary hover:underline"
          >
            Month in review
          </Link>
        ) : null}
      </PageHeader>

      {setup && setup.dismissed_at === null && !isDemo ? (
        <GettingStartedCard
          items={gettingStartedItems(setup, {
            budgets: budgets?.statuses.length ?? 0,
            anomalies: anomalies?.open_count ?? 0,
          })}
          canDismiss={setup.writes_enabled && canOperate(organization?.role)}
          dismiss={dismissSetupAction}
        />
      ) : null}

      <OverviewKpis
        summary={summary}
        series={series}
        projection={projection}
        orgBudget={orgBudget}
        anomalies={anomalies}
        from={from}
        to={to}
        interval={interval}
        inPeriod={inPeriod}
        currency={currency}
        isMonthView={isMonthView}
        rangeTotal={rangeTotal}
        displayedTotal={displayedTotal}
        displayedChange={isMonthView ? summary.change_percent : rangeChange}
        previousRangeTotal={previousRangeTotal}
      />
      <SignalStrip items={signals} />
      <NeedsAPerson signals={details.signals} />
      <WhatChanged movers={movers} currency={currency} />

      <Card>
        <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
          <div>
            <CardHeading>{intervalLabel(interval)} spend</CardHeading>
            <CardDescription>
              {series.source === "cost"
                ? "From the provider cost report; attribution by key or account arrives with the import."
                : `Top ${CHART_TOP} by ${by.replace("_", " ")}, the rest as "other".`}
            </CardDescription>
          </div>
          <QueryChips name="by" value={by} options={groupOptions} label="Group by" size="sm" />
        </CardHeader>
        <CardContent className="space-y-4">
          {aggregated && !byProvider ? (
            <CouldNotLoad what="the provider breakdown" />
          ) : (
            <ProviderStrip items={providerShares} currency={currency} />
          )}
          <BucketedSpendChart
            data={queryChartData(series, by)}
            interval={interval}
            currency={currency}
            markers={interval === "day" && anomalies ? anomalyMarkers(anomalies.anomalies) : []}
            height={CHART_HEIGHT}
            legend={by === "provider" && providerShares.length >= 2 ? "markers" : "full"}
            projection={
              projecting && interval === "day" && projection
                ? { fromDay: projection.as_of_day, days: projection.days }
                : projecting &&
                    isMonthView &&
                    interval === "day" &&
                    summary.last_day_with_data &&
                    summary.daily_average
                  ? { fromDay: summary.last_day_with_data, dailyAverage: summary.daily_average }
                  : null
            }
          />
        </CardContent>
      </Card>

      {activity ? <ActivityCard rows={activity} /> : null}

      <section aria-label="Who spends" className="space-y-2">
        {isMonthView && summary.people_share != null && summary.people_total != null ? (
          <p className="text-sm text-muted-foreground">
            {formatPercent(summary.people_share)} of spend ({formatUsd(summary.people_total)}{" "}
            {currency}) counts under a person; the rest is service keys. Mark a key used by one
            person on its page to count it under them.
          </p>
        ) : null}
        {provider === "cursor" ? (
          <TopCard
            context={table}
            title="Top people"
            description="Cursor usage attributed directly to team members and service accounts."
            usage={personAccounts}
            dimension={ACCOUNT_DIMENSION}
          />
        ) : (
          <TopCard
            context={table}
            title="Top API keys"
            description="Spend attributed to each key: its token share of the workspace cost, or the provider's own per-key figure."
            usage={keys}
            dimension="api_key"
          />
        )}
      </section>

      <details className="rounded-md border border-border bg-background px-4 py-3 text-sm">
        <summary className="cursor-pointer font-medium text-secondary-foreground">
          More on this period
        </summary>
        <div className="mt-3 grid gap-4 lg:grid-cols-2">
          {provider === "cursor" ? null : (
            <TopCard
              context={table}
              title="Top accounts"
              description="People using the provider with their own login or Claude Code key."
              usage={personAccounts}
              dimension={ACCOUNT_DIMENSION}
              footer={
                accountsWithoutLogin
                  ? `${formatUsd(accountsWithoutLogin)} ${currency} without a person (service API keys)`
                  : undefined
              }
            />
          )}
          {movers ? (
            <MoversCard movers={movers} period={period} currency={currency} />
          ) : (
            <Card>
              <CardHeader>
                <CardHeading>What changed</CardHeading>
                <CardDescription>
                  Each key&apos;s spend against the previous period.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <CouldNotLoad what="the comparison with the previous period" />
              </CardContent>
            </Card>
          )}
          <AnomaliesCard
            anomalies={anomalies ? anomalies.anomalies : null}
            provider={provider}
            period={period}
            periodTotal={anomalies?.window_total ?? summary.total}
          />
          <OverviewBudgetsCard
            budgets={budgets}
            month={to.slice(0, 7)}
            currency={currency}
            showProvider={aggregated}
            isDemo={isDemo}
          />
          <OverviewModelsCard models={models} currency={currency} />
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          How it is computed: every figure on this page covers {displayRange}. The change compares
          with{" "}
          {isMonthView ? "the previous calendar month." : "the preceding range of equal length."}{" "}
          The daily average divides the total by the selected calendar days. Budgets are monthly and
          show {formatMonth(to.slice(0, 7))}; the month-end projection appears only while the time
          frame contains today.
        </p>
      </details>
    </div>
  );
}
