import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { AttributionTable } from "@/components/attribution-table";
import { CardHeading } from "@/components/card-heading";
import { BucketedSpendChart } from "@/components/charts/daily-spend-chart";
import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { FilterChips, QueryChips } from "@/components/query-chips";
import { QuerySelect } from "@/components/query-select";
import { TransposedSpendTable } from "@/components/transposed-spend-table";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import {
  USAGE_DIMENSIONS,
  type ExploreDisplay,
  type QueryProjectionMode,
  type UsageRow,
} from "@/lib/api";
import { BYOK_NOTE, hasByok } from "@/lib/byok";
import { DIMENSION_LABELS, splitLabel } from "@/lib/dimensions";
import { formatUsd } from "@/lib/format";
import { RANGE_MEASURES, loadExplore } from "@/lib/explore";
import { displayLabel, exploreHref } from "@/lib/explore-state";
import { applyExploreDisplay } from "@/lib/explore-display";
import { isAll } from "@/lib/providers";
import { queryCsvUrl } from "@/lib/query-export";
import { filtersFrom, first, oneOf, positiveInt, type Search } from "@/lib/search";
import { syncAction } from "@/lib/setup";
import { queryChartData } from "@/lib/spend-query";
import { rangeLabel } from "@/lib/time-range";

import { requireView, type View } from "@/lib/view";

import { openOrgHref } from "@/lib/setup";
import { Disclosure } from "@/components/disclosure";
import { FilterEditor, type FilterValueOption } from "./filter-editor";
import { CopyExploreLink } from "./views-menu";
import { ViewOptions } from "./view-options";

export const metadata: Metadata = { title: "Analyze" };

/** Under one provider the provider grouping has a single row, so the chip stays hidden. */
const SINGLE_PROVIDER_DIMENSIONS = USAGE_DIMENSIONS.filter((d) => d !== "provider");

/**
 * Groupings that fit the view: the provider one needs the aggregated scope; the provider
 * account one needs a second account somewhere in scope, otherwise it repeats the provider
 * row. The `by` query accepts either, so a shared link opens that grouping.
 */
function visibleDimensions(aggregated: boolean, accountCount: number): readonly string[] {
  const base = aggregated ? USAGE_DIMENSIONS : SINGLE_PROVIDER_DIMENSIONS;
  return accountCount > 1 ? base : base.filter((d) => d !== "provider_account");
}

/** The groupings a first query needs. A shared link for any other grouping selects it. */
const PRIMARY_DIMENSIONS = new Set([
  "api_key",
  "account",
  "workspace",
  "model",
  "person",
  "team",
  "provider",
  "provider_account",
]);
const TOP_OPTIONS = [
  { value: "10", label: "Top 10" },
  { value: "25", label: "Top 25" },
  { value: "50", label: "Top 50" },
  { value: "100", label: "Top 100" },
  { value: "200", label: "Top 200" },
] as const;
const CHART_TOP = 8;
const DISPLAYS: ExploreDisplay[] = ["total", "delta", "daily_average", "daily_average_x30"];
const AXES = ["time", "dimension"] as const;
const PROJECTIONS: QueryProjectionMode[] = ["none", "linear"];
const RANGE_KEYS = new Set(["from", "to", "time_frame", "period"]);

/**
 * A link that carries dates (`?from=&to=`) becomes the view through `/o/{org}`, which writes
 * the cookie and comes back without them, so the header picker and the page read one range.
 */
function adoptRangeHref(view: View, query: Search): string {
  const rest = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (RANGE_KEYS.has(key) || value === undefined) continue;
    for (const item of Array.isArray(value) ? value : [value]) rest.append(key, item);
  }
  const params = new URLSearchParams({
    scope: view.provider,
    from: view.from,
    to: view.to,
    next: rest.size > 0 ? `/explore?${rest}` : "/explore",
  });
  if (view.timeFrame) params.set("time_frame", view.timeFrame);
  return `/o/${encodeURIComponent(view.org)}?${params}`;
}

