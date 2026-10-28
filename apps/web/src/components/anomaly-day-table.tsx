"use client";

import Link from "next/link";
import { useState } from "react";

import { DataTable, type Column } from "@/components/data-table";
import { StatusBadge } from "@/components/status-badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { DayBreakdown, DayRow } from "@/lib/api";
import {
  DIMENSION_LABELS,
  activeTokenTypes,
  drillDownHref,
  entityHref,
  idHint,
  splitLabel,
} from "@/lib/dimensions";
import { formatTokens, formatUsd } from "@/lib/format";
import { openOrgHref } from "@/lib/setup";

/**
 * Everything the series spent on the anomaly day, one tab per child dimension, every row
 * against its own trailing 7-day average. Rows link to their entity page and to Explore under
 * the anomaly's provider, since the row ids belong to it.
 */
export function AnomalyDayTable({
  breakdowns,
  org,
  provider,
}: {
  breakdowns: DayBreakdown[];
  org: string;
  provider: string;
}) {
  const [dimension, setDimension] = useState(breakdowns[0]?.dimension ?? "");
  const current = breakdowns.find((b) => b.dimension === dimension) ?? breakdowns[0];
  if (!current) return <p className="text-sm text-muted-foreground">No rows for this day.</p>;
  const tokenTypes = activeTokenTypes(current.rows.map((r) => r.tokens));
  const showRequests = current.rows.some((r) => r.request_count > 0);

  const columns: Column<DayRow>[] = [
    {
      id: "label",
      header: DIMENSION_LABELS[current.dimension] ?? current.dimension,
      sortValue: (row) => row.label,
      render: (row) => {
        const { name, id } = splitLabel(row.label);
        const entity = entityHref(current.dimension, row.key, null, provider);
        const drill = drillDownHref(current.dimension, row.key);
        const explore = drill ? openOrgHref(org, drill, { scope: provider }) : null;
        return (
          <span className="flex flex-wrap items-baseline gap-x-2">
            {entity ? (
              <Link href={entity} className="text-primary hover:underline">
                {name}
              </Link>
            ) : (
              <span>{name}</span>
            )}
            {id ? (
              <span className="font-mono text-xs text-muted-foreground" title={id}>
                {idHint(id)}
              </span>
            ) : null}
            {row.new ? <StatusBadge tone="warning">new</StatusBadge> : null}
            {explore ? (
              <Link
                href={explore}
                prefetch={false}
                className="text-xs text-muted-foreground hover:underline"
              >
                Analyze
              </Link>
            ) : null}
          </span>
        );
      },
    },
    {
      id: "amount",
      header: "amount",
      align: "right",
      className: "font-mono text-xs",
      sortValue: (row) => (row.amount === null ? null : Number(row.amount)),
      render: (row) => (row.amount === null ? "-" : formatUsd(row.amount)),
    },
    {
      id: "delta",
      header: "vs 7-day avg",
      align: "right",
      className: "font-mono text-xs",
      sortValue: (row) => (row.delta === null ? null : Number(row.delta)),
      render: (row) =>
        row.delta === null ? (
          "-"
        ) : (
          <span>
            {Number(row.delta) >= 0 ? "+" : ""}
            {formatUsd(row.delta)}
            <span className="block text-muted-foreground">
              avg {formatUsd(row.trailing_average)}
            </span>
          </span>
        ),
    },
    ...tokenTypes.map((type): Column<DayRow> => ({
      id: type.key,
      header: type.short,
      align: "right",
      className: "font-mono text-xs",
      sortValue: (row) => row.tokens[type.key] ?? 0,
      render: (row) => formatTokens(row.tokens[type.key] ?? 0),
    })),
    ...(showRequests
      ? [
          {
            id: "requests",
            header: "requests",
            align: "right",
            className: "font-mono text-xs",
            sortValue: (row) => row.request_count,
            render: (row) => formatTokens(row.request_count),
          } satisfies Column<DayRow>,
        ]
      : []),
    {
      id: "price",
      header: "USD / M tokens",
      align: "right",
      className: "font-mono text-xs",
      sortValue: (row) => (row.cost_per_million === null ? null : Number(row.cost_per_million)),
      render: (row) => (row.cost_per_million === null ? "-" : formatUsd(row.cost_per_million)),
    },
  ];

  return (
    <div className="space-y-3">
      {breakdowns.length > 1 ? (
        <Tabs value={current.dimension} onValueChange={setDimension}>
          <TabsList aria-label="Break the day down by">
            {breakdowns.map((b) => (
              <TabsTrigger key={b.dimension} value={b.dimension}>
                {DIMENSION_LABELS[b.dimension] ?? b.dimension}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      ) : null}
      <DataTable
        key={current.dimension}
        rows={current.rows}
        columns={columns}
        rowKey={(row) => `${current.dimension}:${row.key ?? row.label}`}
        caption={`Spend on the anomaly day by ${DIMENSION_LABELS[current.dimension] ?? current.dimension}`}
        defaultSort={{ id: "delta", direction: "desc" }}
        emptyMessage="No rows for this day."
      />
    </div>
  );
}
