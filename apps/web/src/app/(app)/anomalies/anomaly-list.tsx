"use client";

import Link from "next/link";
import { useState } from "react";

import { CardHeading } from "@/components/card-heading";
import { OwnerLine } from "@/components/owners-card";
import { StatusBadge } from "@/components/status-badge";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import type { Anomaly } from "@/lib/api";
import { investigateHref } from "@/lib/anomaly-links";
import { SEVERITY_LABEL, SEVERITY_TONE, periodShareSentence } from "@/lib/anomaly-impact";
import {
  ANOMALY_KIND_LABELS,
  KIND_LABELS,
  PRINCIPAL_BADGES,
  STATUS_TONE,
  impactAmount,
  anomalyHref,
  baselineSentence,
  episodeSentence,
  formatAnomalyValue,
  groupByDay,
  isDrop,
  kindLabel,
  signedImpact,
  weekdayName,
  triageLine,
} from "@/lib/anomaly-text";
import { drillDownHref, entityHref, idHint, splitLabel } from "@/lib/dimensions";
import { formatDayShort, formatPercent, formatSignedUsd, formatUsd } from "@/lib/format";
import { hasAccountLabel, isAll, sourceLabel } from "@/lib/providers";
import { cn } from "@/lib/utils";

const ENTITY_LINK: Partial<Record<Anomaly["series_kind"], string>> = {
  org: "Analyze the day",
  api_key: "Open the key",
  account: "Open the account",
};

import { BulkStatusBar, StatusForm } from "./status-form";

type Scope = { org: string; provider: string; periodTotal: string };

/** The orders the API answers in; `day` is the only one the list groups. */
type AnomalySort = "day" | "impact" | "severity";

/**
 * One card per anomaly, under day headings (`sort=day`) or in one list by impact
 * (`sort=impact`). Writable scopes add selection, bulk actions and per-card status controls.
 * The whole card opens the anomaly (the title link is stretched over it); the checkbox, the
 * entity link, the owner, the status controls and the drivers sit above it and keep their own
 * targets. Drivers are collapsed to the top one; the rest open on click. Under `all` each card
 * names its provider and its entity links open under that provider.
 */
