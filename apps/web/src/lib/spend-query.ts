/**
 * The web side of the range query (`GET /orgs/{org}/query`): one builder for the request every
 * page sends, and the adapters that turn a `SpendQuery` into chart data and usage rows.
 */

import type {
  QueryCompare,
  QueryInterval,
  QueryMeasure,
  QueryProjectionMode,
  QueryRequest,
  QuerySeries,
  SpendQuery,
  Usage,
  UsageFilters,
  UsageRow,
} from "@/lib/api";
import { isAll, providerLabel } from "@/lib/providers";

type SpendQuerySpec = {
  /** The provider scope; `all` adds no provider filter. */
  provider: string;
  dimensions: string[];
  start: string;
  end: string;
  interval: QueryInterval;
  measure?: QueryMeasure;
  filters?: UsageFilters;
  top?: number;
  compare?: QueryCompare;
  projection?: QueryProjectionMode;
  lookback?: number;
  horizon?: number;
};

/** Filters narrowed to the provider scope. */
export function scopedFilters(provider: string, filters: UsageFilters = {}): UsageFilters {
  return isAll(provider) ? filters : { ...filters, provider };
}

/** The request for a spec: billed USD unless another measure is named. */
export function spendQuery({ provider, filters, measure, ...rest }: SpendQuerySpec): QueryRequest {
  return { measure: measure ?? "billed_usd", ...rest, filters: scopedFilters(provider, filters) };
}

export function valuesTotal(values: (string | number)[]): string {
  return values.reduce<number>((sum, value) => sum + Number(value), 0).toFixed(2);
}

export function queryTotal(query: SpendQuery): string {
  return valuesTotal(query.total);
}

/** Identity of a row across a usage report and a query: provider plus key (label if keyless). */
export function rowKey(provider: string | null, key: string | null, label: string): string {
  return `${provider ?? "scope"}:${key ?? label}`;
}

function seriesKey(series: QuerySeries, dimension: string): string {
  return rowKey(
    series.provider,
    series.keys[dimension] ?? null,
    series.labels[dimension] ?? "total",
  );
}

/** Chart buckets for the first `top` series; the rest fold into `other`. */
export function queryChartData(query: SpendQuery, dimension: string, top = Infinity) {
  const series = query.series.slice(0, top);
  const selected = new Set(series.map((item) => seriesKey(item, dimension)));
  const other = query.series
    .filter((item) => !selected.has(seriesKey(item, dimension)))
    .reduce<number[] | null>(
      (values, item) => {
        const next = values ?? query.buckets.map(() => 0);
        item.values.forEach((value, index) => {
          next[index]! += Number(value);
        });
        return next;
      },
      query.other ? query.other.map(Number) : null,
    );
  return {
    buckets: query.buckets,
    series: series.map((item) => ({
      key: item.keys[dimension] ?? null,
      label: chartLabel(item, dimension, series),
      provider: item.provider,
      values: item.values,
      total: item.total,
    })),
    other,
    total: query.total,
  };
}

/** The series label, with the provider appended when another charted series shares it: the
 * sentinel rows ("(api key request)") repeat once per provider under the aggregated scope. */
function chartLabel(item: QuerySeries, dimension: string, all: QuerySeries[]): string {
  const label = item.labels[dimension] ?? "total";
  const twins = all.filter((other) => (other.labels[dimension] ?? "total") === label);
  if (twins.length < 2 || !item.provider) return label;
  return `${label} ${providerLabel(item.provider)}`;
}

/** Billed rows of one query, enriched with the month report's details where a row matches. */
export function queryUsage(query: SpendQuery, dimension: string, metadata: Usage | null): Usage {
  const total = Number(queryTotal(query));
  const metadataRows = new Map(
    (metadata?.rows ?? []).map((row) => [rowKey(row.provider, row.key, row.label), row]),
  );
  const rows: UsageRow[] = query.series.map((item) => {
    const key = item.keys[dimension] ?? null;
    const label = item.labels[dimension] ?? "total";
    const known = metadataRows.get(rowKey(item.provider, key, label));
    const amount = Number(item.total);
    return {
      key,
      label,
      provider: item.provider,
      details: known?.details ?? {},
      amount: amount.toFixed(2),
      share: total > 0 ? ((amount / total) * 100).toFixed(2) : null,
      byok_amount: known?.byok_amount ?? null,
      tokens: known?.tokens ?? {},
      total_tokens: known?.total_tokens ?? 0,
      web_search_requests: known?.web_search_requests ?? 0,
      person: known?.person ?? (dimension === "person" ? key : null),
      provider_account_id: known?.provider_account_id ?? null,
      provider_account_label: known?.provider_account_label ?? null,
    };
  });
  return {
    dimension,
    allocated: query.source === "allocated",
    cost_total: total.toFixed(2),
    rows,
  };
}

/**
 * Rows for a range across every measure: money and tokens per row come from the matching
 * series of each measure's query, details from the month report. Rows follow billed spend,
 * or tokens when nothing is billed.
 */
export function rangeUsage(
  dimension: string,
  metadata: Usage,
  byMeasure: Map<QueryMeasure, SpendQuery>,
): Usage {
  const billed = byMeasure.get("billed_usd")!;
  const tokens = byMeasure.get("tokens_total")!;
  const base = billed.series.length > 0 ? billed.series : tokens.series;
  const metadataByKey = new Map(
    metadata.rows.map((row) => [rowKey(row.provider, row.key, row.label), row]),
  );
  const lookups = new Map<QueryMeasure, Map<string, number>>(
    [...byMeasure].map(([measure, query]) => [
      measure,
      new Map(query.series.map((series) => [seriesKey(series, dimension), Number(series.total)])),
    ]),
  );
  const total = billed.total.reduce<number>((sum, value) => sum + Number(value), 0);
  const rows: UsageRow[] = base.map((series) => {
    const key = series.keys[dimension] ?? null;
    const label = series.labels[dimension] ?? "total";
    const identity = seriesKey(series, dimension);
    const known = metadataByKey.get(rowKey(series.provider, key, label));
    const amount = lookups.get("billed_usd")?.get(identity);
    const byok = lookups.get("byok_usd")?.get(identity);
    const totalTokens = lookups.get("tokens_total")?.get(identity) ?? 0;
    return {
      key,
      label,
      provider: series.provider,
      provider_account_id: known?.provider_account_id ?? null,
      provider_account_label: known?.provider_account_label ?? null,
      details: known?.details ?? {},
      amount: amount === undefined ? null : amount.toFixed(2),
      share: amount === undefined || total <= 0 ? null : ((amount / total) * 100).toFixed(2),
      byok_amount: byok === undefined ? null : byok.toFixed(2),
      tokens: {
        uncached_input_tokens: lookups.get("tokens_input")?.get(identity) ?? 0,
        cache_creation_5m_tokens: lookups.get("tokens_cache_write")?.get(identity) ?? 0,
        cache_creation_1h_tokens: 0,
        cache_read_tokens: lookups.get("tokens_cache_read")?.get(identity) ?? 0,
        output_tokens: lookups.get("tokens_output")?.get(identity) ?? 0,
        reasoning_tokens: known?.tokens.reasoning_tokens ?? 0,
      },
      total_tokens: totalTokens,
      web_search_requests: lookups.get("requests_web_search")?.get(identity) ?? 0,
      person: dimension === "person" ? key : (known?.person ?? null),
    };
  });
  return {
    dimension,
    allocated: rows.some((row) => row.amount !== null),
    cost_total: total.toFixed(2),
    rows,
  };
}
