import Link from "next/link";

import { ActivityCard } from "@/components/activity-card";
import { AttributionTable } from "@/components/attribution-table";
import { CardHeading } from "@/components/card-heading";
import { DailySpendChart } from "@/components/charts/daily-spend-chart";
import { CopyButton } from "@/components/copy-button";
import { Disclosure } from "@/components/disclosure";
import { EmptyState } from "@/components/empty-state";
import {
  CanonicalModelCard,
  EntityAnomaliesCard,
  EntityBudgetCard,
  EntityFigures,
  FurtherBreakdowns,
} from "@/components/entity/entity-cards";
import { Facts, StatusFlags } from "@/components/entity/entity-facts";
import { KeyGovernance } from "@/components/entity/key-governance";
import { KpiCard } from "@/components/kpi-card";
import { PageHeader } from "@/components/page-header";
import { PersonalKeyForm } from "@/components/personal-key-form";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { anomalyMarkers } from "@/lib/anomalies";
import { DIMENSION_LABELS, drillDownHref } from "@/lib/dimensions";
import { ENTITY_KIND_LABELS, type EntityData } from "@/lib/entity";
import { changePercent, formatDelta, formatUsd } from "@/lib/format";
import { providerLabel, sourceLabel } from "@/lib/providers";
import { runsAction } from "@/lib/setup";
import { periodPhrase } from "@/lib/time-range";

/**
 * One page per key, account, workspace, model or person: what it is (inventory facts), what
 * it cost (KPIs, daily chart, breakdown by the next dimension), what went wrong (its
 * anomalies) and, for a workspace, its budget. "Open in Analyze" keeps the pivot tool one
 * click away. A person is one e-mail across providers: the header carries one badge per
 * provider account and the page adds model and key breakdowns.
 */
