import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { CardHeading } from "@/components/card-heading";
import { AnomalySeriesChart } from "@/components/charts/anomaly-series-chart";
import { ASSIGNED_ROLE, type Driver, OwnersCard } from "@/components/owners-card";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { ApiError, api } from "@/lib/api";
import { investigateHref } from "@/lib/anomaly-links";
import { SEVERITY_LABEL, SEVERITY_TONE } from "@/lib/anomaly-impact";
import { canOperate } from "@/lib/roles";
import {
  ANOMALY_KIND_LABELS,
  KIND_LABELS,
  PRINCIPAL_BADGES,
  STATUS_TONE,
  anomalyHref,
  baselineSentence,
  episodeSentence,
  isDrop,
  weekdayName,
  triageLine,
} from "@/lib/anomaly-text";
import { entityHref, idHint, splitLabel } from "@/lib/dimensions";
import { formatDateTime, formatDayShort } from "@/lib/format";
import { ALL, sourceLabel } from "@/lib/providers";
import { readSessionToken } from "@/lib/session-cookie";

import { requireView } from "@/lib/view";
import { StatusForm } from "../status-form";
import { AnomalyEvidence } from "./anomaly-evidence";
import { AnomalyFigures } from "./anomaly-figures";
import { AssignOwnerForm } from "./assign-owner-form";
import { MarkRead } from "./mark-read";

/** The tab names the series and the day, from the same cached read the page uses. */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const anomalyId = Number((await params).id);
  if (!Number.isInteger(anomalyId)) return { title: "Anomaly" };
  const { org } = await requireView();
  const detail = await api.anomaly(org, ALL, anomalyId).catch(() => null);
  if (!detail) return { title: "Anomaly" };
  return { title: `${splitLabel(detail.label).name}, ${formatDayShort(detail.day)}` };
}

/**
 * One anomaly as a dossier: who to contact first, the figures people read (impact in USD and
 * as a share of the month), every check the detector applied with its numbers, the baseline
 * samples, everything spent that day against its own history, volume against price, the syncs
 * behind the data, the series' earlier anomalies, the other anomalies of that day and the
 * status controls. Opening it marks the anomaly read in the visitor's inbox.
 */
