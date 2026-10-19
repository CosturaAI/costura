"use client";

import type { ReactNode } from "react";

import { CopyDetails } from "@/components/copy-details";
import { StatusBadge, runTone } from "@/components/status-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  TableViewport,
} from "@/components/ui/table";
import type { Run } from "@/lib/api";
import { formatDate, formatDateTime, formatDuration, formatTokens } from "@/lib/format";
import { providerLabel } from "@/lib/providers";
import { endpointLabel } from "@/lib/run-labels";
import { useMinWidth } from "@/lib/use-min-width";

type RunColumn = {
  key: string;
  heading: string;
  dense: boolean;
  headClassName?: string;
  cellClassName?: string;
  render: (run: Run) => ReactNode;
};

/** One definition drives both headings and cells, including the reduced freshness-drawer view. */
function runColumns(showProvider: boolean): RunColumn[] {
  const columns: RunColumn[] = [
    {
      key: "job",
      heading: "job",
      dense: true,
      render: (run) => <span className="font-medium">{endpointLabel(run.endpoint)}</span>,
    },
    {
      key: "status",
      heading: "status",
      dense: true,
      render: (run) => <StatusBadge tone={runTone(run.status)}>{run.status}</StatusBadge>,
    },
    {
      key: "started",
      heading: "started",
      dense: true,
      cellClassName: "font-mono text-xs text-muted-foreground",
      render: (run) => formatDateTime(run.started_at),
    },
    {
      key: "window",
      heading: "window",
      dense: false,
      cellClassName: "font-mono text-xs text-muted-foreground",
      render: (run) => `${formatDate(run.window_start)} to ${formatDate(run.window_end)}`,
    },
    {
      key: "duration",
      heading: "duration",
      dense: false,
      headClassName: "text-right",
      cellClassName: "text-right font-mono text-muted-foreground",
      render: (run) => formatDuration(run.duration_seconds),
    },
    {
      key: "pages",
      heading: "pages",
      dense: false,
      headClassName: "text-right",
      cellClassName: "text-right font-mono",
      render: (run) => formatTokens(run.pages_fetched),
    },
    {
      key: "results",
      heading: "results",
      dense: false,
      headClassName: "text-right",
      cellClassName: "text-right font-mono",
      render: (run) => formatTokens(run.raw_results),
    },
    {
      key: "id",
      heading: "id",
      dense: false,
      cellClassName: "font-mono text-xs text-muted-foreground",
      render: (run) => `#${run.id}`,
    },
    {
      key: "rows",
      heading: "rows",
      dense: false,
      headClassName: "text-right",
      cellClassName: "text-right font-mono",
      render: (run) => formatTokens(run.rows_upserted),
    },
    {
      key: "error",
      heading: "error",
      dense: true,
      cellClassName: "max-w-md",
      render: (run) =>
        run.error ? (
          <details>
            <summary className="cursor-pointer text-xs text-severity-critical">
              {run.error.split(":")[0]}
            </summary>
            <pre className="mt-1 max-h-48 overflow-auto rounded bg-muted p-2 font-mono text-xs whitespace-pre-wrap text-secondary-foreground">
              {run.error}
            </pre>
            <CopyDetails
              className="mt-2 block"
              details={{
                job: `${endpointLabel(run.endpoint)} (${providerLabel(run.provider)} run #${run.id})`,
                status: run.status,
                message: run.error,
              }}
            />
          </details>
        ) : (
          <span className="text-xs text-muted-foreground">-</span>
        ),
    },
  ];
  if (showProvider) {
    columns.splice(1, 0, {
      key: "provider",
      heading: "provider",
      dense: true,
      render: (run) => <StatusBadge tone="neutral">{providerLabel(run.provider)}</StatusBadge>,
    });
  }
  return columns;
}

/** `showProvider` adds a provider column for lists that mix providers (the `all` scope). */
export function RunsTable({
  runs,
  dense = false,
  showProvider = false,
}: {
  runs: Run[];
  dense?: boolean;
  showProvider?: boolean;
}) {
  const wide = useMinWidth(768);
  const columns = runColumns(showProvider).filter((column) => !dense || column.dense);
  const face = columns.filter((column) => dense || column.dense || column.key === "rows");
  const telemetry = columns.filter((column) => !face.includes(column));
  if (!wide) {
    return (
      <div className="space-y-3">
        {runs.map((run) => {
          return (
            <article key={run.id} className="space-y-2 rounded-lg border border-border bg-card p-3">
              {face.map((column) => (
                <div key={column.key} className="grid grid-cols-[6rem_minmax(0,1fr)] gap-2 text-sm">
                  <div className="text-muted-foreground">{column.heading}</div>
                  <div className="min-w-0 break-words">{column.render(run)}</div>
                </div>
              ))}
              {telemetry.length > 0 ? (
                <details>
                  <summary className="cursor-pointer text-xs text-muted-foreground">
                    Telemetry
                  </summary>
                  <div className="mt-2 space-y-2">
                    {telemetry.map((column) => (
                      <div
                        key={column.key}
                        className="grid grid-cols-[6rem_minmax(0,1fr)] gap-2 text-sm"
                      >
                        <div className="text-muted-foreground">{column.heading}</div>
                        <div className="min-w-0 break-words">{column.render(run)}</div>
                      </div>
                    ))}
                  </div>
                </details>
              ) : null}
            </article>
          );
        })}
      </div>
    );
  }
  return (
    <TableViewport>
      <Table scroll={false}>
        <TableHeader>
          <TableRow>
            {face.map((column) => (
              <TableHead key={column.key} className={column.headClassName}>
                {column.heading}
              </TableHead>
            ))}
            {telemetry.length > 0 ? (
              <TableHead>
                <span className="sr-only">Telemetry</span>
              </TableHead>
            ) : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {runs.map((run) => (
            <TableRow key={run.id}>
              {face.map((column) => (
                <TableCell key={column.key} className={column.cellClassName}>
                  {column.render(run)}
                </TableCell>
              ))}
              {telemetry.length > 0 ? (
                <TableCell>
                  <details>
                    <summary className="cursor-pointer text-xs text-muted-foreground">
                      Telemetry
                    </summary>
                    <dl className="mt-2 space-y-1 text-xs">
                      {telemetry.map((column) => (
                        <div key={column.key} className="flex justify-between gap-3">
                          <dt className="text-muted-foreground">{column.heading}</dt>
                          <dd>{column.render(run)}</dd>
                        </div>
                      ))}
                    </dl>
                  </details>
                </TableCell>
              ) : null}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableViewport>
  );
}
