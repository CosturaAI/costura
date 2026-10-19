/** Budget fixtures: budgets, alerts and monthly statuses. */

import type { Budget, BudgetAlert, BudgetStatus, BudgetStatuses } from "@/lib/api";

import { MONTH, OTHER_PROVIDER, PROVIDER } from "./common";

export const orgBudget: Budget = {
  id: 1,
  provider: PROVIDER,
  scope_kind: "org",
  scope_id: "__org__",
  label: "organization total",
  amount: "60000.00",
  currency: "USD",
  thresholds: [50, 80, 100],
  period: "month",
  created_at: "2026-08-01T10:00:00+00:00",
  updated_at: "2026-08-01T10:00:00+00:00",
};

export const workspaceBudget: Budget = {
  id: 2,
  provider: PROVIDER,
  scope_kind: "workspace",
  scope_id: "wrkspc_redacted_a",
  label: "Platform",
  amount: "10000.00",
  currency: "USD",
  thresholds: [80, 100],
  period: "month",
  created_at: "2026-08-01T10:00:00+00:00",
  updated_at: "2026-08-03T10:00:00+00:00",
};

export const budgets: Budget[] = [orgBudget, workspaceBudget];

export const thresholdAlert: BudgetAlert = {
  id: 11,
  budget_id: 2,
  scope_kind: "workspace",
  scope_id: "wrkspc_redacted_a",
  label: "Platform",
  month: MONTH,
  period_start: null,
  kind: "threshold",
  threshold: 80,
  spent: "8120.00",
  projected: "11800.00",
  amount: "10000.00",
  currency: "USD",
  triggered_at: "2026-08-09T06:02:00+00:00",
};

export const projectionAlert: BudgetAlert = {
  id: 12,
  budget_id: 2,
  scope_kind: "workspace",
  scope_id: "wrkspc_redacted_a",
  label: "Platform",
  month: MONTH,
  period_start: null,
  kind: "projection",
  threshold: null,
  spent: "8120.00",
  projected: "11800.00",
  amount: "10000.00",
  currency: "USD",
  triggered_at: "2026-08-09T06:02:00+00:00",
};

export const orgBudgetStatus: BudgetStatus = {
  budget: orgBudget,
  period_start: null,
  period_end: null,
  spent: "56056.12",
  percent: "93.43",
  projected: "52100.00",
  projected_percent: "86.83",
  thresholds: [
    { percent: 50, crossed_at: "2026-08-05T06:02:00+00:00" },
    { percent: 80, crossed_at: "2026-08-08T06:02:00+00:00" },
    { percent: 100, crossed_at: null },
  ],
  highest_crossed: 80,
  projection_exceeds: false,
  alerts: [
    {
      ...thresholdAlert,
      id: 9,
      budget_id: 1,
      scope_kind: "org",
      scope_id: "__org__",
      label: "organization total",
      threshold: 50,
      spent: "30100.00",
      amount: "60000.00",
      triggered_at: "2026-08-05T06:02:00+00:00",
    },
    {
      ...thresholdAlert,
      id: 10,
      budget_id: 1,
      scope_kind: "org",
      scope_id: "__org__",
      label: "organization total",
      threshold: 80,
      spent: "48200.00",
      amount: "60000.00",
      triggered_at: "2026-08-08T06:02:00+00:00",
    },
  ],
};

export const workspaceBudgetStatus: BudgetStatus = {
  budget: workspaceBudget,
  period_start: null,
  period_end: null,
  spent: "8120.00",
  percent: "81.20",
  projected: "11800.00",
  projected_percent: "118.00",
  thresholds: [
    { percent: 80, crossed_at: "2026-08-09T06:02:00+00:00" },
    { percent: 100, crossed_at: null },
  ],
  highest_crossed: 80,
  projection_exceeds: true,
  alerts: [thresholdAlert, projectionAlert],
};

export const budgetStatuses: BudgetStatuses = {
  month: MONTH,
  statuses: [orgBudgetStatus, workspaceBudgetStatus],
  alerts: [projectionAlert, thresholdAlert, ...orgBudgetStatus.alerts.slice().reverse()],
};

export const noBudgets: BudgetStatuses = { month: MONTH, statuses: [], alerts: [] };

export const openRouterBudget: Budget = {
  ...orgBudget,
  id: 3,
  provider: OTHER_PROVIDER,
  amount: "2000.00",
};

export const openRouterBudgetStatus: BudgetStatus = {
  ...orgBudgetStatus,
  budget: openRouterBudget,
  period_start: null,
  period_end: null,
  spent: "1200.00",
  percent: "60.00",
  projected: null,
  projected_percent: null,
  thresholds: [
    { percent: 50, crossed_at: "2026-08-20T06:02:00+00:00" },
    { percent: 80, crossed_at: null },
    { percent: 100, crossed_at: null },
  ],
  highest_crossed: 50,
  projection_exceeds: false,
  alerts: [],
};