export function AnomalyList({
  anomalies,
  canWrite,
  sort = "day",
  ...scope
}: Scope & { anomalies: Anomaly[]; canWrite: boolean; sort?: AnomalySort }) {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const groups =
    sort === "day"
      ? groupByDay(anomalies)
      : // `impact` and `severity` arrive in the API's order, which the list keeps.
        [{ day: null, rows: anomalies }];
  const openIds = canWrite ? anomalies.filter((a) => a.status === "open").map((a) => a.id) : [];

  function toggle(id: number, checked: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  return (
    <div className="space-y-5">
      {openIds.length > 1 ? (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <label className="flex items-center gap-2">
            <Checkbox
              checked={openIds.length > 0 && openIds.every((id) => selected.has(id))}
              onCheckedChange={(checked) =>
                setSelected(checked === true ? new Set(openIds) : new Set())
              }
              aria-label="Select every open anomaly"
            />
            Select all open ({openIds.length})
          </label>
        </div>
      ) : null}
      {selected.size > 0 ? (
        <BulkStatusBar
          provider={scope.provider}
          ids={[...selected]}
          onClear={() => setSelected(new Set())}
        />
      ) : null}
      {groups.map((group) => (
        <section
          key={group.day ?? "by-impact"}
          aria-labelledby={group.day ? `day-${group.day}` : undefined}
          aria-label={group.day ? undefined : "Anomalies by impact"}
          className="space-y-3"
        >
          {group.day ? (
            <h2
              id={`day-${group.day}`}
              className="flex items-baseline gap-2 text-sm font-semibold text-foreground"
            >
              {formatDayShort(group.day)}
              <span className="text-xs font-normal text-muted-foreground">
                {weekdayName(group.day)}; {group.rows.length} anomal
                {group.rows.length === 1 ? "y" : "ies"}
                {group.rows.every((row) => row.unit === "USD")
                  ? `; ${formatSignedUsd(group.rows.reduce((sum, a) => sum + signedImpact(a, a.impact), 0))} impact`
                  : "; cost and usage impacts"}
              </span>
            </h2>
          ) : null}
          <ul className="space-y-3">
            {group.rows.map((anomaly) => (
              <li key={anomaly.id}>
                <AnomalyCard
                  anomaly={anomaly}
                  canWrite={canWrite}
                  showDay={group.day === null}
                  selected={selected.has(anomaly.id)}
                  onSelect={(checked) => toggle(anomaly.id, checked)}
                  {...scope}
                />
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function AnomalyCard({
  anomaly,
  selected,
  onSelect,
  provider,
  periodTotal,
  canWrite,
  showDay,
}: Scope & {
  anomaly: Anomaly;
  selected: boolean;
  onSelect: (checked: boolean) => void;
  canWrite: boolean;
  showDay: boolean;
}) {
  const { name, id } = splitLabel(anomaly.label);
  const entity =
    anomaly.series_kind === "org"
      ? investigateHref(anomaly)
      : entityHref(anomaly.series_kind, anomaly.series_id);
  const detail = anomalyHref(anomaly.id);
  const [top, ...rest] = anomaly.root_causes;
  const showProvider = isAll(provider);
  const severity = anomaly.severity;
  const share = periodShareSentence(anomaly, periodTotal);
  const episode = episodeSentence(anomaly);
  const badge = PRINCIPAL_BADGES[anomaly.series_kind];
  // A login anomaly is the user's own; the title already names the person.
  const showOwner = !(anomaly.series_kind === "account" && !anomaly.owners_gap);
  return (
    <Card
      className={cn(
        "relative transition-colors focus-within:ring-2 focus-within:ring-ring hover:bg-background",
        selected && "ring-2 ring-ring",
      )}
    >
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          {canWrite && anomaly.status === "open" ? (
            <Checkbox
              checked={selected}
              onCheckedChange={(checked) => onSelect(checked === true)}
              aria-label={`Select the ${kindLabel(anomaly.series_kind).toLowerCase()} anomaly ${name}`}
              className="relative z-10 mt-1"
            />
          ) : null}
          <div className="min-w-0 space-y-1">
            <CardHeading as="h3" className="flex flex-wrap items-center gap-2">
              <StatusBadge tone={STATUS_TONE[anomaly.status]}>{anomaly.status}</StatusBadge>
              <StatusBadge tone={SEVERITY_TONE[severity]}>{SEVERITY_LABEL[severity]}</StatusBadge>
              {anomaly.kind === "spike" ? null : (
                <StatusBadge tone={isDrop(anomaly) ? "info" : "warning"}>
                  {ANOMALY_KIND_LABELS[anomaly.kind]}
                </StatusBadge>
              )}
              {showProvider || hasAccountLabel(anomaly.provider, anomaly.provider_account_label) ? (
                <StatusBadge tone="neutral">
                  {sourceLabel(anomaly.provider, anomaly.provider_account_label)}
                </StatusBadge>
              ) : null}
              <span className="text-sm font-medium text-muted-foreground">
                {kindLabel(anomaly.series_kind)}
              </span>
              <Link
                href={detail}
                className="truncate text-foreground after:absolute after:inset-0 after:content-[''] focus-visible:outline-none"
              >
                {name}
              </Link>
              {badge ? <StatusBadge tone="info">{badge}</StatusBadge> : null}
              {id ? (
                <span className="font-mono text-xs text-muted-foreground" title={id}>
                  {idHint(id)}
                </span>
              ) : null}
              {showDay ? (
                <span className="text-xs text-muted-foreground">{formatDayShort(anomaly.day)}</span>
              ) : null}
            </CardHeading>
            {triageLine(anomaly) ? (
              <p className="text-xs text-muted-foreground">{triageLine(anomaly)}</p>
            ) : null}
            {anomaly.explanation ? (
              <p className="text-sm text-foreground">{anomaly.explanation}</p>
            ) : null}
            <p className="flex flex-wrap items-baseline gap-x-2 text-sm">
              <span className="font-mono text-base font-semibold text-foreground">
                {impactAmount(anomaly)} {anomaly.currency}
              </span>
              {episode ? <span className="text-secondary-foreground">{episode}</span> : null}
              {share ? <span className="text-secondary-foreground">{share}</span> : null}
            </p>
            <CardDescription>
              {anomaly.unit === "USD" ? "Spent" : "Observed"}{" "}
              {formatAnomalyValue(anomaly, anomaly.actual)}
              {episode
                ? ` on the first day, ${formatAnomalyValue(anomaly, anomaly.total_actual)} over the run`
                : ""}
              ; {baselineSentence(anomaly)}
              {anomaly.impact_percent
                ? `; ${formatPercent(anomaly.impact_percent)} ${isDrop(anomaly) ? "under" : "over"} the baseline`
                : ""}
              .
              {entity ? (
                <>
                  {" "}
                  <Link href={entity} className="relative z-10 text-primary hover:underline">
                    {ENTITY_LINK[anomaly.series_kind]}
                  </Link>
                </>
              ) : null}
            </CardDescription>
            {showOwner ? (
              <div className="relative z-10 w-fit">
                <OwnerLine owners={anomaly.owners} gap={anomaly.owners_gap} />
              </div>
            ) : null}
          </div>
        </div>
        {canWrite ? (
          <div className="relative z-10">
            <StatusForm provider={anomaly.provider} id={anomaly.id} status={anomaly.status} />
          </div>
        ) : null}
      </CardHeader>
      {top ? (
        <CardContent className="relative z-10">
          {/* The first driver sits outside the disclosure: a summary must hold no link. */}
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm text-secondary-foreground">
            <span className="text-xs font-medium tracking-wider text-muted-foreground uppercase">
              {anomaly.root_causes.length === 1
                ? "1 driver"
                : `${anomaly.root_causes.length} drivers`}
            </span>
            <Driver cause={top} />
          </div>
          {rest.length > 0 ? (
            <details className="group mt-1 text-sm">
              <summary className="cursor-pointer text-xs text-primary">
                <span className="group-open:hidden">show all</span>
                <span className="hidden group-open:inline">hide</span>
              </summary>
              <ul className="mt-2 divide-y divide-border border-t border-border">
                {rest.map((cause) => (
                  <li key={`${cause.kind}:${cause.id}`} className="py-1.5">
                    <Driver cause={cause} />
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </CardContent>
      ) : null}
    </Card>
  );
}

function Driver({ cause }: { cause: Anomaly["root_causes"][number] }) {
  const href = entityHref(cause.kind, cause.id) ?? drillDownHref(cause.kind, cause.id);
  const label = splitLabel(cause.label);
  return (
    <span className="flex min-w-0 flex-1 flex-wrap items-baseline justify-between gap-x-4">
      <span className="flex min-w-0 items-baseline gap-2">
        <span className="text-xs text-muted-foreground">{KIND_LABELS[cause.kind]}</span>
        {href ? (
          <Link
            href={href}
            className="inline-block min-h-6 leading-6 break-words text-foreground hover:underline"
          >
            {label.name}
          </Link>
        ) : (
          <span className="break-words text-foreground">{label.name}</span>
        )}
      </span>
      <span className="font-mono text-xs text-secondary-foreground">
        {formatSignedUsd(cause.delta)}{" "}
        <span className="text-muted-foreground">
          ({formatUsd(cause.actual)} vs {formatUsd(cause.baseline)} on the baseline days
          {cause.share
            ? `; ${formatPercent(Math.abs(Number(cause.share)))} of the ${Number(cause.delta) < 0 ? "drop" : "increase"}`
            : ""}
          )
        </span>
      </span>
    </span>
  );
}
