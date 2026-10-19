import type { FilterClause, UsageFilters } from "@/lib/api";

type QueryExport = {
  measure: string;
  dimensions?: string[];
  start: string;
  end: string;
  interval: string;
  compare?: string;
  top?: number;
  projection?: string;
  lookback?: number;
  horizon?: number;
  filters?: UsageFilters;
};

export function encodeFilterClause(dimension: string, clause: FilterClause): string {
  return `${dimension}:${clause.op}:${clause.values.join(",")}`;
}

export function appendUsageFilters(params: URLSearchParams, filters: UsageFilters): void {
  for (const [dimension, filter] of Object.entries(filters)) {
    if (!filter) continue;
    if (typeof filter === "string") {
      params.set(dimension, filter);
    } else {
      params.append("f", encodeFilterClause(dimension, filter));
    }
  }
}

export function queryCsvUrl(query: QueryExport): string {
  const params = new URLSearchParams({
    measure: query.measure,
    dimensions: (query.dimensions ?? []).join(","),
    start: query.start,
    end: query.end,
    interval: query.interval,
    compare: query.compare ?? "none",
  });
  if (query.top !== undefined) params.set("top", String(query.top));
  if (query.projection && query.projection !== "none") {
    params.set("projection", query.projection);
    if (query.lookback !== undefined) params.set("lookback", String(query.lookback));
    if (query.horizon !== undefined) params.set("horizon", String(query.horizon));
  }
  appendUsageFilters(params, query.filters ?? {});
  return `/api/exports/query?${params.toString()}`;
}
