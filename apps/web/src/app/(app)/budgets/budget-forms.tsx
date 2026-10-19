"use client";

import { useActionState, useRef, useState } from "react";

import { SubmitButton } from "@/components/submit-button";
import { ConfirmSubmit, Feedback, FieldError, invalid } from "@/components/form-feedback";
import { StatusBadge } from "@/components/status-badge";
import { NativeSelect } from "@/components/ui/native-select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { idleAction } from "@/lib/action-errors";
import type { Budget, BudgetStatus } from "@/lib/api";
import {
  BUDGET_PERIODS,
  budgetPeriod,
  budgetTone,
  currentPeriodLabel,
  scopeKindLabel,
  type BudgetTone,
  type ScopeOption,
} from "@/lib/budgets";
import { splitLabel } from "@/lib/dimensions";
import { formatPercent, formatUsd } from "@/lib/format";
import { providerLabel } from "@/lib/providers";
import { useOnSuccess } from "@/lib/use-on-success";
import { cn } from "@/lib/utils";

import { deleteBudgetAction, setBudgetAction } from "./actions";

type Scope = { org: string; provider: string };
type ProviderOption = { value: string; label: string };

/**
 * Set or replace the budget of one scope, over a month, an ISO week or a UTC day. Posting for a scope that already has a
 * budget replaces its amount and thresholds; alerts already raised stay. `initial` pre-fills
 * the fields when the form opens from a row's Edit button. The form posts to the concrete
 * provider it is for: the scope's own, or the one chosen in the select under `all`.
 */
function BudgetForm({
  providers,
  optionsByProvider,
  budgets,
  initial,
  onDone,
}: {
  providers: ProviderOption[];
  optionsByProvider: Record<string, ScopeOption[]>;
  budgets: Budget[];
  initial?: Budget | null;
  onDone?: () => void;
}) {
  const [state, action, pending] = useActionState(setBudgetAction, idleAction);
  useOnSuccess(state, onDone);
  const [chosen, setChosen] = useState(initial?.provider ?? providers[0]?.value ?? "");
  const options = optionsByProvider[chosen] ?? [];
  const configured = new Set(
    budgets.filter((b) => b.provider === chosen).map((b) => `${b.scope_kind}:${b.scope_id}`),
  );
  const initialScope = initial ? `${initial.scope_kind}:${initial.scope_id}` : options[0]?.value;
  const chooseProvider = providers.length > 1 && !initial;
  return (
    <form action={action} className="space-y-4">
      {chooseProvider ? null : <input type="hidden" name="provider" value={chosen} />}
      <div className={cn("grid gap-4", chooseProvider ? "sm:grid-cols-5" : "sm:grid-cols-4")}>
        {chooseProvider ? (
          <div>
            <label
              className="block text-sm font-medium text-secondary-foreground"
              htmlFor="budget_provider"
            >
              Provider
            </label>
            <NativeSelect
              id="budget_provider"
              name="provider"
              required
              className="mt-1 w-full px-3"
              value={chosen}
              onChange={(event) => setChosen(event.target.value)}
            >
              {providers.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </NativeSelect>
          </div>
        ) : null}
        <div>
          <label
            className="block text-sm font-medium text-secondary-foreground"
            htmlFor="budget_scope"
          >
            Scope
          </label>
          <NativeSelect
            key={chosen}
            id="budget_scope"
            name="scope"
            required
            aria-invalid={invalid(state, "scope") || undefined}
            aria-describedby={invalid(state, "scope") ? "budget_scope_error" : undefined}
            className="mt-1 w-full px-3"
            defaultValue={initialScope}
          >
            {options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
                {configured.has(option.value) ? " (has a budget)" : ""}
              </option>
            ))}
          </NativeSelect>
          <FieldError state={state} field="scope" id="budget_scope_error" />
        </div>
        <div>
          <label
            className="block text-sm font-medium text-secondary-foreground"
            htmlFor="budget_amount"
          >
            Amount (USD)
          </label>
          <Input
            id="budget_amount"
            name="amount"
            type="number"
            inputMode="decimal"
            min="0.01"
            step="0.01"
            placeholder="10000"
            defaultValue={initial?.amount ?? ""}
            className="mt-1 h-9 font-mono"
            required
            aria-invalid={invalid(state, "amount") || undefined}
            aria-describedby={invalid(state, "amount") ? "budget_amount_error" : undefined}
          />
          <FieldError state={state} field="amount" id="budget_amount_error" />
        </div>
        <div>
          <label
            className="block text-sm font-medium text-secondary-foreground"
            htmlFor="budget_period"
          >
            Per
          </label>
          <NativeSelect
            id="budget_period"
            name="period"
            className="mt-1 w-full px-3"
            defaultValue={initial?.period ?? "month"}
            aria-invalid={invalid(state, "period") || undefined}
            aria-describedby={invalid(state, "period") ? "budget_period_error" : undefined}
          >
            {BUDGET_PERIODS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </NativeSelect>
          <FieldError state={state} field="period" id="budget_period_error" />
        </div>
        <div>
          <label
            className="block text-sm font-medium text-secondary-foreground"
            htmlFor="budget_thresholds"
          >
            Alert at (% of amount)
          </label>
          <Input
            id="budget_thresholds"
            name="thresholds"
            type="text"
            placeholder="50, 80, 100"
            defaultValue={initial?.thresholds.join(", ") ?? ""}
            className="mt-1 h-9 font-mono"
            aria-invalid={invalid(state, "thresholds") || undefined}
            aria-describedby={invalid(state, "thresholds") ? "budget_thresholds_error" : undefined}
          />
          <FieldError state={state} field="thresholds" id="budget_thresholds_error" />
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        Mirror the spend limit set in the provider&apos;s console for the organization or a
        workspace; the management APIs do not expose it. Costura compares spend and the month-end
        projection with the amount and records an alert the first time each threshold is crossed. A
        week or day budget records its alerts once per week or day, without a projection; a person
        budget is monthly. Nothing is enforced at the provider.
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <SubmitButton size="lg" pending={pending}>
          {pending ? "Saving..." : initial ? "Save changes" : "Save budget"}
        </SubmitButton>
        {onDone ? (
          <Button type="button" variant="ghost" size="lg" onClick={onDone}>
            Cancel
          </Button>
        ) : null}
        <Feedback state={state} />
      </div>
    </form>
  );
}

