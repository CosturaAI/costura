import type { Metadata } from "next";
import { AreaNav, GUARDRAILS } from "@/components/area-nav";
import { BudgetAlertList, BudgetBars } from "@/components/budget-bars";
import { CardHeading } from "@/components/card-heading";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { api } from "@/lib/api";
import {
  ALL_PROVIDERS_TOTAL,
  PERSON_BUDGET_PROVIDER,
  personScopeOptions,
  scopeOptionsByProvider,
  teamScopeOptions,
} from "@/lib/budgets";
import { formatMonth } from "@/lib/format";
import { isAll } from "@/lib/providers";
import { sampleCopy } from "@/lib/sample";
import { monthsIn, periodPhrase } from "@/lib/time-range";
import { loadScopeConnections, writesEnabled } from "@/lib/scope";

import { requireView } from "@/lib/view";
import { BudgetEditor } from "./budget-forms";

export const metadata: Metadata = { title: "Budgets" };

const MONTHS_SHOWN = 24;

/**
 * Budgets in one place: each budget with its progress, the alerts recorded, and the forms to
 * add, edit or remove one (only when the API accepts writes). A budget is a monthly amount, so
 * the page answers the time frame month by month: one block per month it touches, newest
 * first; the forms show the newest month's progress. Under `all` the list unions every
 * provider and the form asks which provider the budget is for, since a budget and its
 * workspaces belong to one provider; "Every provider" sets a person budget instead.
 */
export default async function BudgetsPage() {
  const { org, provider, period } = await requireView();
  const touched = monthsIn(period.from, period.to);
  const months = touched.slice(0, MONTHS_SHOWN);
  const aggregated = isAll(provider);
  const [monthly, budgets, workspaces, scope, organization] = await Promise.all([
    Promise.all(months.map((month) => api.budgetStatuses(org, provider, month))),
    api.budgets(org, provider),
    api.workspaces(org, provider, false),
    loadScopeConnections(org, provider),
    api.org(org),
  ]);
  const statuses = monthly[0];
  const currency = statuses!.statuses[0]?.budget.currency ?? "USD";
  // Budgets move alert thresholds, an owner's call; the API answers 403 to a member.
  const isOwner = organization.role === "owner";
  const canWrite = writesEnabled(scope) && isOwner;
  // Only a provider with a key can have a budget worth setting; under one provider the form
  // has no choice to make.
  const targets = aggregated ? scope.providers.filter((p) => p.connected) : scope.providers;
  // The person select needs every user of the organization; only a writer sees the form.
  const [users, teams] =
    aggregated && canWrite
      ? await Promise.all([
          api.users(org, provider, false).then((r) => r.items),
          api
            .teams(org)
            .then((r) => r.teams)
            .catch(() => []),
        ])
      : [[], []];
  const people = personScopeOptions(users);
  const teamOptions = teamScopeOptions(teams);
  // Under `all` one more target sums every provider: the organization total or one person.
  const providerOptions = [
    ...targets.map((p) => ({ value: p.provider, label: p.label })),
    ...(aggregated && targets.length > 0
      ? [{ value: PERSON_BUDGET_PROVIDER, label: "Every provider" }]
      : []),
  ];

  return (
    <div className="space-y-5">
      <AreaNav label="Guardrails" items={GUARDRAILS} current="/budgets" />
      <PageHeader
        title={`Budgets ${periodPhrase(period.from, period.to)}`}
        description={`An amount per month, ISO week or UTC day for an organization total or a workspace, or per month for a team or one person across every provider. The daily sync records when spend crosses a threshold.${months.length > 1 ? ` The time frame touches ${touched.length} months; each one has its block below${touched.length > months.length ? `, the newest ${months.length} shown` : ""}.` : ""}`}
      />

      {organization.is_demo ? (
        <p className="rounded-lg border border-border bg-background px-4 py-3 text-sm text-secondary-foreground">
          The sample organization is read-only. Sign in to your own organization to change budgets.
        </p>
      ) : !writesEnabled(scope) ? (
        <p className="rounded-lg border border-severity-warning/30 bg-severity-warning-bg px-4 py-3 text-sm text-secondary-foreground">
          This Costura instance does not accept changes from the browser, so budgets can be read
          here but not changed.
        </p>
      ) : !isOwner ? (
        <p className="rounded-lg border border-border bg-background px-4 py-3 text-sm text-secondary-foreground">
          Budgets are set by the owners of this organization; you can read them here.
        </p>
      ) : null}

      <Card>
        <CardHeader>
          <CardHeading>All budgets</CardHeading>
          <CardDescription>
            {budgets.budgets.length === 0 && organization.is_demo
              ? sampleCopy.noBudget
              : budgets.budgets.length === 0
                ? "No budget yet. Set one to see how much of the month is spent on the overview and to record when a threshold is crossed."
                : `${budgets.budgets.length} budget${budgets.budgets.length === 1 ? "" : "s"}; a budget applies to every period until changed. Progress is for ${formatMonth(months[0]!)}, or the week or day shown on a week or day budget.`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <BudgetEditor
            org={org}
            provider={provider}
            providers={providerOptions}
            optionsByProvider={{
              ...scopeOptionsByProvider(
                workspaces.items,
                targets.map((p) => p.provider),
              ),
              [PERSON_BUDGET_PROVIDER]: [ALL_PROVIDERS_TOTAL, ...teamOptions, ...people],
            }}
            budgets={budgets.budgets}
            statuses={statuses!.statuses}
            currency={currency}
            canWrite={canWrite}
            showProvider={aggregated}
          />
        </CardContent>
      </Card>

      {months.length === 1 ? (
        statuses!.alerts.length > 0 ? (
          <Card>
            <CardHeader>
              <CardHeading>Alerts in {formatMonth(months[0]!)}</CardHeading>
              <CardDescription>
                Recorded once per threshold per month by the daily sync; changing an amount keeps
                them. Progress for each budget is on its row.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <BudgetAlertList alerts={statuses!.alerts} />
            </CardContent>
          </Card>
        ) : null
      ) : budgets.budgets.length > 0 ? (
        <section aria-label="Month by month" className="space-y-4">
          {months.map((month, index) => (
            <Card key={month}>
              <CardHeader>
                <CardHeading>{formatMonth(month)}</CardHeading>
                <CardDescription>
                  Spend against each budget in the month, and the thresholds it crossed.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <BudgetBars
                  statuses={monthly[index]!.statuses}
                  currency={currency}
                  showProvider={aggregated}
                />
                <BudgetAlertList alerts={monthly[index]!.alerts} />
              </CardContent>
            </Card>
          ))}
        </section>
      ) : null}
    </div>
  );
}
