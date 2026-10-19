"use server";

import { z } from "zod";

import { type ActionState } from "@/lib/action-errors";
import { api, type BudgetScope } from "@/lib/api";
import { ORG_SCOPE_ID } from "@/lib/budgets";
import {
  BUDGET_PERIODS,
  budgetPeriod,
  parseThresholds,
  type BudgetPeriodValue,
} from "@/lib/budgets";
import { splitLabel } from "@/lib/dimensions";
import { parseForm, text } from "@/lib/form";
import { BUDGET_PAGES, runMutation } from "@/lib/mutations";
import { formScope } from "@/lib/view";

/** Server actions behind the budgets page forms; see settings/connection-actions.ts for the pattern. */

const SCOPE_KINDS = [
  "org",
  "workspace",
  "person",
  "team",
] as const satisfies readonly BudgetScope[];
const PERIODS = BUDGET_PERIODS.map((p) => p.value) as [BudgetPeriodValue, ...BudgetPeriodValue[]];

const SetBudget = z.object({
  scope: z
    .string()
    .catch("")
    .transform((value) => {
      const [kind, ...rest] = value.split(":");
      return { kind, id: rest.join(":") };
    })
    .refine(
      (scope): scope is { kind: BudgetScope; id: string } =>
        (SCOPE_KINDS as readonly string[]).includes(scope.kind!),
      "Choose the organization total, a workspace, a team or a person.",
    ),
  amount: text().refine((value) => Number(value) > 0, "Enter an amount above zero."),
  period: z.enum(PERIODS, { error: "Choose a month, a week or a day." }).catch("month"),
  thresholds: text()
    .transform(parseThresholds)
    .refine(
      (value) => value !== undefined,
      "Thresholds are whole percentages between 1 and 200, separated by commas.",
    ),
});

const DeleteBudget = z.object({
  scope_kind: z.enum(SCOPE_KINDS, { error: "Unknown budget scope." }),
  scope_id: text(),
});

export async function setBudgetAction(_prev: ActionState, form: FormData): Promise<ActionState> {
  const { org, provider } = await formScope(form);
  const parsed = parseForm(form, SetBudget, ["scope", "amount", "thresholds"]);
  if (!parsed.ok) return parsed.error;
  const { scope, amount, thresholds, period } = parsed.data;
  if (period !== "month" && (scope.kind === "person" || scope.kind === "team")) {
    return { ok: false, message: `A ${scope.kind} budget is monthly.`, field: "period" };
  }
  const kind = scope.kind as BudgetScope;
  return runMutation(async () => {
    const budget = await api.setBudget(
      org,
      provider,
      kind,
      kind === "org" ? ORG_SCOPE_ID : scope.id,
      amount,
      thresholds ?? null,
      period,
    );
    return `Budget for ${splitLabel(budget.label).name} set to ${budget.amount} ${budget.currency} ${budgetPeriod(budget.period).per}.`;
  }, BUDGET_PAGES);
}

export async function deleteBudgetAction(_prev: ActionState, form: FormData): Promise<ActionState> {
  const { org, provider } = await formScope(form);
  const parsed = parseForm(form, DeleteBudget);
  if (!parsed.ok) return parsed.error;
  const { scope_kind, scope_id } = parsed.data;
  return runMutation(async () => {
    await api.deleteBudget(org, provider, scope_kind, scope_id);
    return "Budget removed with its alerts.";
  }, BUDGET_PAGES);
}