/** Posts to the budget's own provider, which is what the DELETE route needs under `all`. */
function RemoveBudgetForm({ budget }: { budget: Budget }) {
  const [state, action, pending] = useActionState(deleteBudgetAction, idleAction);
  const name = splitLabel(budget.label).name;
  const formId = `remove-budget-${budget.id}`;
  return (
    <form id={formId} action={action} className="flex items-center justify-end gap-2">
      <input type="hidden" name="provider" value={budget.provider} />
      <input type="hidden" name="scope_kind" value={budget.scope_kind} />
      <input type="hidden" name="scope_id" value={budget.scope_id} />
      <Feedback state={state} className="text-xs" />
      <ConfirmSubmit
        formId={formId}
        title={`Remove the budget for ${name}?`}
        description="Its alerts for every month are deleted with it. The limit set at the provider is not touched."
        confirmLabel="Remove budget"
        pending={pending}
        aria-label={`Remove the budget for ${name}`}
      >
        {pending ? "Removing..." : "Remove"}
      </ConfirmSubmit>
    </form>
  );
}

const BAR_COLOR: Record<BudgetTone, string> = {
  neutral: "var(--primary)",
  warning: "var(--color-severity-warning)",
  critical: "var(--color-severity-critical)",
};

/**
 * One row per budget with its bar, percent, projection and thresholds; Edit opens the form
 * below the table pre-filled with the row, Add opens it empty. With no budget the form is
 * open from the start. `showProvider` (the `all` scope) adds a provider badge per row.
 */
