"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { DataTable, type Column } from "@/components/data-table";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import type { UsageRow } from "@/lib/api";
import { BYOK_NOTE, hasByok } from "@/lib/byok";
import {
  DIMENSION_LABELS,
  activeTokenTypes,
  entityHref,
  idHint,
  splitLabel,
} from "@/lib/dimensions";
import { formatPercent, formatTokens, formatUsd } from "@/lib/format";
import { hasAccountLabel, sourceLabel } from "@/lib/providers";
import { cn } from "@/lib/utils";

function secondary(dimension: string, row: UsageRow, id: string | null): string {
  const d = row.details;
  const parts: string[] = [];
  if (dimension === "api_key") {
    parts.push(
      ...[splitLabel(d.workspace ?? "").name, d.created_by, d.hint].filter((part): part is string =>
        Boolean(part),
      ),
    );
  } else if (dimension === "workspace" && d.admins) {
    parts.push(`admins: ${d.admins}`);
  }
  if (id && parts.length === 0) parts.push(idHint(id));
  return parts.join(" - ");
}

function usageRowKey(row: UsageRow): string {
  return `${row.provider ?? "scope"}:${row.key ?? row.label}`;
}

/**
 * Ranked rows with an inline share bar. Amounts come first because that is what people read;
 * token counters sit behind a toggle and only the counters with data appear. Rows link to the
 * entity page of the key, account, workspace or model under the row's own provider; under the
 * `all` scope (`showProvider`) a badge names that provider. The rank column keeps the order of
 * the API (spend descending) whatever the current sort. A BYOK column appears once any row
 * carries a non-zero `byok_amount`; that money is billed by the providers and is not in the
 * amount column. `compact` is the overview card, about 330 px wide under the `all` scope: the
 * figure columns size to their own content, the name column takes what is left and clips, and
 * the provider and status badges sit on the secondary line instead of beside the name.
 * `other` is the spend outside the listed rows: one unranked, unlinked "Other rows" line that
 * stays last under every sort, so the amounts and shares add up to the total.
 */