export function EntityPage({
  data,
  currency = "USD",
  isDemo = false,
}: {
  data: EntityData;
  currency?: string;
  /** The read-only sample: no link to set a budget it would refuse. */
  isDemo?: boolean;
}) {
  const exploreHref = drillDownHref(data.kind, data.id, data.nextBy);
  const month = data.period.to.slice(0, 7);
  const inPeriod = periodPhrase(data.period.from, data.period.to);
  const amount = data.current?.amount ?? null;
  const previousAmount = data.previous?.amount ?? null;
  const change = changePercent(amount, previousAmount);
  const changeValue = Number.parseFloat(change ?? "0");
  const hasActivity = data.current !== null;
  const hasAmount = amount !== null;
  const totalTokens = data.current?.total_tokens ?? 0;
  const cacheShare =
    totalTokens > 0
      ? (((data.current?.tokens.cache_read_tokens ?? 0) / totalTokens) * 100).toFixed(2)
      : null;
  const byokAmount = data.current?.byok_amount ?? null;
  const markers = data.anomalies ? anomalyMarkers(data.anomalies) : [];
  const noun = ENTITY_KIND_LABELS[data.kind].toLowerCase();
  const isPerson = data.facts.kind === "person";
  // The anomalies list filters by series kind; a person's anomalies are account series.
  const anomaliesKind = isPerson ? "account" : data.kind;

  return (
    <div className="space-y-5">
      <PageHeader
        title={data.name}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <StatusBadge tone="neutral">{ENTITY_KIND_LABELS[data.kind]}</StatusBadge>
            {!isPerson && (
              <StatusBadge tone="info">
                {sourceLabel(data.provider, data.providerAccountLabel)}
              </StatusBadge>
            )}
            {data.facts.kind === "person" ? (
              data.facts.item.identities.map((identity) => (
                <StatusBadge key={`${identity.provider}:${identity.external_id}`} tone="info">
                  {providerLabel(identity.provider)} {identity.role}
                </StatusBadge>
              ))
            ) : (
              <span className="inline-flex items-center gap-1 font-mono text-xs text-muted-foreground">
                {data.id}
                <CopyButton value={data.id} label="Copy id" />
              </span>
            )}
            <StatusFlags facts={data.facts} />
          </span>
        }
      >
        {exploreHref ? (
          <Button asChild variant="outline" size="lg">
            <Link href={exploreHref}>Open in Analyze</Link>
          </Button>
        ) : null}
      </PageHeader>

      {data.partial ? (
        <p className="text-sm text-severity-critical">
          Part of this page could not load (previous period, anomalies, projection or budget);
          reload to retry.
        </p>
      ) : null}

      {data.facts.kind === "api_key" && data.facts.item ? (
        <KeyGovernance
          apiKey={data.facts.item}
          signals={data.keySignals}
          snoozes={data.keySnoozes}
          canSnooze={!isDemo}
          consoleUrl={data.keysConsoleUrl}
          consoleLabel={providerLabel(data.provider)}
        />
      ) : null}

      <Disclosure title="Details">
        <Facts facts={data.facts} />
        {data.facts.kind === "api_key" && data.facts.item && !isDemo ? (
          <PersonalKeyForm
            provider={data.facts.item.provider}
            apiKeyId={data.facts.item.external_id}
            marked={
              data.facts.item.person_source === "marked" ? (data.facts.item.person ?? null) : null
            }
          />
        ) : null}

        {data.canonicalModel ? <CanonicalModelCard model={data.canonicalModel} /> : null}

        {data.activity ? <ActivityCard rows={data.activity} /> : null}
        {hasActivity ? (
          <EntityFigures
            data={data}
            currency={currency}
            previousAmount={previousAmount}
            totalTokens={totalTokens}
            cacheShare={cacheShare}
            byokAmount={byokAmount}
          />
        ) : null}
        {data.kind === "workspace" ? (
          <EntityBudgetCard
            budget={data.budget}
            month={month}
            currency={currency}
            isDemo={isDemo}
          />
        ) : null}
      </Disclosure>

      {!hasActivity ? (
        <EmptyState
          message={
            isDemo
              ? `No spend attributed to this ${noun} ${inPeriod}. The sample keeps what stopped spending, as a real inventory does; another time frame may have it.`
              : `No spend attributed to this ${noun} ${inPeriod}.`
          }
          action={isDemo ? undefined : runsAction()}
        />
      ) : (
        <>
          <section aria-label="Headline figures" className="grid gap-4 sm:grid-cols-2">
            <KpiCard
              label={`Spend ${inPeriod}`}
              value={hasAmount ? formatUsd(amount) : "-"}
              unit={hasAmount ? currency : undefined}
              delta={hasAmount ? formatDelta(change) : null}
              deltaTone={changeValue > 0 ? "critical" : changeValue < 0 ? "success" : "neutral"}
              hint={hasAmount ? undefined : "amount unavailable; attribution runs with each import"}
            />
          </section>

          <Card>
            <CardHeader>
              <CardHeading>Daily spend</CardHeading>
              <CardDescription>
                Top {DIMENSION_LABELS[data.nextBy]?.toLowerCase() ?? data.nextBy}s of this {noun}
                {data.series.other ? ', the rest as "other"' : ""}.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <DailySpendChart
                data={data.series}
                currency={currency}
                markers={markers}
                height={260}
              />
            </CardContent>
          </Card>

          <section className="grid gap-4 lg:grid-cols-[3fr_2fr]">
            <Card>
              <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
                <div>
                  <CardHeading>
                    By {DIMENSION_LABELS[data.nextBy]?.toLowerCase() ?? data.nextBy}
                  </CardHeading>
                  <CardDescription>Where this {noun}&apos;s spend went.</CardDescription>
                </div>
                {exploreHref ? (
                  <Link
                    href={exploreHref}
                    className="shrink-0 text-sm text-primary hover:underline"
                  >
                    All rows
                  </Link>
                ) : null}
              </CardHeader>
              <CardContent className="p-0">
                <AttributionTable
                  rows={data.breakdown.rows}
                  dimension={data.nextBy}
                  allocated={data.breakdown.allocated}
                  currency={currency}
                  caption={`${data.name} by ${DIMENSION_LABELS[data.nextBy]?.toLowerCase() ?? data.nextBy}`}
                  compact
                />
              </CardContent>
            </Card>

            <div className="space-y-4">
              {data.anomalies !== null ? (
                <EntityAnomaliesCard
                  anomalies={data.anomalies}
                  anomaliesKind={anomaliesKind}
                  inPeriod={inPeriod}
                />
              ) : null}
            </div>
          </section>

          {data.secondary.length > 0 ? (
            <FurtherBreakdowns data={data} noun={noun} currency={currency} />
          ) : null}
        </>
      )}
    </div>
  );
}
