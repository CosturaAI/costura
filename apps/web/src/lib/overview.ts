/**
 * Secondary data of the Overview page. Each call is settled on its own: a failed one leaves its
 * card with a note instead of failing the page.
 */

import type { SignalItem } from "@/lib/ui-types";
import {
  api,
  type BudgetStatus,
  type Projection,
  type QueryInterval,
  type Summary,
} from "@/lib/api";
import { formatDayShort, formatPercent, formatRelative, formatUsd } from "@/lib/format";
import { settledRecord, settledValue } from "@/lib/loaders";
import { isAll } from "@/lib/providers";
import { queryUsage, spendQuery } from "@/lib/spend-query";

const TABLE_TOP = 8;
export const MODELS_TOP = 6;
/** A person is one row in every scope; service API keys remain outside personal spend. */
export const ACCOUNT_DIMENSION = "person";

export type OverviewView = {
  org: string;
  provider: string;
  from: string;
  to: string;
  interval: QueryInterval;
};

/** Billed spend by one dimension over the view's range, with the previous period beside it. */
export function overviewQuery(view: OverviewView, dimension: string, top?: number) {
  return api.query(
    view.org,
    spendQuery({
      provider: view.provider,
      dimensions: [dimension],
      start: view.from,
      end: view.to,
      interval: view.interval,
      top,
      compare: "previous_period",
    }),
  );
}

export async function loadOverviewDetails(view: OverviewView) {
  const { org, provider, from, to } = view;
  const period = { from, to };
  const endMonth = to.slice(0, 7);
  const aggregated = isAll(provider);
  const reads = await settledRecord({
    keysMetadata: api.usage(org, provider, period, "api_key", TABLE_TOP),
    accountsMetadata: api.usage(org, provider, period, ACCOUNT_DIMENSION, TABLE_TOP),
    modelsMetadata: api.usage(org, provider, period, "model"),
    keysQuery: overviewQuery(view, "api_key", TABLE_TOP),
    accountsQuery: overviewQuery(view, ACCOUNT_DIMENSION, TABLE_TOP),
    modelsQuery: overviewQuery(view, "model", MODELS_TOP),
    movers: api.movers(org, provider, period, provider === "cursor" ? "person" : "api_key"),
    projections: api.projection(org, provider, endMonth, "org"),
    // Severity first: the card and the KPI both lead with the episode worth reading.
    anomalies: api.anomalies(org, provider, period, "open", undefined, "severity"),
    budgets: api.budgetStatuses(org, provider, endMonth),
    providersMetadata: aggregated
      ? api.usage(org, provider, period, "provider")
      : Promise.resolve(null),
    providersQuery: aggregated ? overviewQuery(view, "provider") : Promise.resolve(null),
    setup: api.setup(org),
    organization: api.org(org),
    signals: api.signals(org, provider),
  });
  const keysQuery = settledValue(reads.keysQuery);
  const accountsQuery = settledValue(reads.accountsQuery);
  const modelsQuery = settledValue(reads.modelsQuery);
  const providersQuery = settledValue(reads.providersQuery);
  const accounts = accountsQuery
    ? queryUsage(accountsQuery, ACCOUNT_DIMENSION, settledValue(reads.accountsMetadata))
    : null;
  return {
    keys: keysQuery ? queryUsage(keysQuery, "api_key", settledValue(reads.keysMetadata)) : null,
    accountsWithoutLogin: accounts?.rows
      .filter((row) => row.key === null)
      .reduce((total, row) => total + Number(row.amount ?? 0), 0),
    personAccounts: accounts
      ? { ...accounts, rows: accounts.rows.filter((row) => row.key !== null) }
      : null,
    models: modelsQuery
      ? queryUsage(modelsQuery, "model", settledValue(reads.modelsMetadata))
      : null,
    movers: settledValue(reads.movers),
    byProvider: providersQuery
      ? queryUsage(providersQuery, "provider", settledValue(reads.providersMetadata))
      : null,
    projections: settledValue(reads.projections),
    anomalies: settledValue(reads.anomalies),
    budgets: settledValue(reads.budgets),
    setup: settledValue(reads.setup),
    organization: settledValue(reads.organization),
    signals: settledValue(reads.signals),
  };
}

type OverviewDetails = Awaited<ReturnType<typeof loadOverviewDetails>>;

/** The period in one strip: the budget it strains and the last import whose totals were
 * checked against each provider. What to investigate is the Needs a person queue. */
