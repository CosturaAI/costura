import type { Run } from "@/lib/api";

type Freshness = {
  /** The oldest of each account's newest succeeded cost sync, or null before the first one. */
  asOf: string | null;
  /** The account that dates `asOf` when the scope holds several, so the band can name it. */
  staleAccount: string | null;
  /** Latest run per provider account, endpoint and window month, newest first: a cycle syncs
   * the current month and then the previous one, so a failed current month stays visible. */
  latest: Run[];
  failed: number;
};

type FreshnessTone = "neutral" | "success" | "warning" | "critical";

/** The endpoint each provider's spend is read from (`ProviderSpec.cost_endpoint` in the API). */
const COST_ENDPOINTS = new Set([
  "cost_report",
  "costs",
  "analytics_cost",
  "analytics_cost_report",
  "codex_workspace_usage",
  "filtered_usage_events",
]);

const DAY_MS = 86_400_000;
/** Two daily schedule intervals. */
const WARNING_DAYS = 2;
const CRITICAL_DAYS = 3;

/** The header pill state from a runs list (newest first). */
export function freshness(runs: Run[]): Freshness {
  const latest: Run[] = [];
  const seen = new Set<string>();
  for (const run of runs) {
    const key = `${run.provider}/${run.provider_account_id ?? ""}/${run.endpoint}/${run.window_start.slice(0, 7)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    latest.push(run);
  }
  const newest = new Map<string, Run>();
  for (const run of runs) {
    if (!COST_ENDPOINTS.has(run.endpoint) || run.status !== "succeeded") continue;
    const account = `${run.provider}/${run.provider_account_id ?? ""}`;
    if (!newest.has(account)) newest.set(account, run);
  }
  const worst = [...newest.values()].sort((a, b) => a.started_at.localeCompare(b.started_at))[0];
  return {
    asOf: worst?.started_at ?? null,
    staleAccount:
      newest.size > 1 ? (worst?.provider_account_label ?? worst?.provider ?? null) : null,
    latest,
    failed: latest.filter((run) => run.status === "failed").length,
  };
}

/** Whole days since the newest succeeded cost sync; null before the first one. */
function dataAgeDays(asOf: string | null, now: Date = new Date()): number | null {
  if (asOf === null) return null;
  const started = Date.parse(asOf);
  if (Number.isNaN(started)) return null;
  return Math.max(0, Math.floor((now.getTime() - started) / DAY_MS));
}

/** Red on a failed latest run or data older than three days, amber past two days. */
export function freshnessTone(state: Freshness, now: Date = new Date()): FreshnessTone {
  const age = dataAgeDays(state.asOf, now);
  if (age === null) return "neutral";
  if (state.failed > 0 || age > CRITICAL_DAYS) return "critical";
  if (age >= WARNING_DAYS) return "warning";
  return "success";
}

/** "3 days old" once the data is two days old or more; null while current. */
export function ageLabel(state: Freshness, now: Date = new Date()): string | null {
  const age = dataAgeDays(state.asOf, now);
  return age !== null && age >= WARNING_DAYS ? `${age} days old` : null;
}

/** The one line under the header when the data is stale or the latest sync failed. */
export function freshnessBand(runs: Run[], now: Date = new Date()): string | null {
  const state = freshness(runs);
  if (state.asOf === null) return null;
  const age = ageLabel(state, now);
  const failed =
    state.failed > 0
      ? `${state.failed} sync job${state.failed > 1 ? "s" : ""} failed on the latest run`
      : null;
  if (age === null && failed === null) return null;
  const whose = state.staleAccount ? ` for ${state.staleAccount}` : "";
  return [age ? `Spend data${whose} is ${age}` : null, failed].filter(Boolean).join("; ") + ".";
}
