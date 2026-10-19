import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { CardHeading } from "@/components/card-heading";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, type AuditTrail } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

import { loadSettings } from "../data";

export const metadata: Metadata = { title: "Audit" };

const PAGE_SIZE = 50;

/** "provider_key_connected" -> "provider key connected". */
function eventLabel(event: string): string {
  return event.replaceAll("_", " ");
}

function detailsText(details: Record<string, string>): string {
  return Object.entries(details)
    .map(([key, value]) => `${key.replaceAll("_", " ")}: ${value}`)
    .join(", ");
}

/**
 * Audit section, owners only: who connected, replaced or removed a key, changed a role or a
 * member, triaged an anomaly or changed a setting, newest first, fifty per page. The rows are
 * never edited; a reset keeps them.
 */
export default async function AuditSettingsPage({
  searchParams,
}: {
  searchParams: Promise<{ page?: string }>;
}) {
  const settings = await loadSettings();
  if (settings.isDemo || !settings.isOwner) notFound();
  const page = Math.max(1, Number.parseInt((await searchParams).page ?? "1", 10) || 1);
  let trail: AuditTrail | null = null;
  try {
    trail = await api.audit(settings.org, PAGE_SIZE, (page - 1) * PAGE_SIZE);
  } catch {
    trail = null;
  }
  const last = trail ? Math.max(1, Math.ceil(trail.total / PAGE_SIZE)) : 1;
  return (
    <Card>
      <CardHeader>
        <CardHeading>Audit</CardHeading>
        <CardDescription>
          Who connected, replaced or removed a provider key, changed a role or a member, triaged an
          anomaly or changed a setting. No key or key fragment is stored. Rows are never edited, and
          a reset keeps them.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {trail === null ? (
          <p className="text-sm text-severity-critical">
            Could not load the audit trail; reload to retry.
          </p>
        ) : trail.events.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing recorded yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableCaption className="sr-only">Audit events, newest first</TableCaption>
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>Who</TableHead>
                  <TableHead>What</TableHead>
                  <TableHead>Target</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {trail.events.map((event) => (
                  <TableRow key={event.id}>
                    <TableCell className="font-mono text-xs whitespace-nowrap">
                      {formatDateTime(event.created_at)}
                    </TableCell>
                    <TableCell className="text-sm">{event.actor_email ?? "system"}</TableCell>
                    <TableCell className="text-sm">
                      {eventLabel(event.event)}
                      {Object.keys(event.details).length > 0 ? (
                        <span className="block text-xs text-muted-foreground">
                          {detailsText(event.details)}
                        </span>
                      ) : null}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {event.target ?? "-"}
                      {event.request_id ? (
                        <span className="block text-muted-foreground">
                          request {event.request_id}
                        </span>
                      ) : null}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
        {trail && trail.total > PAGE_SIZE ? (
          <nav aria-label="Audit pages" className="flex items-center gap-3 text-sm">
            {page > 1 ? (
              <Link
                href={`/settings/audit?page=${page - 1}`}
                className="text-primary hover:underline"
              >
                Newer
              </Link>
            ) : null}
            <span className="text-muted-foreground">
              Page {page} of {last}
            </span>
            {page < last ? (
              <Link
                href={`/settings/audit?page=${page + 1}`}
                className="text-primary hover:underline"
              >
                Older
              </Link>
            ) : null}
          </nav>
        ) : null}
      </CardContent>
    </Card>
  );
}
