import type { ReactNode } from "react";

import Link from "next/link";

import { CardHeading } from "@/components/card-heading";
import { CopyButton } from "@/components/copy-button";
import { MethodHint } from "@/components/method-hint";
import { StatusBadge } from "@/components/status-badge";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import type { Owner } from "@/lib/api";
import { formatSignedUsd } from "@/lib/format";

const FALLBACK_SOURCE = "Costura organization";
export const ASSIGNED_ROLE = "assigned in Costura";

/** The Costura organization owners close every list; they are a fallback, not a finding. */
function isFallback(owner: Owner): boolean {
  return owner.source === FALLBACK_SOURCE;
}

/**
 * "Who to contact" on an anomaly: the people the inventory ties to the flagged key or
 * workspace, then the Costura organization owners. The API dedupes by e-mail and orders most
 * specific first, so the first row is the person to write to. When `gap` is set the inventory
 * names nobody, and the card says so before listing the fallback.
 */
/** A principal that drove the day on an organization anomaly: its own anomaly page when it
 * was flagged too, otherwise its entity page. */
export type Driver = { label: string; delta: string; href: string | null; flagged: boolean };

export function OwnersCard({
  owners,
  gap,
  drivers = [],
  action,
}: {
  owners: Owner[];
  gap: string | null;
  drivers?: Driver[];
  /** The assign-a-contact form, rendered under the list when the reader may write. */
  action?: ReactNode;
}) {
  const description =
    owners.length === 0
      ? (gap ?? "The inventory names nobody for this series") +
        " The Costura organization has no owner to fall back on."
      : gap
        ? `${gap} The people below are the Costura organization owners, listed as a fallback; they are not the people behind the spend.`
        : owners[0]!.role === ASSIGNED_ROLE
          ? "A member of this organization recorded who answers for this spend; the inventory's people and the organization owners follow."
          : owners[0]!.role === "used their own login"
            ? "The spend was made with this person's own Claude Code login, so they are the one to write to; the organization owners follow."
            : "From the provider inventory: who created the key, who administers the workspace, then the organization owners.";
  return (
    <Card>
      <CardHeader>
        <CardHeading as="h2">Who to contact</CardHeading>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      {drivers.length > 0 ? (
        <CardContent className="pb-0">
          <p className="text-xs font-medium text-secondary-foreground">Who drove the day</p>
          <ul className="mt-1 divide-y divide-border">
            {drivers.map((driver) => (
              <li
                key={driver.label}
                className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-1.5 text-sm"
              >
                {driver.href ? (
                  <Link href={driver.href} className="font-medium text-primary hover:underline">
                    {driver.label}
                  </Link>
                ) : (
                  <span className="font-medium text-foreground">{driver.label}</span>
                )}
                <span className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span className="font-mono text-foreground">{formatSignedUsd(driver.delta)}</span>
                  {driver.flagged ? <StatusBadge tone="warning">flagged too</StatusBadge> : null}
                </span>
              </li>
            ))}
          </ul>
        </CardContent>
      ) : null}
      {owners.length > 0 ? (
        <CardContent>
          <ul className="divide-y divide-border">
            {owners.map((owner) => (
              <li
                key={owner.email}
                className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2 text-sm"
              >
                <span className="flex min-w-0 items-center gap-2">
                  <a
                    href={`mailto:${owner.email}`}
                    className="truncate font-medium text-primary hover:underline"
                  >
                    {owner.email}
                  </a>
                  <CopyButton value={owner.email} label={`Copy ${owner.email}`} />
                </span>
                <span className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
                  <StatusBadge
                    tone={
                      gap && isFallback(owner)
                        ? "warning"
                        : owner.role === ASSIGNED_ROLE
                          ? "info"
                          : "neutral"
                    }
                  >
                    {gap && isFallback(owner) ? "fallback" : owner.role}
                  </StatusBadge>
                  <span className="min-w-0 break-words">
                    {owner.note ? `${owner.source}: ${owner.note}` : owner.source}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </CardContent>
      ) : null}
      {action ? (
        <CardContent className={owners.length > 0 ? "pt-0" : ""}>{action}</CardContent>
      ) : null}
    </Card>
  );
}

/**
 * One line for list cards and the alerts bell: the first owner and why, or, when the inventory
 * names nobody, that fact with the fallback marked as such.
 */
export function OwnerLine({ owners, gap }: { owners: Owner[]; gap: string | null }) {
  const [owner] = owners;
  if (!owner) {
    return <p className="text-xs text-muted-foreground">Nobody recorded for this series.</p>;
  }
  if (gap) {
    return (
      <p className="text-xs text-muted-foreground">
        <MethodHint text="Nobody recorded in the provider inventory" method={gap} />; fallback{" "}
        <a
          href={`mailto:${owner.email}`}
          className="font-medium text-secondary-foreground hover:underline"
        >
          {owner.email}
        </a>{" "}
        ({owner.role})
      </p>
    );
  }
  return (
    <p className="text-xs text-muted-foreground">
      Contact{" "}
      <a
        href={`mailto:${owner.email}`}
        className="font-medium text-secondary-foreground hover:underline"
      >
        {owner.email}
      </a>{" "}
      ({owner.role})
    </p>
  );
}