export function AttributionTable({
  rows,
  dimension,
  allocated,
  currency = "USD",
  compact = false,
  tokensDefault = false,
  showProvider = false,
  caption,
  other = null,
}: {
  rows: UsageRow[];
  dimension: string;
  allocated: boolean;
  currency?: string;
  compact?: boolean;
  tokensDefault?: boolean;
  showProvider?: boolean;
  caption?: string;
  other?: { amount: string; share: string | null } | null;
}) {
  const [showTokens, setShowTokens] = useState(tokensDefault);
  const otherRow = useMemo<UsageRow | null>(
    () =>
      other === null
        ? null
        : {
            key: null,
            label: "Other rows",
            provider: null,
            details: {},
            amount: other.amount,
            share: other.share,
            tokens: {},
            total_tokens: 0,
            web_search_requests: 0,
          },
    [other],
  );
  const shown = useMemo(() => (otherRow ? [...rows, otherRow] : rows), [rows, otherRow]);
  const maxShare = shown.reduce((max, row) => Math.max(max, Number(row.share ?? 0)), 0);
  const rank = useMemo(() => new Map(rows.map((row, i) => [usageRowKey(row), i + 1])), [rows]);
  const tokenColumns = useMemo(
    () => (showTokens ? activeTokenTypes(rows.map((row) => row.tokens)) : []),
    [rows, showTokens],
  );
  const label = DIMENSION_LABELS[dimension] ?? dimension;
  const badgeProvider = showProvider && dimension !== "provider";
  const byokColumn = useMemo(() => hasByok(rows), [rows]);

  const columns: Column<UsageRow>[] = [
    {
      id: "rank",
      header: "#",
      priority: "hide",
      align: "right",
      headClassName: "w-8",
      className: "w-8 font-mono text-xs whitespace-nowrap text-muted-foreground",
      render: (row) => (row === otherRow ? null : rank.get(usageRowKey(row))),
    },
    {
      id: "name",
      header: label,
      priority: "primary",
      sortValue: (row) => (row === otherRow ? null : splitLabel(row.label).name),
      // Compact cards are narrow: the name column takes what the figures leave and clips.
      className: compact ? "w-full max-w-0" : "min-w-40 max-w-md",
      render: (row) => {
        const href = entityHref(dimension, row.key, row.person, row.provider);
        const status = row.details.status ?? "";
        const missing = status.endsWith(" [missing]");
        const { name, id } = splitLabel(row.label);
        const detail = secondary(dimension, row, id);
        const badges = [
          row.provider &&
          (badgeProvider || hasAccountLabel(row.provider, row.provider_account_label)) ? (
            <span key="provider" className="shrink-0">
              <StatusBadge tone="neutral">
                {sourceLabel(row.provider, row.provider_account_label)}
              </StatusBadge>
            </span>
          ) : null,
          missing ? (
            <span key="missing" className="shrink-0">
              <StatusBadge tone="warning">missing</StatusBadge>
            </span>
          ) : null,
          status && !missing && status !== "active" ? (
            <span key="status" className="shrink-0">
              <StatusBadge tone="neutral">{status}</StatusBadge>
            </span>
          ) : null,
        ].filter(Boolean);
        return (
          <>
            <div className="flex items-center gap-2">
              {href ? (
                <Link
                  href={href}
                  className="min-w-0 font-medium break-words text-foreground hover:text-primary hover:underline"
                  title={row.label}
                >
                  {name}
                </Link>
              ) : (
                <span
                  className="min-w-0 font-medium break-words text-secondary-foreground"
                  title={row.label}
                >
                  {name}
                </span>
              )}
              {compact ? null : badges}
            </div>
            {detail || (compact && badges.length > 0) ? (
              <div className="flex flex-wrap items-center gap-2">
                {detail ? (
                  <p className="min-w-0 text-xs break-words text-muted-foreground">{detail}</p>
                ) : null}
                {compact ? badges : null}
              </div>
            ) : null}
          </>
        );
      },
    },
    ...(allocated
      ? ([
          {
            id: "amount",
            header: currency,
            priority: "summary",
            align: "right",
            className: "font-mono whitespace-nowrap",
            sortValue: (row) => (row === otherRow ? null : Number(row.amount ?? 0)),
            render: (row) => formatUsd(row.amount),
          },
          {
            id: "share",
            header: "share",
            priority: "summary",
            headClassName: compact ? undefined : "w-40",
            sortValue: (row) => (row === otherRow ? null : Number(row.share ?? 0)),
            render: (row) => {
              const share = Number(row.share ?? 0);
              return (
                <div className="flex items-center gap-2 whitespace-nowrap">
                  <span
                    className={cn(
                      "h-1.5 overflow-hidden rounded-full bg-muted",
                      compact ? "w-10" : "flex-1",
                    )}
                  >
                    <span
                      className="block h-full rounded-full bg-primary"
                      style={{ width: `${maxShare > 0 ? (share / maxShare) * 100 : 0}%` }}
                    />
                  </span>
                  <span
                    className={cn(
                      "text-right font-mono text-xs text-muted-foreground",
                      compact ? "w-12" : "w-14",
                    )}
                  >
                    {formatPercent(row.share)}
                  </span>
                </div>
              );
            },
          },
        ] satisfies Column<UsageRow>[])
      : []),
    ...(byokColumn
      ? ([
          {
            id: "byok",
            header: <abbr title={BYOK_NOTE}>BYOK</abbr>,
            align: "right",
            className: "font-mono whitespace-nowrap text-muted-foreground",
            sortValue: (row) => (row === otherRow ? null : Number(row.byok_amount ?? 0)),
            render: (row) => formatUsd(row.byok_amount),
          },
        ] satisfies Column<UsageRow>[])
      : []),
    ...tokenColumns.map((column): Column<UsageRow> => ({
      id: column.key,
      header: column.short.toLowerCase(),
      align: "right",
      className: "font-mono text-xs text-muted-foreground",
      sortValue: (row) => (row === otherRow ? null : (row.tokens[column.key] ?? 0)),
      render: (row) => (row === otherRow ? "-" : formatTokens(row.tokens[column.key] ?? 0)),
    })),
    ...(compact
      ? []
      : ([
          {
            id: "tokens",
            header: "tokens",
            priority: "detail",
            align: "right",
            className: "font-mono text-muted-foreground",
            sortValue: (row) => (row === otherRow ? null : row.total_tokens),
            render: (row) => (row === otherRow ? "-" : formatTokens(row.total_tokens)),
          },
        ] satisfies Column<UsageRow>[])),
  ];

  return (
    <DataTable
      rows={shown}
      columns={columns}
      rowKey={usageRowKey}
      caption={caption ?? `Spend by ${label.toLowerCase()}`}
      pageSize={compact ? shown.length || 1 : undefined}
      rowClassName={() => cn(!compact && "hover:bg-background")}
      toolbar={
        compact ? undefined : (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            aria-pressed={showTokens}
            onClick={() => setShowTokens((v) => !v)}
          >
            {showTokens ? "Hide token counters" : "Show token counters"}
          </Button>
        )
      }
    />
  );
}
