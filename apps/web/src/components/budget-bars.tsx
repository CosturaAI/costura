import { StatusBadge } from "@/components/status-badge";
import type { BudgetAlert, BudgetStatus } from "@/lib/api";
import { alertSentence, budgetTone, type BudgetTone } from "@/lib/budgets";
import { splitLabel } from "@/lib/dimensions";
import { formatPercent, formatUsd } from "@/lib/format";
import { providerLabel } from "@/lib/providers";

const BAR_COLOR: Record<BudgetTone, string> = {
  neutral: "var(--primary)",
  warning: "var(--color-severity-warning)",
  critical: "var(--color-severity-critical)",
};

const TEXT_CLASS: Record<BudgetTone, string> = {
  neutral: "text-secondary-foreground",
  warning: "text-severity-warning",
  critical: "text-severity-critical",
};

/** The bar spans 0..max(100, projected, spent) percent so an overrun stays visible. */
function scale(status: BudgetStatus): number {
  const spent = Number.parseFloat(status.percent);
  const projected = Number.parseFloat(status.projected_percent ?? "0");
  return Math.max(100, spent, projected, ...status.thresholds.map((t) => t.percent));
}

/**
 * One progress bar per budget: spent over the amount, threshold ticks, and a marker for the
 * projected month end when the month is still open. Colour follows the highest crossed line.
 */
export function BudgetBars({
  statuses,
  currency = "USD",
  showProvider = false,
}: {
  statuses: BudgetStatus[];
  currency?: string;
  /** Under the `all` scope a budget caps one provider's spend, next to a total of every
   * provider; the badge says which. */
  showProvider?: boolean;
}) {
  return (
    <ul className="space-y-4">
      {statuses.map((status) => {
        const tone = budgetTone(status);
        const max = scale(status);
        const spent = Number.parseFloat(status.percent);
        const projected =
          status.projected_percent === null ? null : Number.parseFloat(status.projected_percent);
        const name = splitLabel(status.budget.label).name;
        return (
          <li key={status.budget.id} className="text-sm">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
              <span className="flex min-w-0 items-baseline gap-2">
                <span className="font-medium">{name}</span>
                <span className="text-xs text-muted-foreground">
                  {status.budget.scope_kind === "org" ? "organization" : "workspace"}
                </span>
                {showProvider ? (
                  <StatusBadge tone="neutral">{providerLabel(status.budget.provider)}</StatusBadge>
                ) : null}
              </span>
              <span className="font-mono text-xs">
                <span className={TEXT_CLASS[tone]}>{formatPercent(status.percent)}</span>
                <span className="ml-2 text-muted-foreground">
                  {formatUsd(status.spent)} of {formatUsd(status.budget.amount)}{" "}
                  <span className="text-muted-foreground">{currency}</span>
                </span>
              </span>
            </div>
            <div
              role="meter"
              aria-label={`${name} budget`}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.min(100, Math.round(spent))}
              className="relative mt-1.5 h-2.5 w-full overflow-hidden rounded-full bg-muted"
            >
              <div
                className="h-full rounded-full"
                style={{
                  width: `${Math.min(100, (spent / max) * 100)}%`,
                  backgroundColor: BAR_COLOR[tone],
                }}
              />
              {status.thresholds.map((t) => (
                <span
                  key={t.percent}
                  aria-hidden
                  title={`${t.percent}%${t.crossed_at ? " crossed" : ""}`}
                  className="absolute top-0 h-full w-px bg-muted/60"
                  style={{ left: `${(t.percent / max) * 100}%` }}
                />
              ))}
              {projected !== null ? (
                <span
                  aria-hidden
                  title={`projected ${formatPercent(status.projected_percent)}`}
                  className="absolute top-0 h-full w-0.5 border-l border-dashed border-border"
                  style={{ left: `${Math.min(100, (projected / max) * 100)}%` }}
                />
              ) : null}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              alerts at {status.thresholds.map((t) => `${t.percent}%`).join(", ")}
              {status.projected !== null
                ? `; projected ${formatUsd(status.projected)} (${formatPercent(status.projected_percent)})`
                : ""}
            </p>
          </li>
        );
      })}
    </ul>
  );
}

export function BudgetAlertList({ alerts }: { alerts: BudgetAlert[] }) {
  if (alerts.length === 0) {
    return <p className="text-xs text-muted-foreground">No threshold crossed in the month.</p>;
  }
  return (
    <ul aria-label="Budget alerts" className="space-y-1 text-sm">
      {alerts.map((alert) => (
        <li
          key={alert.id}
          className={
            alert.kind === "projection" || alert.threshold === null || alert.threshold >= 100
              ? "text-severity-critical"
              : "text-severity-warning"
          }
        >
          {alertSentence(alert)}
        </li>
      ))}
    </ul>
  );
}
