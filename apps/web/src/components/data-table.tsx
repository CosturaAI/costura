"use client";

import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  TableViewport,
} from "@/components/ui/table";
import { useMinWidth } from "@/lib/use-min-width";
import { cn } from "@/lib/utils";

type SortValue = string | number | null | undefined;

export type Column<Row> = {
  /** Stable id, also the default sort key name. */
  id: string;
  header: React.ReactNode;
  /** Value compared when sorting; omit for an unsortable column. Strings compare case-insensitively. */
  sortValue?: (row: Row) => SortValue;
  render: (row: Row, index: number) => React.ReactNode;
  align?: "left" | "right";
  /** Numbers and dates are `font-mono`; the class applies to every cell of the column. */
  className?: string;
  headClassName?: string;
  /**
   * `primary` is the card title. `summary` stays on the card (at most three). `detail` and
   * anything past those three open under More on this row. `hide` drops the column below `md`.
   */
  priority?: "primary" | "summary" | "detail" | "hide";
};

type Sort = { id: string; direction: "asc" | "desc" };

const PAGE_SIZE = 100;

function isEmpty(value: SortValue): boolean {
  return value === null || value === undefined || value === "";
}

function compare(a: NonNullable<SortValue>, b: NonNullable<SortValue>): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { sensitivity: "base", numeric: true });
}

/** Stable sort; empty values ("no usage", missing dates) go last in both directions. */
function sortRows<Row>(rows: Row[], columns: Column<Row>[], sort: Sort | null): Row[] {
  if (!sort) return rows;
  const column = columns.find((c) => c.id === sort.id);
  if (!column?.sortValue) return rows;
  const accessor = column.sortValue;
  const sign = sort.direction === "asc" ? 1 : -1;
  return rows
    .map((row, index) => ({ row, index, value: accessor(row) }))
    .sort((x, y) => {
      const xEmpty = isEmpty(x.value);
      const yEmpty = isEmpty(y.value);
      if (xEmpty || yEmpty) {
        if (xEmpty && yEmpty) return x.index - y.index;
        return xEmpty ? 1 : -1;
      }
      return compare(x.value!, y.value!) * sign || x.index - y.index;
    })
    .map((entry) => entry.row);
}

/**
 * Table with header-click sorting, a sticky header and paging in blocks of 100 rows. The
 * caller keeps the data; this component keeps sort and page state. `caption` is read by
 * screen readers only.
 */
