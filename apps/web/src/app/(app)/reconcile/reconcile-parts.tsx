import { AreaNav, DATA_HEALTH } from "@/components/area-nav";
import { CardHeading } from "@/components/card-heading";
import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import Link from "next/link";

import { api, type ProviderInfo, type Summary } from "@/lib/api";
import { formatUsd } from "@/lib/format";
import {
  monthsIn,
  periodPhrase,
  periodTitle,
  type DateRange,
  type TimeFramePreset,
} from "@/lib/time-range";
import { openOrgHref, welcomeHref } from "@/lib/setup";

/** Providers whose control total needs a word on what it covers get a sentence saying so. */
const PROVIDER_TOTAL_NOTES: Record<string, string> = {
  openrouter:
    "The provider total is what OpenRouter billed to credits; traffic on your own provider keys (BYOK) is not included.",
  openai:
    "The provider total is the billed amount of the OpenAI Costs API; every line item, web search and images included, is attributed to the key OpenAI reports it under.",
  cursor:
    "Cursor publishes /teams/spend only for the current billing cycle. Derived seat costs are shown separately and excluded from that comparison; older cycles are unknown.",
};

export function providerTotalNote(provider: string): string | null {
  return PROVIDER_TOTAL_NOTES[provider] ?? null;
}

export type Verdict = "pass" | "fail" | "pending";

const VERDICT: Record<Verdict, { tone: "success" | "critical" | "warning"; text: string }> = {
  pass: { tone: "success", text: "pass" },
  fail: { tone: "critical", text: "fail" },
  pending: { tone: "warning", text: "pending" },
};

/**
 * Control totals are provider-specific, so the aggregated scope cannot reconcile in one
 * report. One card per connected provider or provider with data in the time frame: its total
 * over those days, whether it matches the provider's own figure, and the link to its full
 * checks, which keeps the time frame.
 */
export async function providerCards(
  org: string,
  period: DateRange,
  timeFrame: TimeFramePreset | null,
  isDemo: boolean,
) {
  const touched = monthsIn(period.from, period.to);
  const registry = await api.providers(org);
  const [monthResults, summaryResults] = await Promise.all([
    Promise.allSettled(registry.map((provider) => api.months(org, provider.provider))),
    Promise.allSettled(registry.map((provider) => api.summary(org, provider.provider, period))),
  ]);
  const kept = registry.flatMap((provider, index) => {
    const months = monthResults[index];
    const inRange =
      months?.status === "fulfilled" &&
      months.value.months.some((month) => touched.includes(month));
    if (!provider.connected && !inRange) return [];
    const summary = summaryResults[index];
    return [{ provider, summary: summary?.status === "fulfilled" ? summary.value : null }];
  });
  const included = kept.map((entry) => entry.provider);
  const summaries = kept.map((entry) => entry.summary);
  return (
    <div className="space-y-5">
      <AreaNav label="Data health" items={DATA_HEALTH} current="/reconcile" />
      <PageHeader
        title={`Does ${periodTitle(period.from, period.to)} add up?`}
        description="Each provider publishes its own control total, so the checks run per provider. Open a card for its checks and the cost report breakdown."
      />
      {included.length === 0 ? (
        <EmptyState
          message={`No provider is connected or has data ${periodPhrase(period.from, period.to)}, so there is nothing to reconcile.`}
          action={{ href: welcomeHref(), label: "Connect a provider" }}
        />
      ) : (
        <section className="grid gap-4 lg:grid-cols-2">
          {included.map((info, index) => (
            <ProviderCard
              key={info.provider}
              org={org}
              period={period}
              timeFrame={timeFrame}
              info={info}
              summary={summaries[index] ?? null}
              isDemo={isDemo}
            />
          ))}
        </section>
      )}
    </div>
  );
}

function ProviderCard({
  org,
  period,
  timeFrame,
  info,
  summary,
  isDemo,
}: {
  org: string;
  period: DateRange;
  timeFrame: TimeFramePreset | null;
  info: ProviderInfo;
  summary: Summary | null;
  /** The sample holds no key, which says nothing about how current its data is. */
  isDemo: boolean;
}) {
  const disconnected = !info.connected && !isDemo;
  const verdict: Verdict = summary
    ? summary.provider_matches === null
      ? "pending"
      : summary.provider_matches
        ? "pass"
        : "fail"
    : "pending";
  const v = VERDICT[verdict];
  const note = providerTotalNote(info.provider);
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div>
          <CardHeading className="flex items-center gap-3">
            {info.label}
            <StatusBadge tone={v.tone}>{v.text}</StatusBadge>
            {disconnected ? <StatusBadge tone="neutral">disconnected</StatusBadge> : null}
          </CardHeading>
          <CardDescription>
            {summary
              ? summary.provider_matches === null
                ? "No provider total synced for these days yet."
                : summary.provider_matches
                  ? "Costura total matches the provider total."
                  : "Costura total differs from the provider total."
              : "Could not load this provider's figures; reload to retry."}
            {disconnected ? " This is historical data from a disconnected provider." : ""}
            {note ? ` ${note}` : ""}
          </CardDescription>
        </div>
        <Link
          prefetch={false}
          href={openOrgHref(org, "/reconcile", { scope: info.provider, ...period, timeFrame })}
          className="shrink-0 text-sm text-primary hover:underline"
        >
          See the checks
        </Link>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[auto_1fr]">
          <dt className="text-muted-foreground">Costura total</dt>
          <dd className="font-mono text-foreground">
            {summary ? `${formatUsd(summary.total)} ${summary.currency ?? "USD"}` : "-"}
          </dd>
          <dt className="text-muted-foreground">Provider total</dt>
          <dd className="font-mono text-foreground">
            {summary?.provider_total
              ? `${formatUsd(summary.provider_total)} ${summary.currency ?? "USD"}`
              : "not synced"}
          </dd>
        </dl>
      </CardContent>
    </Card>
  );
}

export function CheckRow({
  title,
  verdict,
  children,
}: {
  title: string;
  verdict: Verdict;
  children: React.ReactNode;
}) {
  const v = VERDICT[verdict];
  return (
    <li className="flex flex-wrap items-start gap-x-4 gap-y-1 py-3">
      <StatusBadge tone={v.tone} className="mt-0.5 w-16 justify-center">
        {v.text}
      </StatusBadge>
      <div className="min-w-0 flex-1">
        <p className="font-medium text-foreground">{title}</p>
        {verdict === "pass" ? (
          <details className="text-sm text-muted-foreground">
            <summary className="cursor-pointer">Details</summary>
            <div className="mt-1">{children}</div>
          </details>
        ) : (
          <div className="text-sm text-muted-foreground">{children}</div>
        )}
      </div>
    </li>
  );
}
