"use client";

import { DataTable, type Column } from "@/components/data-table";
import { idHint, splitLabel } from "@/lib/dimensions";
import { formatPercent, formatUsd } from "@/lib/format";

type Row = { label: string; amount: string };

/** Reconcile breakdown: one dimension of the provider cost report, sortable, with the share of the total. */
export function BreakdownTable({
  rows,
  dimension,
  total,
  currency,
}: {
  rows: Row[];
  dimension: string;
  total: string;
  currency: string;
}) {
  const totalValue = Number.parseFloat(total);
  const share = (row: Row) =>
    totalValue > 0 ? (Number.parseFloat(row.amount) / totalValue) * 100 : 0;
  const columns: Column<Row>[] = [
    {
      id: "label",
      header: dimension.replace("_", " "),
      sortValue: (row) => splitLabel(row.label).name,
      className: dimension === "day" ? "font-mono" : "font-medium",
      render: (row) => {
        const { name, id } = splitLabel(row.label);
        return (
          <span title={row.label}>
            {name}
            {id ? (
              <span className="ml-2 font-mono text-xs text-muted-foreground" title={id}>
                {idHint(id)}
              </span>
            ) : null}
          </span>
        );
      },
    },
    {
      id: "amount",
      header: currency,
      align: "right",
      className: "font-mono",
      sortValue: (row) => Number.parseFloat(row.amount),
      render: (row) => formatUsd(row.amount),
    },
    {
      id: "share",
      header: "share",
      align: "right",
      headClassName: "w-24",
      className: "font-mono text-xs text-muted-foreground",
      sortValue: share,
      render: (row) => formatPercent(share(row).toFixed(2)),
    },
  ];
  return (
    <DataTable
      rows={rows}
      columns={columns}
      rowKey={(row) => row.label}
      caption={`Provider cost report by ${dimension.replace("_", " ")}`}
      defaultSort={dimension === "day" ? { id: "label", direction: "asc" } : null}
    />
  );
}
