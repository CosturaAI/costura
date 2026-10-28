import Link from "next/link";

import { CardHeading } from "@/components/card-heading";
import { StatusBadge } from "@/components/status-badge";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import type { MoverRow, Movers } from "@/lib/api";
import { dimensionLabel, entityHref, splitLabel } from "@/lib/dimensions";
import { formatPercent, formatUsd } from "@/lib/format";
import { periodTitle } from "@/lib/time-range";

const SIDE_TOP = 5;

/**
 * What changed against the previous period (the previous month for a calendar month, else the
 * days of the same length before the range), rises and falls side by side. A total that
 * moved says nothing about where to look; the rows that carry the move do. The API
 * ranks by the size of the move in both directions, so the card only splits the list by sign.
 */
export function MoversCard({
  movers,
  period,
  currency = "USD",
}: {
  movers: Movers;
  period: { from: string; to: string };
  currency?: string;
}) {
  const previous = periodTitle(movers.previous_start, movers.previous_end);
  const current = periodTitle(period.from, period.to);
  const up = movers.rows.filter((row) => Number(row.delta) > 0).slice(0, SIDE_TOP);
  const down = movers.rows.filter((row) => Number(row.delta) < 0).slice(0, SIDE_TOP);
  const label = dimensionLabel(movers.dimension);

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div>
          <CardHeading>What changed</CardHeading>
          <CardDescription>
            Each {label}&apos;s spend against {previous}.
          </CardDescription>
        </div>
        <Link
          href={`/explore?by=${movers.dimension}`}
          className="shrink-0 text-sm text-primary hover:underline"
        >
          Analyze
        </Link>
      </CardHeader>
      <CardContent>
        {!movers.allocated ? (
          <p className="text-sm text-muted-foreground">
            {previous} or {current} has no attribution yet, so no {label} can be compared. The
            comparison appears once both periods are imported and attributed.
          </p>
        ) : movers.rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No {label} changed its spend against {previous}.
          </p>
        ) : (
          <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
            <Side
              heading="Spending more"
              rows={up}
              dimension={movers.dimension}
              currency={currency}
            />
            <Side
              heading="Spending less"
              rows={down}
              dimension={movers.dimension}
              currency={currency}
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Side({
  heading,
  rows,
  dimension,
  currency,
}: {
  heading: string;
  rows: MoverRow[];
  dimension: string;
  currency: string;
}) {
  return (
    <div>
      <p className="text-xs font-medium text-secondary-foreground">{heading}</p>
      {rows.length === 0 ? (
        <p className="mt-1 text-sm text-muted-foreground">none</p>
      ) : (
        <ul className="mt-1 divide-y divide-border">
          {rows.map((row) => {
            const href = entityHref(dimension, row.key, null, row.provider);
            const name = splitLabel(row.label).name;
            const delta = Number(row.delta);
            return (
              <li key={`${row.provider ?? "scope"}:${row.key}`} className="py-1.5 text-sm">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="min-w-0 break-words">
                    {href ? (
                      <Link href={href} className="font-medium hover:text-primary">
                        {name}
                      </Link>
                    ) : (
                      <span className="font-medium">{name}</span>
                    )}
                  </span>
                  <span
                    className={
                      delta > 0
                        ? "shrink-0 font-mono text-xs text-severity-critical"
                        : "shrink-0 font-mono text-xs text-severity-success"
                    }
                  >
                    {delta > 0 ? "+" : "-"}
                    {formatUsd(Math.abs(delta))}{" "}
                    <span className="text-muted-foreground">{currency}</span>
                  </span>
                </div>
                <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
                  {row.is_new ? (
                    <StatusBadge tone="warning">new</StatusBadge>
                  ) : row.is_gone ? (
                    <StatusBadge tone="neutral">stopped</StatusBadge>
                  ) : (
                    <span>
                      {formatPercent(row.change_percent)} against {formatUsd(row.previous_amount)}
                    </span>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
