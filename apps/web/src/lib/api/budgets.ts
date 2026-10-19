/**
 * Budgets and their monthly statuses and alerts, and the invoice totals typed in per month.
 */

import type { Schema } from "./schema";
import { get, scope, send } from "./transport";

/** "person" budgets live under provider "all" and sum one e-mail across every provider. */
export type BudgetScope = "org" | "workspace" | "person" | "team";

type BudgetPeriod = Schema<"BudgetOut">["period"];

export type Budget = Omit<Schema<"BudgetOut">, "scope_kind"> & {
  scope_kind: BudgetScope;
};

export type BudgetAlert = Omit<Schema<"BudgetAlertOut">, "scope_kind" | "kind"> & {
  scope_kind: BudgetScope;
  kind: "threshold" | "projection";
};

export type BudgetStatus = Omit<Schema<"BudgetStatusOut">, "budget" | "thresholds" | "alerts"> & {
  budget: Budget;
  thresholds: { percent: number; crossed_at: string | null }[];
  alerts: BudgetAlert[];
};

export type BudgetStatuses = { month: string; statuses: BudgetStatus[]; alerts: BudgetAlert[] };

/** What a provider invoiced one account for one month, as an owner typed it in. */
export type Invoice = Schema<"InvoiceOut">;

export const budgetsApi = {
  budgets: (org: string, provider: string) =>
    get<{ budgets: Budget[] }>(`${scope(org, provider)}/budgets`),
  budgetStatuses: (org: string, provider: string, month: string) =>
    get<BudgetStatuses>(`${scope(org, provider)}/months/${month}/budgets`),
  setBudget: (
    org: string,
    provider: string,
    scopeKind: BudgetScope,
    scopeId: string,
    amount: string,
    thresholds: number[] | null,
    period: BudgetPeriod = "month",
  ) =>
    send<Budget>(
      "PUT",
      `${scope(org, provider)}/budgets/${scopeKind}/${encodeURIComponent(scopeId)}`,
      { amount, thresholds, period },
    ),
  deleteBudget: (org: string, provider: string, scopeKind: BudgetScope, scopeId: string) =>
    send<void>(
      "DELETE",
      `${scope(org, provider)}/budgets/${scopeKind}/${encodeURIComponent(scopeId)}`,
    ),
  invoices: (org: string, provider: string, month: string) =>
    get<{ month: string; items: Invoice[] }>(`${scope(org, provider)}/months/${month}/invoices`),
  setInvoice: (
    org: string,
    provider: string,
    accountId: number,
    month: string,
    amount: string,
    note: string | null,
  ) =>
    send<Invoice>("PUT", `${scope(org, provider)}/accounts/${accountId}/invoices/${month}`, {
      amount,
      note,
    }),
  deleteInvoice: (org: string, provider: string, accountId: number, month: string) =>
    send<void>("DELETE", `${scope(org, provider)}/accounts/${accountId}/invoices/${month}`),
};
