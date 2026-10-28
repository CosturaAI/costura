import {
  ApiError,
  api,
  type ActivityRow,
  type Anomaly,
  type AnomalySeriesKind,
  type ApiKey,
  type BudgetStatus,
  type DailySeries,
  type EntityLookup,
  type EntityLookupKind,
  type Person,
  type Projection,
  type Signal,
  type Snooze,
  type SeriesKind,
  type Usage,
  type UsageFilters,
  type UsageRow,
  type User,
  type Workspace,
} from "@/lib/api";
import { NEXT_DIMENSION, splitLabel } from "@/lib/dimensions";
import { ALL, isAll, PROVIDERS } from "@/lib/providers";
import type { EntityHint } from "@/lib/resource-search";
import { settledRecord, settledValue } from "@/lib/loaders";
import { spendQuery } from "@/lib/spend-query";
import { previousPeriod as periodBefore, wholeMonth, type DateRange } from "@/lib/time-range";

/** Dimensions with an entity page; `creator` rows land on the account page and `person` is
 * one e-mail across providers. */
export type EntityKind = "api_key" | "account" | "workspace" | "model" | "person";

export const ENTITY_KIND_LABELS: Record<EntityKind, string> = {
  api_key: "API key",
  account: "Account",
  workspace: "Workspace",
  model: "Model",
  person: "Person",
};

/** Additional breakdowns below an entity's primary chart and table. */
const SECONDARY_DIMENSIONS: Partial<Record<EntityKind, readonly string[]>> = {
  person: ["model", "api_key"],
  workspace: ["api_key"],
  model: ["api_key"],
};

/** Projection series exist for these kinds; accounts have none. */
const PROJECTION_KIND: Partial<Record<EntityKind, SeriesKind>> = {
  api_key: "api_key",
  workspace: "workspace",
  model: "model",
};

/** Anomaly series are the principals; workspaces and models appear only as root
 * causes, so their pages carry no anomaly section. */
const ANOMALY_KIND: Partial<Record<EntityKind, AnomalySeriesKind>> = {
  api_key: "api_key",
  account: "account",
};

export type EntityFacts =
  | { kind: "api_key"; item: ApiKey }
  | { kind: "account"; item: User }
  | { kind: "workspace"; item: Workspace }
  | { kind: "model"; item: null }
  | { kind: "person"; item: Person };

export type EntityData = {
  kind: EntityKind;
  id: string;
  /** The provider the id belongs to (`all` for a person under the aggregated scope). */
  provider: string;
  /** The provider account the id belongs to, once accounts exist; null before. */
  providerAccountId: number | null;
  /** Its label ("Acme"), from the inventory row or the period's usage; null when unknown. */
  providerAccountLabel: string | null;
  name: string;
  /** "name (id)" as the API labels it, for titles and tooltips. */
  label: string;
  facts: EntityFacts;
  period: DateRange;
  /** The period's row in the entity's own dimension, or null without usage. */
  current: UsageRow | null;
  /** Percent of the total spend of `provider` (every provider for a person under `all`) in
   * the period; null without allocation. */
  share: string | null;
  /** The provider scope a person page was asked under and has no account in; the page then
   * shows every provider. Null otherwise. */
  widenedFrom: string | null;
  previous: UsageRow | null;
  previousPeriod: DateRange;
  allocated: boolean;
  /** Dimension of the chart and table: the next natural question. */
  nextBy: string;
  series: DailySeries;
  breakdown: Usage;
  /** Further breakdowns of the same lines. */
  secondary: { by: string; usage: Usage }[];
  anomalies: Anomaly[] | null;
  keySignals: Signal[] | null;
  /** Gaps of this key a member snoozed; they are not in `keySignals`. */
  keySnoozes: Snooze[];
  keysConsoleUrl: string | null;
  projection: Projection | null;
  budget: BudgetStatus | null;
  canonicalModel: {
    brand: string;
    family: string;
    name: string;
    channel: string;
    lifecycle: string;
  } | null;
  /** OpenAI non-completions activity for provider project and key contexts. */
  activity: ActivityRow[] | null;
  /** True when a secondary call failed; the page says so once. */
  partial: boolean;
};