export function DataTable<Row>({
  rows,
  columns,
  rowKey,
  caption,
  defaultSort = null,
  pageSize = PAGE_SIZE,
  emptyMessage = "Nothing to show.",
  rowClassName,
  toolbar,
  className,
  viewportClassName,
}: {
  rows: Row[];
  columns: Column<Row>[];
  rowKey: (row: Row) => string;
  caption: string;
  defaultSort?: Sort | null;
  pageSize?: number;
  emptyMessage?: React.ReactNode;
  rowClassName?: (row: Row) => string | undefined;
  /** Rendered above the table, right-aligned (token toggle, filters). */
  toolbar?: React.ReactNode;
  className?: string;
  viewportClassName?: string;
}) {
  const wide = useMinWidth(768);
  const [sort, setSort] = useState<Sort | null>(defaultSort);
  const [limit, setLimit] = useState(pageSize);
  const sorted = useMemo(() => sortRows(rows, columns, sort), [rows, columns, sort]);
  const visible = sorted.slice(0, limit);
  const desktop = columns.filter((column) => column.priority !== "detail");
  const folded = columns.filter((column) => column.priority === "detail");

  function toggle(column: Column<Row>) {
    if (!column.sortValue) return;
    setSort((current) => {
      if (current?.id !== column.id) {
        return { id: column.id, direction: column.align === "right" ? "desc" : "asc" };
      }
      return { id: column.id, direction: current.direction === "asc" ? "desc" : "asc" };
    });
  }

  return (
    <div className={cn("flex min-w-0 flex-col", className)}>
      {toolbar ? (
        <div className="flex flex-wrap items-center justify-end gap-2 px-3 py-2">{toolbar}</div>
      ) : null}
      {wide ? (
        <TableViewport className={viewportClassName}>
          <Table scroll={false}>
            <TableCaption className="sr-only">{caption}</TableCaption>
            <TableHeader className="sticky top-0 z-10 bg-card shadow-[inset_0_-1px_0_var(--border)]">
              <TableRow className="border-0 hover:bg-transparent">
                {desktop.map((column) => {
                  const active = sort?.id === column.id;
                  const sortable = Boolean(column.sortValue);
                  const ariaSort = active
                    ? sort?.direction === "asc"
                      ? "ascending"
                      : "descending"
                    : sortable
                      ? "none"
                      : undefined;
                  const Icon = active
                    ? sort?.direction === "asc"
                      ? ArrowUp
                      : ArrowDown
                    : ArrowUpDown;
                  return (
                    <TableHead
                      key={column.id}
                      aria-sort={ariaSort}
                      className={cn(
                        "text-xs font-medium text-muted-foreground",
                        column.align === "right" && "text-right",
                        column.headClassName,
                      )}
                    >
                      {sortable ? (
                        <button
                          type="button"
                          onClick={() => toggle(column)}
                          className={cn(
                            "group inline-flex min-h-8 items-center gap-1 rounded hover:text-foreground",
                            column.align === "right" && "flex-row-reverse",
                            active && "text-foreground",
                          )}
                        >
                          {column.header}
                          <Icon
                            aria-hidden
                            className={cn(
                              "h-3 w-3",
                              active ? "opacity-100" : "opacity-0 group-hover:opacity-60",
                            )}
                          />
                        </button>
                      ) : (
                        column.header
                      )}
                    </TableHead>
                  );
                })}
                {folded.length > 0 ? (
                  <TableHead className="text-xs font-medium text-muted-foreground">
                    <span className="sr-only">Details</span>
                  </TableHead>
                ) : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={desktop.length + (folded.length > 0 ? 1 : 0)}
                    className="py-6 text-center text-muted-foreground"
                  >
                    {emptyMessage}
                  </TableCell>
                </TableRow>
              ) : (
                visible.map((row, index) => (
                  <TableRow key={rowKey(row)} className={rowClassName?.(row)}>
                    {desktop.map((column) => (
                      <TableCell
                        key={column.id}
                        className={cn(
                          column.align === "right" && "text-right tabular-nums",
                          column.className,
                        )}
                      >
                        {column.render(row, index)}
                      </TableCell>
                    ))}
                    {folded.length > 0 ? (
                      <TableCell>
                        <details>
                          <summary className="cursor-pointer text-xs text-muted-foreground">
                            Details
                          </summary>
                          <dl className="mt-2 space-y-1 text-sm">
                            {folded.map((column) => (
                              <div key={column.id}>
                                <dt className="text-xs text-muted-foreground">{column.header}</dt>
                                <dd>{column.render(row, index)}</dd>
                              </div>
                            ))}
                          </dl>
                        </details>
                      </TableCell>
                    ) : null}
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </TableViewport>
      ) : (
        <div className="space-y-3">
          <p className="sr-only">{caption}</p>
          {visible.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-sm text-muted-foreground">
              {emptyMessage}
            </p>
          ) : (
            visible.map((row, index) => {
              const shown = columns.filter((column) => column.priority !== "hide");
              const primary = shown.find((column) => column.priority === "primary") ?? shown[0];
              const rest = shown.filter((column) => column !== primary);
              const summary = rest.filter((column) => column.priority !== "detail");
              const face = summary.slice(0, 3);
              const more = [
                ...summary.slice(3),
                ...rest.filter((column) => column.priority === "detail"),
              ];
              return (
                <article
                  key={rowKey(row)}
                  className={cn(
                    "space-y-2 rounded-lg border border-border bg-card p-3",
                    rowClassName?.(row),
                  )}
                >
                  {primary ? (
                    <div className="text-sm font-medium break-words">
                      {primary.render(row, index)}
                    </div>
                  ) : null}
                  <dl className="grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm">
                    {face.map((column) => (
                      <div key={column.id} className="contents">
                        <dt className="text-muted-foreground">{column.header}</dt>
                        <dd className="min-w-0 break-words">{column.render(row, index)}</dd>
                      </div>
                    ))}
                  </dl>
                  {more.length > 0 ? (
                    <details>
                      <summary className="cursor-pointer text-xs text-muted-foreground">
                        More on this row
                      </summary>
                      <dl className="mt-2 grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm">
                        {more.map((column) => (
                          <div key={column.id} className="contents">
                            <dt className="text-muted-foreground">{column.header}</dt>
                            <dd className="min-w-0 break-words">{column.render(row, index)}</dd>
                          </div>
                        ))}
                      </dl>
                    </details>
                  ) : null}
                </article>
              );
            })
          )}
        </div>
      )}
      {sorted.length > limit ? (
        <div className="flex items-center justify-between gap-3 border-t border-border px-3 py-2 text-xs text-muted-foreground">
          <span>
            {visible.length} of {sorted.length} rows
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setLimit((value) => value + pageSize)}
          >
            Load {Math.min(pageSize, sorted.length - limit)} more
          </Button>
        </div>
      ) : null}
    </div>
  );
}
