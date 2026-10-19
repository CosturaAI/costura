"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { DataTable, type Column } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { spendKey } from "@/lib/dimensions";
import type { ApiKey, User, Workspace } from "@/lib/api";
import { personHref, splitLabel } from "@/lib/dimensions";
import { formatDate, formatDateTime, formatTokens, formatUsd } from "@/lib/format";
import { providerLabel } from "@/lib/providers";
import { inventoryGap } from "@/lib/sample";
import { syncAction } from "@/lib/setup";

export type InventoryKind = "api-keys" | "workspaces" | "users";

type Spend = Record<string, { amount: string | null; tokens: number }>;

function matches(haystack: (string | null | undefined)[], needle: string): boolean {
  if (!needle) return true;
  const lower = needle.toLowerCase();
  return haystack.some((value) => value?.toLowerCase().includes(lower));
}

/** Sort key for the spend column: dollars when allocated, else tokens; undefined = no usage (sorts last). */
function spendValue(
  spend: Spend,
  item: { provider: string; external_id: string },
): number | undefined {
  const entry = spend[spendKey(item.provider, item.external_id)];
  if (!entry) return undefined;
  return entry.amount !== null ? Number(entry.amount) : entry.tokens;
}

function unused(spend: Spend, item: { provider: string; external_id: string }): boolean {
  return spend[spendKey(item.provider, item.external_id)] === undefined;
}

/**
 * Search box, "unused in the period" toggle and the table for one inventory kind. `spend` maps
 * `spendKey(provider, id)` to the attributed dollars and tokens of the time frame, so each row
 * shows whether the key, workspace or person was active in it. Rows sort by spend descending
 * with the "no usage" rows last; a header click re-sorts. Under `all` (`showProvider`) each
 * row names its provider and links open under it.
 */
export function InventoryTables({
  kind,
  apiKeys,
  workspaces,
  users,
  spend,
  periodLabel,
  showProvider = false,
  provider,
  isDemo = false,
}: {
  kind: InventoryKind;
  apiKeys?: ApiKey[];
  workspaces?: Workspace[];
  users?: User[];
  spend: Spend;
  periodLabel: string;
  showProvider?: boolean;
  /** The provider in scope, which words the empty state when it never lists `kind`. */
  provider?: string;
  /** The read-only sample: nothing to sync from an empty table. */
  isDemo?: boolean;
}) {
  const [search, setSearch] = useState("");
  const [unusedOnly, setUnusedOnly] = useState(false);

  const filteredKeys = useMemo(
    () =>
      (apiKeys ?? []).filter(
        (key) =>
          matches(
            [key.name, key.partial_key_hint, key.workspace, key.created_by, key.external_id],
            search,
          ) &&
          (!unusedOnly || unused(spend, key)),
      ),
    [apiKeys, search, unusedOnly, spend],
  );
  const filteredWorkspaces = useMemo(
    () =>
      (workspaces ?? []).filter(
        (w) =>
          matches([w.name, w.external_id, ...w.admins], search) &&
          (!unusedOnly || unused(spend, w)),
      ),
    [workspaces, search, unusedOnly, spend],
  );
  const filteredUsers = useMemo(
    () =>
      (users ?? []).filter(
        (u) => matches([u.email, u.role], search) && (!unusedOnly || unused(spend, u)),
      ),
    [users, search, unusedOnly, spend],
  );

  const total =
    kind === "api-keys"
      ? (apiKeys ?? []).length
      : kind === "workspaces"
        ? (workspaces ?? []).length
        : (users ?? []).length;
  const shown =
    kind === "api-keys"
      ? filteredKeys.length
      : kind === "workspaces"
        ? filteredWorkspaces.length
        : filteredUsers.length;
  const noun = kind === "api-keys" ? "keys" : kind === "users" ? "accounts" : kind;

  if (total === 0) {
    const gap = provider ? inventoryGap(provider, kind) : null;
    if (gap) return <EmptyState message={gap} />;
    return (
      <EmptyState
        message={
          isDemo
            ? `The sample has no ${noun} in this scope.`
            : `No ${noun} in the inventory. Inventory arrives with the first import.`
        }
        action={isDemo ? undefined : syncAction()}
      />
    );
  }

  const empty = <>Nothing matches{unusedOnly ? "; every row had usage in the period" : ""}.</>;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <Input
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={`Search ${noun}`}
          aria-label={`Search ${noun}`}
          className="h-9 w-64"
        />
        <Button
          type="button"
          size="lg"
          variant={unusedOnly ? "default" : "outline"}
          aria-pressed={unusedOnly}
          onClick={() => setUnusedOnly((v) => !v)}
        >
          Unused in {periodLabel}
        </Button>
        <span className="text-xs text-muted-foreground">
          {shown} of {total} {noun}
        </span>
      </div>

      <div className="rounded-lg border border-border bg-card">
        {kind === "api-keys" ? (
          <ApiKeysTable
            items={filteredKeys}
            spend={spend}
            empty={empty}
            showProvider={showProvider}
          />
        ) : null}
        {kind === "workspaces" ? (
          <WorkspacesTable
            items={filteredWorkspaces}
            spend={spend}
            empty={empty}
            showProvider={showProvider}
          />
        ) : null}
        {kind === "users" ? (
          <UsersTable
            items={filteredUsers}
            spend={spend}
            empty={empty}
            showProvider={showProvider}
          />
        ) : null}
      </div>
    </div>
  );
}