export default async function ExplorePage({ searchParams }: { searchParams: Promise<Search> }) {
  const query = await searchParams;
  const base = await requireView(query);
  const { org, provider } = base;
  const stored = await requireView();
  if (base.from !== stored.from || base.to !== stored.to) redirect(adoptRangeHref(base, query));
  const selected = query;
  const selectedRange = base;
  const { from, to, interval } = selectedRange;
  const aggregated = isAll(provider);
  const dimensions = aggregated ? USAGE_DIMENSIONS : SINGLE_PROVIDER_DIMENSIONS;
  const by = oneOf(first(selected.by), dimensions, "api_key");
  const topParam = first(selected.top) ?? "25";
  const top = topParam === "all" ? 200 : (positiveInt(topParam, 200) ?? 25);
  const topValue = String(top);
  const topOptions: readonly { value: string; label: string }[] = TOP_OPTIONS.some(
    (option) => option.value === topValue,
  )
    ? TOP_OPTIONS
    : [...TOP_OPTIONS, { value: topValue, label: `Top ${topValue}` }];
  const filters = filtersFrom(selected);
  // The table does not render a previous-period or previous-year column, so the query does not
  // ask for one. Display modes that the chart and table do render stay in the URL.
  const compare = "none";
  const display = oneOf(first(selected.display), DISPLAYS, "total");
  const axis = oneOf(first(selected.axis), AXES, "time");
  const projection = oneOf(first(selected.projection), PROJECTIONS, "none");
  const requestedLookback = positiveInt(first(selected.lookback), 90);
  const lookback = requestedLookback && requestedLookback >= 2 ? requestedLookback : 8;
  const horizon = positiveInt(first(selected.horizon), 31) ?? 4;
  const measures = RANGE_MEASURES;
  const measure = oneOf(first(selected.measure), measures, "billed_usd");

  const { querySpec, metadata, byMeasure, billed, usage, chips, providers } = await loadExplore({
    org,
    provider,
    by,
    top,
    filters,
    start: from,
    end: to,
    interval,
    compare,
    projection,
    lookback,
    horizon,
  });
  const displayedMeasure = applyExploreDisplay(byMeasure.get(measure) ?? billed, display);
  const accountCount = providers
    .filter((p) => aggregated || p.provider === provider)
    .reduce((n, p) => n + p.accounts.length, 0);
  const chipDimensions = new Set(
    [...visibleDimensions(aggregated, accountCount)].filter((dimension) =>
      PRIMARY_DIMENSIONS.has(dimension),
    ),
  );
  chipDimensions.add(by);
  const currency = "USD";
  const exportHref = queryCsvUrl({
    measure,
    ...querySpec,
    top,
    projection,
    lookback,
    horizon,
  });
  const range = rangeLabel(from, to);
  const dimensionLabels: Record<string, string> = { ...DIMENSION_LABELS };
  const groupOptions = dimensions.map((value) => ({
    value,
    label: dimensionLabels[value] ?? value,
  }));
  const valueOptions: Record<string, FilterValueOption[]> = {
    [by]: metadata.rows
      .filter((row): row is UsageRow & { key: string } => row.key !== null)
      .map((row) => ({ value: row.key, label: splitLabel(row.label).name })),
    provider: providers.map((item) => ({ value: item.provider, label: item.label })),
  };
  const shareHref = exploreHref({
    measure,
    dimension: by,
    top,
    filters,
    start: from,
    end: to,
    interval,
    compare,
    display,
    axis,
    projection,
    lookback,
    horizon,
    rangePreset: base.timeFrame,
  });

  return (
    <div className="space-y-4">
      <PageHeader
        title={`Spend by ${dimensionLabels[by]?.toLowerCase() ?? by}, ${range}`}
        description={
          usage.allocated ? (
            <>
              <span className="font-mono text-secondary-foreground">
                {formatUsd(usage.cost_total)}
              </span>{" "}
              {currency} across {usage.rows.length} row{usage.rows.length === 1 ? "" : "s"}
              {chips.length > 0 ? " matching the filters" : ""}. Click a name for its page; sort by
              clicking a column.
            </>
          ) : (
            <>
              {chips.length > 0
                ? measure.endsWith("_usd")
                  ? "No spend matches these filters."
                  : "No usage matches these filters; dollars per row arrive with attribution on the next import."
                : "Nothing is attributed to rows in this range yet; dollars per row arrive with attribution on the next import."}
            </>
          )
        }
      >
        <CopyExploreLink
          href={
            base.organization.is_demo
              ? openOrgHref(base.org, shareHref, { scope: base.provider })
              : shareHref
          }
        />
        <Button asChild variant="outline" size="lg">
          <a href={exportHref} download>
            Export CSV
          </a>
        </Button>
      </PageHeader>

      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <div className="hidden md:block">
          <QueryChips
            name="by"
            value={by}
            options={groupOptions.filter((o) => chipDimensions.has(o.value))}
            label="Group by"
            size="sm"
          />
        </div>
        <div className="md:hidden">
          <QuerySelect
            name="by"
            value={by}
            options={groupOptions.filter((o) => chipDimensions.has(o.value))}
            label="Group by"
          />
        </div>
        <FilterChips filters={chips} labels={dimensionLabels} />
      </div>

      <ViewOptions
        top={top}
        topOptions={topOptions}
        display={display}
        axis={axis}
        projection={projection}
        lookback={lookback}
        horizon={horizon}
      />

      <Disclosure title="Add filter" open={chips.length > 0}>
        <FilterEditor dimensions={groupOptions} defaultDimension={by} valueOptions={valueOptions} />
      </Disclosure>

      {usage.rows.length === 0 ? (
        <EmptyState
          message={
            chips.length > 0 ? "No spend matches these filters." : `No usage stored for ${range}.`
          }
          action={chips.length > 0 ? undefined : syncAction()}
        />
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardHeading>{measure.includes("usd") ? "Spend" : "Usage"} over time</CardHeading>
              <CardDescription>
                Top {CHART_TOP} by {dimensionLabels[by]?.toLowerCase() ?? by}, grouped{" "}
                {interval === "day" ? "daily" : interval === "week" ? "weekly" : "monthly"}
                {axis === "dimension" ? ", aggregated with dimension on the x-axis" : ""}.
                {axis === "dimension" && projection === "linear"
                  ? " Switch to the time x-axis to see the projection."
                  : ""}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <BucketedSpendChart
                data={queryChartData(displayedMeasure, by, CHART_TOP)}
                interval={interval}
                currency={measure === "billed_usd" ? currency : undefined}
                height={240}
                future={displayedMeasure.projection}
                axis={axis}
                allowCumulative={false}
                valueLabel={displayLabel(display, interval)}
              />
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-0">
              {axis === "dimension" ? (
                <TransposedSpendTable
                  data={queryChartData(displayedMeasure, by, top)}
                  currency={measure === "billed_usd" ? currency : undefined}
                  caption={`${displayLabel(display, interval)} by ${dimensionLabels[by]?.toLowerCase() ?? by}, bucket columns, ${range}`}
                />
              ) : (
                <AttributionTable
                  rows={usage.rows}
                  dimension={by}
                  allocated={usage.allocated}
                  currency={currency}
                  showProvider={aggregated}
                  caption={`Spend by ${dimensionLabels[by]?.toLowerCase() ?? by}, ${range}`}
                />
              )}
            </CardContent>
          </Card>
          {hasByok(usage.rows) ? (
            <p className="text-xs text-muted-foreground">BYOK: {BYOK_NOTE}</p>
          ) : null}
        </>
      )}
    </div>
  );
}