export default async function AnomalyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const { org } = await requireView();
  const anomalyId = Number(id);
  if (!Number.isInteger(anomalyId)) notFound();
  // The address names neither provider nor month: the row itself says which
  // provider it belongs to and which month its day falls in, whatever the view shows.
  const [detail, organization, setup, token] = await Promise.all([
    api.anomaly(org, ALL, anomalyId).catch((error: unknown) => {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    }),
    api.org(org),
    api.setup(org),
    readSessionToken(),
  ]);
  if (!detail) notFound();

  const canWrite = setup.writes_enabled && !organization.is_demo && canOperate(organization.role);
  const signedIn = token !== null && !organization.is_demo;
  const { name, id: externalId } = splitLabel(detail.label);
  const entity =
    detail.series_kind === "org" ? null : entityHref(detail.series_kind, detail.series_id);
  const explore = investigateHref(detail);
  const severity = detail.severity;
  const episode = episodeSentence(detail);
  const falling = isDrop(detail);
  const listHref = `/anomalies`;
  // On the organization total the people to write to are behind the principals that drove
  // the day; the card names them instead of leaving the reader to the drivers table.
  const drivers: Driver[] =
    detail.series_kind === "org"
      ? detail.root_causes
          .filter((cause) => cause.kind === "api_key" || cause.kind === "account")
          .map((cause) => {
            const own = detail.same_day.find(
              (item) => item.series_kind === cause.kind && item.series_id === cause.id,
            );
            return {
              label: splitLabel(cause.label).name,
              delta: cause.delta,
              href: own ? anomalyHref(own.id) : entityHref(cause.kind, cause.id),
              flagged: own !== undefined,
            };
          })
      : [];

  return (
    <div className="space-y-5">
      {signedIn ? <MarkRead org={org} id={detail.id} /> : null}
      <p className="text-sm">
        <Link href={listHref} className="text-primary hover:underline">
          Anomalies
        </Link>{" "}
        <span className="text-muted-foreground">/ {formatDayShort(detail.day)}</span>
      </p>
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-2">
            {name}
            {externalId ? (
              <span
                className="font-mono text-sm font-normal text-muted-foreground"
                title={externalId}
              >
                {idHint(externalId)}
              </span>
            ) : null}
          </span>
        }
        description={
          <span className="flex flex-wrap items-center gap-2">
            <StatusBadge tone={STATUS_TONE[detail.status]}>{detail.status}</StatusBadge>
            <StatusBadge tone={SEVERITY_TONE[severity]}>{SEVERITY_LABEL[severity]}</StatusBadge>
            {detail.kind === "spike" ? null : (
              <StatusBadge tone={falling ? "info" : "warning"}>
                {ANOMALY_KIND_LABELS[detail.kind]}
              </StatusBadge>
            )}
            <StatusBadge tone="neutral">{KIND_LABELS[detail.series_kind]}</StatusBadge>
            {PRINCIPAL_BADGES[detail.series_kind] ? (
              <StatusBadge tone="info">{PRINCIPAL_BADGES[detail.series_kind]}</StatusBadge>
            ) : null}
            <StatusBadge tone="neutral">
              {sourceLabel(detail.provider, detail.provider_account_label)}
            </StatusBadge>
            <span>
              {weekdayName(detail.day)}, {formatDayShort(detail.day)}
              {episode ? ` to ${formatDayShort(detail.end_day)} (${episode})` : ""}; detected{" "}
              {formatDateTime(detail.detected_at)}
            </span>
          </span>
        }
      >
        {entity ? (
          <Button asChild variant="outline" size="lg">
            <Link href={entity}>
              {detail.series_kind === "account" ? "Open the account" : "Open the key"}
            </Link>
          </Button>
        ) : null}
        {explore ? (
          <Button asChild variant="outline" size="lg">
            <Link href={explore}>Open in Analyze</Link>
          </Button>
        ) : null}
      </PageHeader>
      {detail.explanation ? (
        <p className="max-w-4xl text-base text-foreground">{detail.explanation}</p>
      ) : null}

      {canWrite ? (
        <Card>
          <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3">
            <div>
              <CardHeading>Status</CardHeading>
              <CardDescription>
                {triageLine(detail) ?? "Acknowledge once someone owns it, or ignore it."}
              </CardDescription>
            </div>
            <StatusForm provider={detail.provider} id={detail.id} status={detail.status} />
          </CardHeader>
        </Card>
      ) : null}

      <OwnersCard
        owners={detail.owners}
        gap={detail.owners_gap}
        drivers={drivers}
        action={
          canWrite && detail.series_kind === "api_key" ? (
            <AssignOwnerForm
              provider={detail.provider}
              kind="api_key"
              externalId={detail.series_id}
              current={detail.owners.find((o) => o.role === ASSIGNED_ROLE) ?? null}
            />
          ) : null
        }
      />

      <AnomalyFigures detail={detail} />

      <Card>
        <CardHeader>
          <CardHeading>What normal looked like</CardHeading>
          <CardDescription>
            Eight weeks of this series ending on {formatDayShort(detail.end_day)};{" "}
            {baselineSentence(detail)}
            {episode
              ? `. The baseline is the one computed on ${formatDayShort(detail.day)} and held for the whole episode, so the shift does not become the new normal while it lasts`
              : ""}
            .
          </CardDescription>
        </CardHeader>
        <CardContent>
          <AnomalySeriesChart
            series={detail.series}
            day={detail.day}
            endDay={detail.end_day}
            expected={detail.expected}
            upperBound={detail.upper_bound}
            lowerBound={falling ? (detail.lower_bound ?? detail.expected) : null}
            currency={detail.currency}
          />
        </CardContent>
      </Card>

      <AnomalyEvidence detail={detail} org={org} />
    </div>
  );
}
