/**
 * Data behind the Explore page: one batched range query for every measure, the usage report
 * over the same days that labels the rows, the readable filter chips and the provider list.
 */

import {
  api,
  type FilterClause,
  type QueryCompare,
  type QueryInterval,
  type QueryMeasure,
  type Period,
  type QueryProjectionMode,
  type UsageFilters,
} from "@/lib/api";
import { splitLabel } from "@/lib/dimensions";
import { rangeUsage, scopedFilters } from "@/lib/spend-query";

export const RANGE_MEASURES: QueryMeasure[] = [
  "billed_usd",
  "byok_usd",
  "tokens_total",
  "tokens_input",
  "tokens_output",
  "tokens_cache_read",
  "tokens_cache_write",
  "requests",
  "requests_web_search",
];

type ExploreRequest = {
  org: string;
  provider: string;
  by: string;
  top: number;
  filters: UsageFilters;
  start: string;
  end: string;
  interval: QueryInterval;
  compare: QueryCompare;
  projection: QueryProjectionMode;
  lookback: number;
  horizon: number;
};

/** Human label for each active filter: the matching row's label in its own dimension. */
export async function filterLabels(
  org: string,
  provider: string,
  period: Period,
  filters: UsageFilters,
): Promise<{ name: string; clause: FilterClause; label: string }[]> {
  const entries = Object.entries(filters)
    .filter((entry): entry is [string, NonNullable<(typeof entry)[1]>] => Boolean(entry[1]))
    .map(([name, value]) => ({
      name,
      clause: typeof value === "string" ? ({ op: "is", values: [value] } as FilterClause) : value,
    }));
  const labels = await Promise.all(
    entries.map(async (entry) => {
      if (entry.clause.values.length === 0) return "";
      if (entry.clause.op === "contains" || entry.clause.op === "not_contains") {
        return entry.clause.values.join(", ");
      }
      // One report per dimension: the rows of every value at once, matched back by key.
      const values = entry.clause.values;
      const report = await api.usage(org, provider, period, entry.name, values.length, {
        [entry.name]:
          values.length === 1 ? values[0] : ({ op: "one_of", values } satisfies FilterClause),
      } as UsageFilters);
      const byKey = new Map(report.rows.map((row) => [row.key, row.label]));
      return values
        .map((value) => {
          const label =
            byKey.get(value) ?? (values.length === 1 ? report.rows[0]?.label : undefined);
          return splitLabel(label ?? value).name;
        })
        .join(", ");
    }),
  );
  return entries.map((entry, i) => ({ ...entry, label: labels[i] ?? entry.name }));
}

/** The query every measure shares; only billed USD carries the projection. */
function exploreQuerySpec(request: ExploreRequest) {
  return {
    dimensions: [request.by],
    start: request.start,
    end: request.end,
    interval: request.interval,
    top: request.top,
    compare: request.compare,
    filters: scopedFilters(request.provider, request.filters),
  };
}

export async function loadExplore(request: ExploreRequest) {
  const { org, provider, by, top, filters, projection, lookback, horizon } = request;
  const querySpec = exploreQuerySpec(request);
  const period = { from: request.start, to: request.end };
  const [metadata, batch, chips, providers] = await Promise.all([
    api.usage(org, provider, period, by, top, filters),
    api.queries(org, {
      measures: RANGE_MEASURES,
      ...querySpec,
      projection,
      ...(projection === "linear" ? { lookback, horizon } : {}),
    }),
    filterLabels(org, provider, period, filters),
    api.providers(org),
  ]);
  const byMeasure = new Map(batch.results.map((result) => [result.measure, result]));
  return {
    querySpec,
    metadata,
    byMeasure,
    billed: byMeasure.get("billed_usd")!,
    usage: rangeUsage(by, metadata, byMeasure),
    chips,
    providers,
  };
}