export function overviewSignals(
  details: OverviewDetails,
  provider: string,
  orgBudget: BudgetStatus | null,
): SignalItem[] {
  const signals: SignalItem[] = [];
  if (orgBudget) {
    signals.push({
      label: "Organization budget",
      value: formatPercent(orgBudget.percent),
      meta: orgBudget.projected_percent
        ? `projected ${formatPercent(orgBudget.projected_percent)}`
        : undefined,
      href: "/budgets",
      linkLabel: "View budgets",
    });
  }
  // Newest finished scheduler run over the providers in scope; `setup` already carries one
  // run per provider, so the row costs no extra call.
  const lastImport = (details.setup?.runs ?? [])
    .filter((run) => (isAll(provider) || run.provider === provider) && run.finished_at !== null)
    .map((run) => ({ at: run.finished_at as string, status: run.status }))
    .sort((a, b) => b.at.localeCompare(a.at))[0];
  if (lastImport) {
    signals.push({
      label: "Last import",
      value: lastImport.status,
      meta: formatRelative(lastImport.at),
      href: "/reconcile",
      linkLabel: "Check the totals",
    });
  }
  return signals;
}

/**
 * "Data through Oct 12." when the cost syncs stop before yesterday, plus "The last import
 * failed." when a later sync failed; null when the figures are current.
 */
export function coverageNote(
  summary: Pick<Summary, "complete_through" | "data_stale"> &
    Partial<Pick<Summary, "detection_through" | "duplicate_accounts">>,
  today: Date = new Date(),
): string | null {
  const yesterday = new Date(today.getTime() - 86_400_000).toISOString().slice(0, 10);
  const through = summary.complete_through ?? null;
  const parts: string[] = [];
  if (through !== null && through < yesterday)
    parts.push(`Data through ${formatDayShort(through)}.`);
  if (summary.data_stale) parts.push("The last import failed.");
  const checked = summary.detection_through ?? null;
  if (through !== null && checked !== null && checked < through) {
    parts.push(`Anomalies checked through ${formatDayShort(checked)}.`);
  }
  for (const pair of summary.duplicate_accounts ?? []) {
    parts.push(`${pair} report the same organization; their spend may be counted twice.`);
  }
  return parts.length > 0 ? parts.join(" ") : null;
}

/**
 * The last complete day when a free range runs past it (a range ending today, or after a sync
 * gap), else null. The previous range is complete, so a drop there is not savings.
 */
export function rangeRunsPast(
  to: string,
  summary: Pick<Summary, "complete_through">,
  today: Date = new Date(),
): string | null {
  const yesterday = new Date(today.getTime() - 86_400_000).toISOString().slice(0, 10);
  const through = summary.complete_through ?? yesterday;
  return to > through ? through : null;
}

/** A change measured over part of a period: never shown as good news. */
export function partialCoverage(summary: Pick<Summary, "comparison_basis">): boolean {
  return summary.comparison_basis === "month_to_date";
}

/** The Total KPI's line on whether Costura's total matches the provider's own report. */
export function providerVerdict(
  summary: Pick<Summary, "provider_total" | "provider_matches" | "provider_difference">,
): { text: string; tone: "success" | "critical" | "neutral" } {
  if (summary.provider_total === null || summary.provider_matches === null) {
    return { text: "provider check pending", tone: "neutral" };
  }
  if (summary.provider_matches) return { text: "matches provider", tone: "success" };
  return {
    text: `differs from provider by ${formatUsd(String(Math.abs(Number(summary.provider_difference ?? "0"))))}`,
    tone: "critical",
  };
}

export type ScopeProjection = Pick<
  Projection,
  "projected_total" | "low" | "high" | "as_of_day" | "currency" | "days"
>;

/**
 * The month-end projection of the whole scope: the API stores one org row per provider
 * account, so the scope's figure is their sum (bands summed too) as of the earliest row.
 */
export function scopeProjection(rows: readonly Projection[]): ScopeProjection | null {
  if (rows.length === 0) return null;
  const sum = (pick: (row: Projection) => string) =>
    rows.reduce((total, row) => total + Number(pick(row)), 0).toFixed(2);
  return {
    projected_total: sum((row) => row.projected_total),
    low: sum((row) => row.low),
    high: sum((row) => row.high),
    as_of_day: rows.map((row) => row.as_of_day).sort()[0]!,
    currency: rows[0]!.currency,
    days: projectedDays(rows),
  };
}

/** Projected days of every row added up per day, in day order. */
function projectedDays(rows: readonly Projection[]): Projection["days"] {
  const byDay = new Map<string, Projection["days"][number]>();
  for (const row of rows) {
    for (const day of row.days) {
      const seen = byDay.get(day.day);
      byDay.set(
        day.day,
        seen
          ? {
              day: day.day,
              expected: (Number(seen.expected) + Number(day.expected)).toFixed(2),
              low: (Number(seen.low) + Number(day.low)).toFixed(2),
              high: (Number(seen.high) + Number(day.high)).toFixed(2),
              samples: Math.min(seen.samples, day.samples),
            }
          : { ...day },
      );
    }
  }
  return [...byDay.values()].sort((a, b) => a.day.localeCompare(b.day));
}

/** The organization budget that covers exactly this provider scope, if one exists. */
export function scopeBudget(
  statuses: readonly BudgetStatus[],
  provider: string,
): BudgetStatus | null {
  return (
    statuses.find((s) => s.budget.scope_kind === "org" && s.budget.provider === provider) ?? null
  );
}