/** The lookup kind of each entity dimension; a person is one e-mail across providers and
 * needs none. */
const LOOKUP_KIND: Record<Exclude<EntityKind, "person">, EntityLookupKind> = {
  api_key: "key",
  account: "account",
  workspace: "workspace",
  model: "model",
};

/**
 * Which provider an entity page renders. The address names none: the API's lookup
 * route answers from the id, and the view's scope only breaks a tie (a model name under two
 * providers). Null when the organization has no such id. Under a concrete scope the lookup
 * is still made, so an id of another provider opens as itself instead of answering 404.
 */
async function resolveEntityProvider(
  kind: EntityKind,
  org: string,
  scope: string,
  id: string,
  account?: number,
): Promise<EntityLookup | null> {
  if (kind === "person") return { provider: scope, provider_account_id: null };
  try {
    return account === undefined
      ? await api.entityLookup(org, LOOKUP_KIND[kind], id, scope)
      : await api.entityLookup(org, LOOKUP_KIND[kind], id, scope, account);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/**
 * Everything an entity page shows, in one place so the five routes stay thin. Returns null
 * when the inventory has no row for the id (the route answers 404); models have no inventory
 * row and resolve as long as a cost line names them. Entities belong to one provider: the
 * page resolves it through `resolveEntityProvider` and renders under it whatever the view's
 * scope is. A person is the exception: the page lives under `all` (every provider) or under
 * one provider (that provider's account only).
 */
/** The account label the inventory row of `provider` carries; models and people have none. */
function accountLabelOf(facts: EntityFacts, provider: string): string | null {
  switch (facts.kind) {
    case "api_key":
    case "workspace":
      return facts.item?.provider === provider ? (facts.item.provider_account_label ?? null) : null;
    default:
      return null;
  }
}

export async function loadEntity(
  kind: EntityKind,
  org: string,
  scope: string,
  period: DateRange,
  id: string,
  hint: EntityHint = {},
): Promise<EntityData | null> {
  const data = await loadEntityUnder(kind, org, scope, period, id, hint);
  if (data !== null || kind !== "person" || isAll(scope)) return data;
  // A person with no account under the scope's provider still has a page across providers.
  const everywhere = await loadEntityUnder(kind, org, ALL, period, id, hint);
  return everywhere && { ...everywhere, widenedFrom: scope };
}

async function loadEntityUnder(
  kind: EntityKind,
  org: string,
  scope: string,
  period: DateRange,
  id: string,
  hint: EntityHint,
): Promise<EntityData | null> {
  const lookupScope = hint.provider && PROVIDERS.includes(hint.provider) ? hint.provider : scope;
  const resolved = await resolveEntityProvider(kind, org, lookupScope, id, hint.account);
  if (resolved === null) return null;
  const provider = resolved.provider;
  if (isAll(provider) && kind !== "person") return null;
  const account = resolved.provider_account_id;
  const filter: UsageFilters = { [NEXT_DIMENSION[kind]!.filter]: id };
  if (account !== null && (kind === "api_key" || kind === "account" || kind === "workspace")) {
    filter.provider_account = String(account);
  }
  let nextBy = NEXT_DIMENSION[kind]!.by;
  const month = period.to.slice(0, 7);
  const range = period;
  const anomalyKind = ANOMALY_KIND[kind];
  const projectionKind = PROJECTION_KIND[kind];
  const secondaryDimensions = SECONDARY_DIMENSIONS[kind] ?? [];

  const modelQuery = (dimensions: string[]) =>
    spendQuery({
      provider,
      dimensions,
      start: range.from,
      end: range.to,
      interval: "month",
      top: 1,
      filters: filter,
    });
  // Every read starts at once except, for a month in progress, the previous period: it takes
  // the days `summary` compares with. A filtered usage report sums only the filtered lines,
  // so the share needs the org total.
  const required = Promise.all([
    loadFacts(kind, org, provider, month, id, account),
    api.usage(org, provider, period, kind, 1, filter),
    api.series(org, provider, period, nextBy, 8, filter),
    api.usage(org, provider, period, nextBy, 25, filter),
    api.summary(org, provider, period),
    kind === "model"
      ? Promise.all([
          api.query(org, modelQuery(["model_brand", "model_family", "model_name"])),
          api.query(org, modelQuery(["model_channel", "model_lifecycle"])),
        ])
      : Promise.resolve(null),
  ]);
  const today = new Date().toISOString().slice(0, 10);
  const inProgress =
    wholeMonth(period.from, period.to) !== null && period.from <= today && today <= period.to;
  const comparedRead: Promise<DateRange> = inProgress
    ? required.then(
        ([, , , , monthSummary]) => ({
          from: monthSummary.previous_start,
          to: monthSummary.previous_end,
        }),
        () => periodBefore(period),
      )
    : Promise.resolve(periodBefore(period));
  const previousUsage: Promise<Usage> = comparedRead.then((compared) =>
    api.usage(org, provider, compared, kind, 1, filter),
  );
  const optionalReads = settledRecord({
    previous: previousUsage,
    anomalies: anomalyKind
      ? api.anomalies(org, provider, period, undefined, { kind: anomalyKind, id })
      : kind === "person"
        ? api.anomalies(org, provider, period, undefined, undefined, undefined, id)
        : Promise.resolve(null),
    projection: projectionKind
      ? api.projection(org, provider, month, projectionKind)
      : Promise.resolve(null),
    budgets:
      kind === "workspace" ? api.budgetStatuses(org, provider, month) : Promise.resolve(null),
    activity:
      provider === "openai" && (kind === "workspace" || kind === "api_key")
        ? api.activity(org, {
            since: range.from,
            until: range.to,
            provider_account: resolved.provider_account_id ?? undefined,
            ...(kind === "workspace" ? { workspace: id } : { api_key: id }),
          })
        : Promise.resolve(null),
    secondary: Promise.all(
      secondaryDimensions.map((by) => api.usage(org, provider, period, by, 25, filter)),
    ),
    // A person page falls back to keys when no row names a person; the series it would then
    // draw is requested now rather than after the breakdown arrives.
    keySeries:
      nextBy === "person"
        ? api.series(org, provider, period, "api_key", 8, filter)
        : Promise.resolve(null),
    signals: kind === "api_key" ? api.signals(org, provider) : Promise.resolve(null),
    providers: kind === "api_key" ? api.providers(org) : Promise.resolve(null),
  });
  let facts: EntityFacts;
  let ownRow, initialSeries, initialBreakdown, summary, canonicalQueries;
  try {
    [facts, ownRow, initialSeries, initialBreakdown, summary, canonicalQueries] = await required;
  } catch (error) {
    await optionalReads;
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
  const optional = await optionalReads;
  const comparedPeriod = await comparedRead;
  // The key series is a fallback the page may not draw; its failure is not a missing card.
  const settledRows = [
    optional.previous,
    optional.anomalies,
    optional.projection,
    optional.budgets,
    optional.activity,
    optional.secondary,
  ];

  const current = ownRow.rows[0] ?? null;
  const orgTotal = Number(summary.total);
  const share =
    current?.amount && ownRow.allocated && orgTotal > 0
      ? ((Number(current.amount) / orgTotal) * 100).toFixed(2)
      : null;
  const previous = settledValue(optional.previous)?.rows[0] ?? null;
  const anomalies = settledValue(optional.anomalies);
  const projections = settledValue(optional.projection);
  const budgets = settledValue(optional.budgets);
  const partial = settledRows.some((result) => result.status === "rejected");
  let series = initialSeries;
  let breakdown = initialBreakdown;
  const secondaryUsage = settledValue(optional.secondary) ?? [];
  let secondary = secondaryDimensions.flatMap((by, i) => {
    const usage = secondaryUsage[i];
    return usage ? [{ by, usage }] : [];
  });
  if (nextBy === "person" && !breakdown.rows.some((row) => row.person)) {
    const apiKeyBreakdown = secondary.find(({ by }) => by === "api_key");
    if (apiKeyBreakdown) {
      nextBy = "api_key";
      breakdown = apiKeyBreakdown.usage;
      series =
        settledValue(optional.keySeries) ??
        (await api.series(org, provider, period, "api_key", 8, filter));
      secondary = secondary.filter(({ by }) => by !== "api_key");
    }
  }

  const name = factsName(facts) ?? (current ? splitLabel(current.label).name : id);
  const identity = canonicalQueries?.[0].series[0]?.labels;
  const status = canonicalQueries?.[1].series[0]?.labels;
  return {
    kind,
    id,
    provider,
    providerAccountId: resolved.provider_account_id ?? null,
    providerAccountLabel:
      accountLabelOf(facts, provider) ??
      (current?.provider === provider ? (current.provider_account_label ?? null) : null),
    name,
    label: current?.label ?? (facts.item ? `${name} (${id})` : name),
    facts,
    current,
    share,
    widenedFrom: null,
    period,
    previous,
    previousPeriod: comparedPeriod,
    allocated: ownRow.allocated,
    nextBy,
    series,
    breakdown,
    secondary,
    anomalies: optional.anomalies.status === "rejected" ? null : (anomalies?.anomalies ?? []),
    keySignals:
      settledValue(optional.signals)?.items.filter(
        (signal) =>
          signal.entity_kind === "api_key" &&
          signal.entity_id === id &&
          signal.kind !== "anomaly" &&
          signal.kind !== "budget",
      ) ?? null,
    keySnoozes:
      settledValue(optional.signals)?.snoozed?.filter(
        (snooze) => snooze.key_id === id && snooze.provider === provider,
      ) ?? [],
    keysConsoleUrl:
      settledValue(optional.providers)?.find((info) => info.provider === provider)
        ?.keys_console_url ?? null,
    projection: summary.is_current_month
      ? (projections?.projections.find((p) => p.series_id === id) ?? null)
      : null,
    budget: budgets?.statuses.find((s) => s.budget.scope_id === id) ?? null,
    canonicalModel:
      identity && status
        ? {
            brand: identity.model_brand ?? "Unknown",
            family: identity.model_family ?? "Unknown",
            name: identity.model_name ?? "Unknown",
            channel: status.model_channel ?? "Unknown",
            lifecycle: status.model_lifecycle ?? "Unknown",
          }
        : null,
    activity: settledValue(optional.activity),
    partial,
  };
}

async function loadFacts(
  kind: EntityKind,
  org: string,
  provider: string,
  month: string,
  id: string,
  account: number | null,
): Promise<EntityFacts> {
  switch (kind) {
    case "api_key":
      return {
        kind,
        item:
          account === null
            ? await api.apiKey(org, provider, id)
            : await api.apiKey(org, provider, id, account),
      };
    case "account":
      return {
        kind,
        item:
          account === null
            ? await api.user(org, provider, id)
            : await api.user(org, provider, id, account),
      };
    case "workspace":
      return {
        kind,
        item:
          account === null
            ? await api.workspace(org, provider, id)
            : await api.workspace(org, provider, id, account),
      };
    case "model":
      return { kind, item: null };
    case "person":
      return { kind, item: await api.person(org, provider, month, id) };
  }
}

function factsName(facts: EntityFacts): string | null {
  switch (facts.kind) {
    case "api_key":
      return facts.item.name;
    case "account":
      return facts.item.email;
    case "workspace":
      return facts.item.name;
    case "model":
      return null;
    case "person":
      return facts.item.email;
  }
}
