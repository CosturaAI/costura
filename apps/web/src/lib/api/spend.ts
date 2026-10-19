/**
 * Spend reads: months, summary, usage, series, movers, activity, the range
 * query, projections and reconciliation.
 */

import type { SeriesKind } from "./anomalies";
import type { Schema } from "./schema";
import { get, periodPath, periodQuery, scope, withFilters, type Period } from "./transport";

export type UsageRow = Schema<"UsageRowOut">;

export type Usage = Schema<"UsageOut">;

export type ActivityRow = Schema<"ActivityRowOut">;

type ActivityFilters = {
  since: string;
  until: string;
  family?: string;
  provider_account?: number;
  workspace?: string;
  api_key?: string;
};

export type MoverRow = Schema<"MoverRowOut">;

export type Movers = Schema<"MoversOut">;

export type Reconcile = Schema<"ReconcileOut">;

export type DailySeries = Schema<"DailySeriesOut">;

export type QueryMeasure =
  | "billed_usd"
  | "byok_usd"
  | "tokens_total"
  | "tokens_input"
  | "tokens_output"
  | "tokens_cache_read"
  | "tokens_cache_write"
  | "requests_web_search"
  | "requests";

export type QueryInterval = "day" | "week" | "month";

export type QueryCompare = "none" | "previous_period" | "previous_year";

export type QueryValue = string | number;

/** URL presets the Explore page understands. Saved views are not an API resource. */
export type ExploreTimeFrame =
  "this_month" | "last_month" | "last_7_days" | "last_30_days" | "last_90_days" | "quarter" | "ytd";

export type ExploreDisplay = "total" | "delta" | "daily_average" | "daily_average_x30";

export type QuerySeries = Schema<"QuerySeriesOut">;

type QueryComparison = Schema<"QueryComparisonOut">;

export type QueryProjection = Schema<"QueryProjectionOut">;

export type SpendQuery = {
  measure: QueryMeasure;
  dimensions: string[];
  start: string;
  end: string;
  interval: QueryInterval;
  source: "allocated" | "cost" | "usage";
  buckets: string[];
  series: QuerySeries[];
  other: QueryValue[] | null;
  total: QueryValue[];
  comparison: QueryComparison | null;
  projection: QueryProjection | null;
};

export type QueryProjectionMode = "none" | "linear";

export type QueryRequest = {
  measure: QueryMeasure;
  dimensions?: string[];
  start: string;
  end: string;
  interval: QueryInterval;
  top?: number;
  compare?: QueryCompare;
  projection?: QueryProjectionMode;
  lookback?: number;
  horizon?: number;
  filters?: UsageFilters;
};

/** Same bounds as `QueryRequest`, for `GET /orgs/{org}/queries`. Projection applies to billed USD. */
type QueriesRequest = Omit<QueryRequest, "measure"> & {
  measures: QueryMeasure[];
};

type SpendQueries = { results: SpendQuery[] };

export type Summary = Schema<"SummaryOut">;

export type Projection = Schema<"ProjectionOut">;

export type Projections = Schema<"ProjectionsOut">;

export type FilterOperator =
  "is" | "is_not" | "one_of" | "not_one_of" | "contains" | "not_contains" | "exists" | "not_exists";

export type FilterClause = {
  op: FilterOperator;
  values: string[];
};

type UsageFilterValue = string | FilterClause;

/** Drill-down filters shared by `usage`, `series` and the range query. */
export type UsageFilters = {
  api_key?: UsageFilterValue;
  account?: UsageFilterValue;
  creator?: UsageFilterValue;
  workspace?: UsageFilterValue;
  model?: UsageFilterValue;
  provider?: UsageFilterValue;
  origin?: UsageFilterValue;
  /** One e-mail across providers: the lines of every account carrying it. */
  person?: UsageFilterValue;
  /** One provider account (its id): the lines synced from that console. */
  provider_account?: UsageFilterValue;
  model_brand?: UsageFilterValue;
  model_family?: UsageFilterValue;
  model_name?: UsageFilterValue;
  model_channel?: UsageFilterValue;
  model_lifecycle?: UsageFilterValue;
  token_type?: UsageFilterValue;
} & Record<`tag:${string}`, UsageFilterValue | undefined>;

export const USAGE_DIMENSIONS = [
  "api_key",
  "account",
  "creator",
  "workspace",
  "model",
  "provider",
  "origin",
  "provider_account",
  "person",
  "team",
  "model_brand",
  "model_family",
  "model_name",
  "model_channel",
  "model_lifecycle",
  "token_type",
] as const;

export const BREAKDOWN_DIMENSIONS = [
  "day",
  "workspace",
  "model",
  "token_type",
  "cost_type",
  "service_tier",
  "description",
] as const;

export const spendApi = {
  months: (org: string, provider: string) =>
    get<{ months: string[] }>(`${scope(org, provider)}/months`),
  query: (org: string, query: QueryRequest) =>
    get<SpendQuery>(
      `/orgs/${encodeURIComponent(org)}/query`,
      withFilters(
        {
          measure: query.measure,
          dimensions: (query.dimensions ?? []).join(","),
          start: query.start,
          end: query.end,
          interval: query.interval,
          top: query.top,
          compare: query.compare,
          projection: query.projection,
          lookback: query.lookback,
          horizon: query.horizon,
        },
        query.filters,
      ),
    ),
  queries: (org: string, query: QueriesRequest) =>
    get<SpendQueries>(
      `/orgs/${encodeURIComponent(org)}/queries`,
      withFilters(
        {
          measures: query.measures.join(","),
          dimensions: (query.dimensions ?? []).join(","),
          start: query.start,
          end: query.end,
          interval: query.interval,
          top: query.top,
          compare: query.compare,
          projection: query.projection,
          lookback: query.lookback,
          horizon: query.horizon,
        },
        query.filters,
      ),
    ),
  summary: (org: string, provider: string, period: Period) =>
    get<Summary>(
      `${scope(org, provider)}/months/${periodPath(period)}/summary`,
      periodQuery(period),
    ),
  series: (
    org: string,
    provider: string,
    period: Period,
    by: string,
    top?: number,
    filters: UsageFilters = {},
  ) =>
    get<DailySeries>(
      `${scope(org, provider)}/months/${periodPath(period)}/series`,
      withFilters({ by, top, ...periodQuery(period) }, filters),
    ),
  usage: (
    org: string,
    provider: string,
    period: Period,
    by: string,
    top?: number,
    filters: UsageFilters = {},
  ) =>
    get<Usage>(
      `${scope(org, provider)}/months/${periodPath(period)}/usage`,
      withFilters({ by, top, ...periodQuery(period) }, filters),
    ),
  activity: (org: string, filters: ActivityFilters) =>
    get<ActivityRow[]>(`/orgs/${encodeURIComponent(org)}/activity`, { ...filters }),
  movers: (org: string, provider: string, period: Period, by: string, top?: number) =>
    get<Movers>(`${scope(org, provider)}/months/${periodPath(period)}/movers`, {
      by,
      top,
      ...periodQuery(period),
    }),
  reconcile: (org: string, provider: string, period: Period, by: string, account?: number) =>
    get<Reconcile>(`${scope(org, provider)}/months/${periodPath(period)}/reconcile`, {
      by,
      account,
      ...periodQuery(period),
    }),
  projection: (org: string, provider: string, month: string, by: SeriesKind = "org") =>
    get<Projections>(`${scope(org, provider)}/months/${month}/projection`, { by }),
};
