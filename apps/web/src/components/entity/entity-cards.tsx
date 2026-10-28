import Link from "next/link";

import { AttributionTable } from "@/components/attribution-table";
import { BudgetBars } from "@/components/budget-bars";
import { CardHeading } from "@/components/card-heading";
import { KpiCard } from "@/components/kpi-card";
import { StatusBadge } from "@/components/status-badge";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import type { BudgetStatus } from "@/lib/api";
import { BYOK_NOTE, isByokAmount } from "@/lib/byok";
import { DIMENSION_LABELS } from "@/lib/dimensions";
import type { EntityData } from "@/lib/entity";
import { signedImpact } from "@/lib/anomaly-text";
import {
  formatCompact,
  formatDayShort,
  formatMonth,
  formatPercent,
  formatSignedUsd,
  formatUsd,
} from "@/lib/format";
import { isAll, providerLabel } from "@/lib/providers";
import { sampleCopy } from "@/lib/sample";
import { periodTitle } from "@/lib/time-range";

const ANOMALIES_SHOWN = 5;

/** Provider-neutral classification of a billing model id. */
export function CanonicalModelCard({
  model,
}: {
  model: NonNullable<EntityData["canonicalModel"]>;
}) {
  return (
    <Card>
      <CardHeader>
        <CardHeading>Canonical model</CardHeading>
        <CardDescription>
          Provider-neutral classification for this billing model id.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[auto_1fr]">
          {Object.entries({
            Brand: model.brand,
            Family: model.family,
            Name: model.name,
            Channel: model.channel,
            Lifecycle: model.lifecycle,
          }).map(([label, value]) => (
            <div key={label} className="contents">
              <dt className="text-muted-foreground">{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}

/** Share, previous period, tokens, projection and BYOK of the entity. */
export function EntityFigures({
  data,
  currency,
  previousAmount,
  totalTokens,
  cacheShare,
  byokAmount,
}: {
  data: EntityData;
  currency: string;
  previousAmount: string | null;
  totalTokens: number;
  cacheShare: string | null;
  byokAmount: string | null;
}) {
  return (
    <section aria-label="More figures" className="grid gap-4 sm:grid-cols-2">
      <KpiCard
        label={
          isAll(data.provider)
            ? "Share of the organization"
            : `Share of ${providerLabel(data.provider)} spend`
        }
        value={formatPercent(data.share)}
        hint={
          isAll(data.provider)
            ? "of the period's spend on every provider"
            : `of the period's ${providerLabel(data.provider)} spend`
        }
      />
      <KpiCard
        label={periodTitle(data.previousPeriod.from, data.previousPeriod.to)}
        value={previousAmount ? formatUsd(previousAmount) : "-"}
        unit={previousAmount ? currency : undefined}
        hint={previousAmount ? undefined : "no spend in the period before"}
      />
      <KpiCard
        label="Tokens"
        value={formatCompact(totalTokens)}
        hint={`${formatPercent(cacheShare)} served from the prompt cache`}
      />
      {data.projection ? (
        <KpiCard
          label="Projected end of month"
          value={formatUsd(data.projection.projected_total)}
          unit={currency}
          hint={`${formatUsd(data.projection.low)} to ${formatUsd(data.projection.high)}, as of ${formatDayShort(data.projection.as_of_day)}`}
        />
      ) : null}
      {isByokAmount(byokAmount) ? (
        <KpiCard
          label="Routed on your own provider keys"
          value={formatUsd(byokAmount)}
          unit={currency}
          hint={BYOK_NOTE}
        />
      ) : null}
    </section>
  );
}

/** A workspace's budget against the month the time frame ends in. */
export function EntityBudgetCard({
  budget,
  month,
  currency,
  isDemo,
}: {
  budget: BudgetStatus | null;
  month: string;
  currency: string;
  isDemo: boolean;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div>
          <CardHeading>Budget</CardHeading>
          <CardDescription>
            Monthly amount set for this workspace, against {formatMonth(month)}.
          </CardDescription>
        </div>
        <Link href={`/budgets`} className="shrink-0 text-sm text-primary hover:underline">
          Budgets
        </Link>
      </CardHeader>
      <CardContent>
        {budget ? (
          <BudgetBars statuses={[budget]} currency={currency} />
        ) : (
          <p className="text-sm text-muted-foreground">
            No budget for this workspace.{" "}
            {isDemo ? (
              sampleCopy.noBudget
            ) : (
              <>
                <Link href={`/budgets`} className="text-primary hover:underline">
                  Set one
                </Link>
                .
              </>
            )}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

/** The entity's latest anomalies, newest first, with the link to all of them. */
export function EntityAnomaliesCard({
  anomalies,
  anomaliesKind,
  inPeriod,
}: {
  anomalies: NonNullable<EntityData["anomalies"]>;
  anomaliesKind: string;
  inPeriod: string;
}) {
  const open = anomalies.filter((a) => a.status === "open");
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div>
          <CardHeading className="flex items-center gap-2">
            Anomalies
            {open.length > 0 ? <StatusBadge tone="critical">{open.length} open</StatusBadge> : null}
          </CardHeading>
          <CardDescription>Days this series spent above its baseline.</CardDescription>
        </div>
        <Link
          href={`/anomalies?status=all&kind=${anomaliesKind}`}
          className="shrink-0 text-sm text-primary hover:underline"
        >
          All anomalies
        </Link>
      </CardHeader>
      <CardContent>
        {anomalies.length === 0 ? (
          <p className="text-sm text-muted-foreground">None detected {inPeriod}.</p>
        ) : (
          <ul className="divide-y divide-border text-sm">
            {anomalies.slice(0, ANOMALIES_SHOWN).map((anomaly) => (
              <li
                key={anomaly.id}
                className="flex flex-wrap items-baseline justify-between gap-x-3 py-1.5"
              >
                <span className="flex items-center gap-2">
                  <StatusBadge
                    tone={
                      anomaly.status === "open"
                        ? "critical"
                        : anomaly.status === "acknowledged"
                          ? "info"
                          : "neutral"
                    }
                  >
                    {anomaly.status}
                  </StatusBadge>
                  {formatDayShort(anomaly.day)}
                </span>
                <span className="font-mono text-xs text-secondary-foreground">
                  {formatSignedUsd(signedImpact(anomaly, anomaly.impact))}
                  {anomaly.impact_percent ? ` (${formatPercent(anomaly.impact_percent)})` : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

/** Model and key breakdowns of the entity, folded away under one disclosure. */
export function FurtherBreakdowns({
  data,
  noun,
  currency,
}: {
  data: EntityData;
  noun: string;
  currency: string;
}) {
  return (
    <details className="rounded-md border border-border bg-background px-4 py-3 text-sm">
      <summary className="cursor-pointer font-medium text-secondary-foreground">
        Further breakdowns
      </summary>
      <section className="mt-3 grid gap-4 lg:grid-cols-2" aria-label="Further breakdowns">
        {data.secondary.map(({ by, usage }) => (
          <Card key={by}>
            <CardHeader>
              <CardHeading>By {DIMENSION_LABELS[by]?.toLowerCase() ?? by}</CardHeading>
              <CardDescription>
                {by === "api_key"
                  ? data.kind === "person"
                    ? "Claude Code keys attributed to this person, every provider together."
                    : `Keys behind this ${noun}'s spend. Claude Code keys and logins are counted under people; other keys are service keys.`
                  : `Models behind this ${noun}'s spend, every provider together.`}
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <AttributionTable
                rows={usage.rows}
                dimension={by}
                allocated={usage.allocated}
                currency={currency}
                caption={`${data.name} by ${DIMENSION_LABELS[by]?.toLowerCase() ?? by}`}
                compact
              />
            </CardContent>
          </Card>
        ))}
      </section>
    </details>
  );
}