/** Provider column, present only under `all`. */
function providerColumn<Item extends { provider: string }>(show: boolean): Column<Item>[] {
  if (!show) return [];
  return [
    {
      id: "provider",
      header: "provider",
      priority: "summary",
      sortValue: (item) => providerLabel(item.provider),
      render: (item) => <StatusBadge tone="neutral">{providerLabel(item.provider)}</StatusBadge>,
    },
  ];
}

function Missing({ since }: { since: string | null }) {
  if (!since) return <span className="text-xs text-muted-foreground">-</span>;
  return (
    <span className="inline-flex items-center gap-1.5 font-mono text-xs">
      {formatDate(since)}
      <StatusBadge tone="warning">missing</StatusBadge>
    </span>
  );
}

function SpendCell({
  item,
  spend,
}: {
  item: { provider: string; external_id: string };
  spend: Spend;
}) {
  const entry = spend[spendKey(item.provider, item.external_id)];
  if (!entry) return <span className="text-xs text-muted-foreground">no usage</span>;
  return (
    <span className="font-mono text-foreground">
      {entry.amount !== null ? formatUsd(entry.amount) : `${formatTokens(entry.tokens)} tok`}
    </span>
  );
}

function NameCell({
  href,
  name,
  id,
  hint,
}: {
  href: string;
  name: string;
  id: string;
  hint?: string | null;
}) {
  return (
    <span className="flex items-center gap-2" title={id}>
      <Link href={href} className="font-medium text-foreground hover:text-primary hover:underline">
        {name}
      </Link>
      {hint ? <span className="font-mono text-xs text-muted-foreground">{hint}</span> : null}
    </span>
  );
}

const DATE = "font-mono text-xs text-muted-foreground";
const SPEND_SORT = { id: "spend", direction: "desc" } as const;

type TableProps<Item> = {
  items: Item[];
  spend: Spend;
  empty: React.ReactNode;
  showProvider: boolean;
};

function ApiKeysTable({ items, spend, empty, showProvider }: TableProps<ApiKey>) {
  const columns: Column<ApiKey>[] = [
    {
      id: "name",
      header: "name",
      priority: "primary",
      sortValue: (k) => k.name,
      render: (k) => (
        <NameCell
          href={`/keys/${encodeURIComponent(k.external_id)}`}
          name={k.name}
          id={k.external_id}
          hint={k.partial_key_hint}
        />
      ),
    },
    ...providerColumn<ApiKey>(showProvider),
    {
      id: "spend",
      header: "in period",
      priority: "summary",
      align: "right",
      sortValue: (k) => spendValue(spend, k),
      render: (k) => <SpendCell item={k} spend={spend} />,
    },
    {
      id: "workspace",
      header: "workspace",
      priority: "summary",
      className: "text-muted-foreground",
      sortValue: (k) => splitLabel(k.workspace).name,
      render: (k) => {
        const name = splitLabel(k.workspace).name;
        if (!k.workspace_external_id) return name;
        return (
          <Link
            href={`/workspaces/${encodeURIComponent(k.workspace_external_id)}`}
            className="hover:text-foreground hover:underline"
          >
            {name}
          </Link>
        );
      },
    },
    {
      id: "created_by",
      header: "created by",
      priority: "detail",
      className: "text-muted-foreground",
      sortValue: (k) => k.created_by,
      render: (k) => k.created_by || "-",
    },
    {
      id: "status",
      header: "status",
      priority: "summary",
      sortValue: (k) => k.status,
      render: (k) => (
        <StatusBadge tone={k.status === "active" ? "success" : "neutral"}>{k.status}</StatusBadge>
      ),
    },
    {
      id: "created",
      header: "created",
      priority: "detail",
      className: DATE,
      sortValue: (k) => k.created_at,
      render: (k) => formatDate(k.created_at),
    },
    {
      id: "last_seen",
      header: "last seen",
      priority: "detail",
      className: DATE,
      sortValue: (k) => k.last_seen_at,
      render: (k) => formatDateTime(k.last_seen_at),
    },
    {
      id: "missing",
      header: "missing since",
      priority: "summary",
      sortValue: (k) => k.missing_since,
      render: (k) => <Missing since={k.missing_since} />,
    },
  ];
  return (
    <DataTable
      rows={items}
      columns={columns}
      rowKey={(k) => spendKey(k.provider, k.external_id)}
      caption="API keys in the inventory with spend in the period"
      defaultSort={SPEND_SORT}
      emptyMessage={empty}
    />
  );
}

