import Link from "next/link";

import { StatusBadge } from "@/components/status-badge";
import { entityHref, personHref, splitLabel } from "@/lib/dimensions";
import type { EntityFacts } from "@/lib/entity";
import { formatDate, formatDateTime } from "@/lib/format";
import { providerLabel } from "@/lib/providers";

export function StatusFlags({ facts }: { facts: EntityFacts }) {
  const item = facts.item;
  if (!item) return null;
  return (
    <>
      {"status" in item && item.status !== "active" ? (
        <StatusBadge tone="neutral">{item.status}</StatusBadge>
      ) : null}
      {"archived_at" in item && item.archived_at ? (
        <StatusBadge tone="neutral">archived {formatDate(item.archived_at)}</StatusBadge>
      ) : null}
      {"missing" in item && item.missing ? (
        <StatusBadge tone="warning">missing since {formatDate(item.missing_since)}</StatusBadge>
      ) : null}
    </>
  );
}

/** Inventory facts as a definition list; models have none. A person lists one provider
 * account per row, each linking to that provider's account page. */
export function Facts({ facts }: { facts: EntityFacts }) {
  if (facts.kind === "model") return null;
  // `key` is stable per row: a person may hold two accounts of one provider, so the term
  // (the provider's name) can repeat.
  const rows: { key: string; term: string; value: React.ReactNode }[] = [];
  if (facts.kind === "person") {
    for (const identity of facts.item.identities) {
      rows.push({
        key: `${identity.provider}:${identity.external_id}`,
        term: providerLabel(identity.provider),
        value: (
          <span className="inline-flex flex-wrap items-baseline gap-x-2">
            <Link
              href={`/accounts/${encodeURIComponent(identity.external_id)}`}
              className="font-mono text-xs text-primary hover:underline"
            >
              {identity.external_id}
            </Link>
            <span className="text-muted-foreground">
              {identity.role}, {identity.keys_created} key{identity.keys_created === 1 ? "" : "s"}
              {identity.missing ? ", missing" : ""}
            </span>
          </span>
        ),
      });
    }
  } else if (facts.kind === "api_key") {
    const k = facts.item;
    rows.push(
      {
        key: "Workspace",
        term: "Workspace",
        value: k.workspace_external_id ? (
          <Link
            href={entityHref("workspace", k.workspace_external_id) ?? "#"}
            className="text-primary hover:underline"
          >
            {splitLabel(k.workspace).name}
          </Link>
        ) : (
          splitLabel(k.workspace).name
        ),
      },
      {
        key: "Created by",
        term: "Created by",
        value: k.created_by_external_id ? (
          <Link
            href={entityHref("account", k.created_by_external_id) ?? "#"}
            className="text-primary hover:underline"
          >
            {k.created_by}
          </Link>
        ) : (
          k.created_by || "-"
        ),
      },
      {
        key: "Counts under",
        term: "Counts under",
        value: k.person ? (
          <span className="inline-flex flex-wrap items-baseline gap-x-2">
            <Link href={personHref(k.person)} className="text-primary hover:underline">
              {k.person}
            </Link>
            <span className="text-muted-foreground">
              {k.person_source === "marked" ? "marked in Costura" : "Claude Code key"}
            </span>
          </span>
        ) : (
          "Service key"
        ),
      },
      {
        key: "Key",
        term: "Key",
        value: <span className="font-mono">{k.partial_key_hint ?? "-"}</span>,
      },
      { key: "Created", term: "Created", value: formatDate(k.created_at) },
      { key: "Expires", term: "Expires", value: formatDate(k.expires_at) },
      { key: "Last seen", term: "Last seen", value: formatDateTime(k.last_seen_at) },
    );
  } else if (facts.kind === "workspace") {
    const w = facts.item;
    rows.push(
      { key: "Admins", term: "Admins", value: w.admins.join(", ") || "-" },
      {
        key: "Active keys",
        term: "Active keys",
        value: <span className="font-mono">{w.api_keys}</span>,
      },
      { key: "Created", term: "Created", value: formatDate(w.created_at) },
      { key: "Last seen", term: "Last seen", value: formatDateTime(w.last_seen_at) },
    );
  } else {
    const u = facts.item;
    rows.push(
      { key: "Role", term: "Role", value: u.role },
      { key: "Added", term: "Added", value: formatDate(u.added_at) },
      { key: "Last seen", term: "Last seen", value: formatDateTime(u.last_seen_at) },
    );
    if (u.kind === "user") {
      rows.push({
        key: "Person",
        term: "Person",
        value: (
          <Link href={personHref(u.email)} className="text-primary hover:underline">
            Across providers
          </Link>
        ),
      });
    } else {
      rows.push({ key: "Kind", term: "Kind", value: u.kind.replace("_", " ") });
    }
  }
  return (
    <dl className="grid gap-x-8 gap-y-2 rounded-lg border border-border bg-card px-4 py-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
      {rows.map((row) => (
        <div key={row.key} className="flex items-baseline gap-2">
          <dt className="w-24 shrink-0 text-muted-foreground">{row.term}</dt>
          <dd className="min-w-0 break-words">{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}
