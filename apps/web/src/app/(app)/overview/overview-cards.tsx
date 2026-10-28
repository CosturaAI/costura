import Link from "next/link";

import { AttributionTable } from "@/components/attribution-table";
import { BudgetBars } from "@/components/budget-bars";
import { CardHeading } from "@/components/card-heading";
import { CouldNotLoad } from "@/components/could-not-load";
import { ShareList } from "@/components/share-list";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import type { BudgetStatuses, Usage } from "@/lib/api";
import { entityHref } from "@/lib/dimensions";
import { formatMonth } from "@/lib/format";
import { MODELS_TOP } from "@/lib/overview";
import { isAll, providerLabel } from "@/lib/providers";
import { sampleCopy } from "@/lib/sample";
import { runsAction } from "@/lib/setup";

/** What every table card on the Overview shares: the page's provider, currency and whether
 * the amounts are attributed. Bound once per page so each card names only what differs. */
export type TableContext = { allocated: boolean; currency: string; provider: string };

/** Top keys, accounts or people of the range, with a link to the full list in Analyze. */
export function TopCard({
  context,
  title,
  description,
  usage,
  dimension,
  footer,
}: {
  context: TableContext;
  title: string;
  description: string;
  usage: Usage | null;
  dimension: string;
  footer?: string;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div>
          <CardHeading>{title}</CardHeading>
          <CardDescription>{description}</CardDescription>
        </div>
        <Link
          href={`/explore?by=${dimension}`}
          className="shrink-0 text-sm text-primary hover:underline"
        >
          See all
        </Link>
      </CardHeader>
      <CardContent className="p-0">
        {!usage ? (
          <CouldNotLoad what={title.toLowerCase()} className="px-4 pb-4" />
        ) : usage.rows.length === 0 ? (
          <p className="px-4 pb-4 text-sm text-muted-foreground">
            No usage stored for the selected range yet.{" "}
            <Link href={runsAction().href} className="text-primary hover:underline">
              {runsAction().label}
            </Link>
            .
          </p>
        ) : (
          <AttributionTable
            rows={usage.rows}
            dimension={dimension}
            allocated={context.allocated}
            currency={context.currency}
            caption={title}
            showProvider={isAll(context.provider)}
            compact
          />
        )}
        {footer ? (
          <p className="border-t px-4 py-3 text-xs text-muted-foreground">{footer}</p>
        ) : null}
      </CardContent>
    </Card>
  );
}

/** Budgets of the month the time frame ends in. */
export function OverviewBudgetsCard({
  budgets,
  month,
  currency,
  showProvider,
  isDemo,
  provider,
}: {
  budgets: BudgetStatuses | null;
  month: string;
  currency: string;
  showProvider: boolean;
  isDemo: boolean;
  /** The view's scope; under one provider the card lists only that provider's budgets. */
  provider: string;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div>
          <CardHeading>Budgets</CardHeading>
          <CardDescription>
            Spend in {formatMonth(month)} against the monthly amounts; budgets are monthly, so the
            card shows the month the time frame ends in.
          </CardDescription>
        </div>
        <Link href="/budgets" className="shrink-0 text-sm text-primary hover:underline">
          {budgets && budgets.alerts.length > 0
            ? `${budgets.alerts.length} alert${budgets.alerts.length === 1 ? "" : "s"} in ${formatMonth(month)}`
            : sampleCopy.budgetsLink(isDemo)}
        </Link>
      </CardHeader>
      <CardContent>
        {!budgets ? (
          <CouldNotLoad what="the budgets" />
        ) : budgets.statuses.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {isAll(provider)
              ? "No budget set for this organization."
              : `No budget for ${providerLabel(provider)}.`}{" "}
            {isDemo ? (
              sampleCopy.noBudget
            ) : (
              <>
                <Link href="/budgets" className="text-primary hover:underline">
                  Set a monthly budget
                </Link>{" "}
                to see how much of the month is spent and be told when a threshold is crossed.
              </>
            )}
          </p>
        ) : (
          <BudgetBars statuses={budgets.statuses} currency={currency} showProvider={showProvider} />
        )}
      </CardContent>
    </Card>
  );
}

/** Models by share of the range. */
export function OverviewModelsCard({
  models,
  currency,
}: {
  models: Usage | null;
  currency: string;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div>
          <CardHeading>Where the money goes</CardHeading>
          <CardDescription>Models by share of the selected range.</CardDescription>
        </div>
        <Link href={`/explore?by=model`} className="shrink-0 text-sm text-primary hover:underline">
          All models
        </Link>
      </CardHeader>
      <CardContent>
        {models ? (
          <ShareList
            currency={currency}
            items={models.rows.slice(0, MODELS_TOP).map((row) => ({
              key: `${row.provider ?? "scope"}:${row.key ?? row.label}`,
              label: row.label,
              amount: row.amount ?? "0.00",
              share: row.share,
              href: entityHref("model", row.key, null, row.provider),
            }))}
          />
        ) : (
          <CouldNotLoad what="the model breakdown" />
        )}
      </CardContent>
    </Card>
  );
}