export function BudgetEditor({
  providers,
  optionsByProvider,
  budgets,
  statuses,
  currency,
  canWrite,
  showProvider = false,
}: Scope & {
  providers: ProviderOption[];
  optionsByProvider: Record<string, ScopeOption[]>;
  budgets: Budget[];
  statuses: BudgetStatus[];
  currency: string;
  canWrite: boolean;
  showProvider?: boolean;
}) {
  const [editing, setEditing] = useState<Budget | null | "new">(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const closeSheet = () => {
    const target = returnFocus.current;
    setEditing(null);
    requestAnimationFrame(() => target?.focus());
  };
  // With no connected provider there is nothing to post a budget to.
  const canAdd = canWrite && providers.length > 0;
  return (
    <div className="space-y-5">
      {statuses.length > 0 ? (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <Table scroll={false}>
            <TableCaption className="sr-only">Budgets and how much of each is spent</TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead>budget</TableHead>
                {showProvider ? <TableHead>provider</TableHead> : null}
                <TableHead className="w-56">spent</TableHead>
                <TableHead className="text-right">{currency}</TableHead>
                <TableHead className="text-right">projected</TableHead>
                <TableHead>alert at</TableHead>
                {canWrite ? <TableHead className="text-right">actions</TableHead> : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {statuses.map((status) => {
                const tone = budgetTone(status);
                const spent = Number.parseFloat(status.percent);
                const name = splitLabel(status.budget.label).name;
                const period = currentPeriodLabel(status);
                return (
                  <TableRow key={status.budget.id}>
                    <TableCell>
                      <span className="font-medium">{name}</span>
                      <span className="ml-2 text-xs text-muted-foreground">
                        {scopeKindLabel(status.budget.scope_kind)}
                        {status.budget.period === "month"
                          ? null
                          : `, ${budgetPeriod(status.budget.period).adjective}`}
                      </span>
                    </TableCell>
                    {showProvider ? (
                      <TableCell>
                        <StatusBadge tone="neutral">
                          {providerLabel(status.budget.provider)}
                        </StatusBadge>
                      </TableCell>
                    ) : null}
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <span
                          role="meter"
                          aria-label={`${name} budget`}
                          aria-valuemin={0}
                          aria-valuemax={100}
                          aria-valuenow={Math.min(100, Math.round(spent))}
                          className="h-2 flex-1 overflow-hidden rounded-full bg-muted"
                        >
                          <span
                            className="block h-full rounded-full"
                            style={{
                              width: `${Math.min(100, spent)}%`,
                              backgroundColor: BAR_COLOR[tone],
                            }}
                          />
                        </span>
                        <span
                          className={cn(
                            "w-14 text-right font-mono text-xs",
                            tone === "critical" && "text-severity-critical",
                            tone === "warning" && "text-severity-warning",
                          )}
                        >
                          {formatPercent(status.percent)}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">
                      {formatUsd(status.spent)}{" "}
                      <span className="text-muted-foreground">
                        of {formatUsd(status.budget.amount)}
                        {period ? `, ${period}` : null}
                      </span>
                    </TableCell>
                    <TableCell
                      className={cn(
                        "text-right font-mono text-xs",
                        status.projection_exceeds && "text-severity-critical",
                      )}
                    >
                      {status.projected === null
                        ? "-"
                        : `${formatUsd(status.projected)} (${formatPercent(status.projected_percent)})`}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {status.thresholds
                        .map((t) => `${t.percent}%${t.crossed_at ? "*" : ""}`)
                        .join(", ")}
                    </TableCell>
                    {canWrite ? (
                      <TableCell>
                        <div className="flex items-center justify-end gap-2">
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={(event) => {
                              returnFocus.current = event.currentTarget;
                              setEditing(status.budget);
                            }}
                            aria-label={`Edit the budget for ${name}`}
                          >
                            Edit
                          </Button>
                          <RemoveBudgetForm budget={status.budget} />
                        </div>
                      </TableCell>
                    ) : null}
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      ) : null}
      {statuses.some((s) => s.thresholds.some((t) => t.crossed_at)) ? (
        <p className="text-xs text-muted-foreground">
          * threshold crossed in the month shown (in the day or week shown for a day or week budget)
        </p>
      ) : null}
      {canWrite && !canAdd && budgets.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Connect a provider key before setting a budget.
        </p>
      ) : null}
      {canAdd ? (
        budgets.length === 0 ? (
          // The first budget: the form is the page's main action, inline rather than in a sheet
          // that has nothing behind it to return to.
          <section
            aria-label="New budget"
            className="space-y-3 rounded-lg border border-border p-4"
          >
            <h3 className="text-sm font-medium text-foreground">New budget</h3>
            <BudgetForm
              providers={providers}
              optionsByProvider={optionsByProvider}
              budgets={budgets}
              initial={null}
            />
          </section>
        ) : editing === null ? (
          <Button
            type="button"
            variant="outline"
            size="lg"
            onClick={(event) => {
              returnFocus.current = event.currentTarget;
              setEditing("new");
            }}
          >
            Add a budget
          </Button>
        ) : (
          <Sheet
            open
            onOpenChange={(open) => {
              if (!open) closeSheet();
            }}
          >
            <SheetContent className="overflow-y-auto sm:max-w-md">
              <SheetHeader>
                <SheetTitle>
                  {editing === "new"
                    ? "New budget"
                    : `Edit the budget for ${splitLabel(editing.label).name}${showProvider ? ` (${providerLabel(editing.provider)})` : ""}`}
                </SheetTitle>
              </SheetHeader>
              <div className="px-4 pb-4">
                <BudgetForm
                  key={editing === "new" ? "new" : editing.id}
                  providers={providers}
                  optionsByProvider={optionsByProvider}
                  budgets={budgets}
                  initial={editing === "new" ? null : editing}
                  onDone={closeSheet}
                />
              </div>
            </SheetContent>
          </Sheet>
        )
      ) : null}
    </div>
  );
}
