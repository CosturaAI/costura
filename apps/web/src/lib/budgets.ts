import type { BudgetAlert, BudgetStatus, Team, User, Workspace } from "@/lib/api";
import { splitLabel } from "@/lib/dimensions";
import { formatDayShort, formatUsd } from "@/lib/format";

/** `scope_id` of the organization-total budget on the API; defined here, not in `api.ts`,
 * because this module is bundled into the client budget form and `api.ts` is server-only. */
export const ORG_SCOPE_ID = "__org__";

/** "50, 80, 100" -> [50, 80, 100]; null for an empty field (the API applies its default);
 * undefined when a value is not a whole percentage in 1..200. */
export function parseThresholds(raw: string): number[] | null | undefined {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const values = trimmed
    .split(/[\s,;]+/)
    .filter(Boolean)
    .map(Number);
  if (values.some((v) => !Number.isInteger(v) || v < 1 || v > 200)) return undefined;
  return values;
}

export type BudgetTone = "neutral" | "warning" | "critical";

/** Colour of a budget row: critical at or past 100% (or a projection above the amount),
 * warning once any lower threshold is crossed, neutral otherwise. */
export function budgetTone(status: BudgetStatus): BudgetTone {
  const spent = Number.parseFloat(status.percent);
  if (spent >= 100 || status.projection_exceeds) return "critical";
  if (status.highest_crossed !== null) return "warning";
  return "neutral";
}

/** One sentence per alert: "Sep 9: Claude Code crossed 80% (8,120.00 of 10,000.00)". */
export function alertSentence(alert: BudgetAlert): string {
  const day = formatDayShort(alert.triggered_at.slice(0, 10));
  const name = splitLabel(alert.label).name;
  if (alert.kind === "projection") {
    return `${day}: ${name} is projected to end the month at ${formatUsd(alert.projected)}, above the ${formatUsd(alert.amount)} budget`;
  }
  const period = alert.period_start ? ` on ${formatDayShort(alert.period_start)}` : "";
  return `${day}: ${name} crossed ${alert.threshold}%${period} (${formatUsd(alert.spent)} of ${formatUsd(alert.amount)})`;
}

export const BUDGET_PERIODS = [
  { value: "month", label: "Month", per: "a month", adjective: "monthly" },
  { value: "week", label: "Week (Monday start)", per: "a week", adjective: "weekly" },
  { value: "day", label: "Day (UTC)", per: "a day", adjective: "daily" },
] as const;

export type BudgetPeriodValue = (typeof BUDGET_PERIODS)[number]["value"];

export function budgetPeriod(value: string) {
  return BUDGET_PERIODS.find((p) => p.value === value) ?? BUDGET_PERIODS[0];
}

/** What `spent` covers for a day or week budget: "today", "Aug 21" or "week of Aug 17". */
export function currentPeriodLabel(status: BudgetStatus): string | null {
  if (!status.period_start || status.budget.period === "month") return null;
  const day = formatDayShort(status.period_start);
  return status.budget.period === "week" ? `week of ${day}` : day;
}

export type ScopeOption = { value: string; label: string };

/** Select options for the budget form: organization total first, then every workspace still
 * listed by the inventory, encoded as "kind:id". */
function scopeOptions(workspaces: Workspace[]): ScopeOption[] {
  return [
    { value: `org:${ORG_SCOPE_ID}`, label: "Organization total" },
    ...workspaces
      .filter((w) => !w.missing)
      .map((w) => ({ value: `workspace:${w.external_id}`, label: w.name })),
  ];
}

/** Scope options per provider: a budget belongs to one provider and its workspaces do too. */
export function scopeOptionsByProvider(
  workspaces: Workspace[],
  providers: string[],
): Record<string, ScopeOption[]> {
  return Object.fromEntries(
    providers.map((provider) => [
      provider,
      scopeOptions(workspaces.filter((w) => w.provider === provider)),
    ]),
  );
}

/** The pseudo-provider a person budget and the all-provider organization budget are set
 * under: they sum one e-mail, or the whole organization, across providers. */
export const PERSON_BUDGET_PROVIDER = "all";

/** The organization total across every provider, the first option under `all`. */
export const ALL_PROVIDERS_TOTAL: ScopeOption = {
  value: `org:${ORG_SCOPE_ID}`,
  label: "Organization total, every provider",
};

/** One "person:<email>" option per e-mail of a user (not a service account) still listed
 * by any provider, sorted. */
export function personScopeOptions(users: User[]): ScopeOption[] {
  const emails = new Set(
    users
      .filter((u) => u.kind === "user" && !u.missing && u.email.includes("@"))
      .map((u) => u.email.trim().toLowerCase()),
  );
  return [...emails].sort().map((email) => ({ value: `person:${email}`, label: email }));
}

/** One "team:<slug>" option per team, in the order the API lists them (by name). */
export function teamScopeOptions(teams: Pick<Team, "slug" | "name">[]): ScopeOption[] {
  return teams.map((team) => ({ value: `team:${team.slug}`, label: `Team ${team.name}` }));
}

/** The word shown next to a budget's name in the table. */
export function scopeKindLabel(kind: string): string {
  if (kind === "org") return "organization";
  if (kind === "person") return "person, every provider";
  if (kind === "team") return "team, every provider";
  return "workspace";
}