function WorkspacesTable({ items, spend, empty, showProvider }: TableProps<Workspace>) {
  const columns: Column<Workspace>[] = [
    {
      id: "name",
      header: "name",
      sortValue: (w) => w.name,
      render: (w) => (
        <NameCell
          href={`/workspaces/${encodeURIComponent(w.external_id)}`}
          name={w.name}
          id={w.external_id}
        />
      ),
    },
    ...providerColumn<Workspace>(showProvider),
    {
      id: "spend",
      header: "in period",
      align: "right",
      sortValue: (w) => spendValue(spend, w),
      render: (w) => <SpendCell item={w} spend={spend} />,
    },
    {
      id: "admins",
      priority: "detail",
      header: "admins",
      className: "max-w-xs truncate text-muted-foreground",
      render: (w) => w.admins.join(", ") || "-",
    },
    {
      id: "api_keys",
      priority: "detail",
      header: "api keys",
      align: "right",
      className: "font-mono",
      sortValue: (w) => w.api_keys,
      render: (w) => w.api_keys,
    },
    {
      id: "archived",
      header: "archived",
      className: DATE,
      sortValue: (w) => w.archived_at,
      render: (w) => formatDate(w.archived_at),
    },
    {
      id: "created",
      header: "created",
      priority: "detail",
      className: DATE,
      sortValue: (w) => w.created_at,
      render: (w) => formatDate(w.created_at),
    },
    {
      id: "missing",
      header: "missing since",
      sortValue: (w) => w.missing_since,
      render: (w) => <Missing since={w.missing_since} />,
    },
  ];
  return (
    <DataTable
      rows={items}
      columns={columns}
      rowKey={(w) => spendKey(w.provider, w.external_id)}
      caption="Workspaces in the inventory with spend in the period"
      defaultSort={SPEND_SORT}
      emptyMessage={empty}
    />
  );
}

function UsersTable({ items, spend, empty, showProvider }: TableProps<User>) {
  const columns: Column<User>[] = [
    {
      id: "email",
      header: "email",
      sortValue: (u) => u.email,
      render: (u) => (
        <NameCell
          href={`/accounts/${encodeURIComponent(u.external_id)}`}
          name={u.email}
          id={u.external_id}
        />
      ),
    },
    ...providerColumn<User>(showProvider),
    {
      id: "kind",
      header: "kind",
      className: "text-muted-foreground",
      sortValue: (u) => u.kind,
      render: (u) =>
        u.kind === "user" ? (
          <Link href={personHref(u.email)} className="text-primary hover:underline">
            across providers
          </Link>
        ) : (
          u.kind.replace("_", " ")
        ),
    },
    {
      id: "spend",
      header: "in period",
      align: "right",
      sortValue: (u) => spendValue(spend, u),
      render: (u) => <SpendCell item={u} spend={spend} />,
    },
    {
      id: "role",
      header: "role",
      className: "text-muted-foreground",
      sortValue: (u) => u.role,
      render: (u) => u.role,
    },
    {
      id: "added",
      priority: "detail",
      header: "added",
      className: DATE,
      sortValue: (u) => u.added_at,
      render: (u) => formatDate(u.added_at),
    },
    {
      id: "last_seen",
      header: "last seen",
      priority: "detail",
      className: DATE,
      sortValue: (u) => u.last_seen_at,
      render: (u) => formatDateTime(u.last_seen_at),
    },
    {
      id: "missing",
      header: "missing since",
      sortValue: (u) => u.missing_since,
      render: (u) => <Missing since={u.missing_since} />,
    },
  ];
  return (
    <DataTable
      rows={items}
      columns={columns}
      rowKey={(u) => spendKey(u.provider, u.external_id)}
      caption="Accounts in the inventory with spend in the period"
      defaultSort={SPEND_SORT}
      emptyMessage={empty}
    />
  );
}
