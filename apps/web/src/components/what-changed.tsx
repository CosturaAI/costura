import Link from "next/link";

import { CardHeading } from "@/components/card-heading";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import type { MoverRow, Movers } from "@/lib/api";
import { entityHref, splitLabel } from "@/lib/dimensions";
import { formatDelta, formatUsd } from "@/lib/format";
import { periodTitle } from "@/lib/time-range";

const TOP = 3;

export function moverSentence(row: MoverRow, previous: string, currency: string): string {
  const delta = Number(row.delta);
  if (row.is_new) return `is new: ${formatUsd(row.amount)} ${currency}, nothing in ${previous}.`;
  if (row.is_gone) {
    return `stopped: ${formatUsd(row.previous_amount)} ${currency} in ${previous}, none now.`;
  }
  return `${delta > 0 ? "rose" : "fell"} ${formatUsd(Math.abs(delta))} ${currency} (${formatDelta(row.change_percent) ?? "-"}) against ${previous}.`;
}

export function WhatChanged({
  movers,
  currency = "USD",
}: {
  movers: Movers | null;
  currency?: string;
}) {
  if (movers === null || !movers.allocated || movers.rows.length === 0) return null;
  const previous = periodTitle(movers.previous_start, movers.previous_end);
  const rows = [...movers.rows]
    .sort((a, b) => Math.abs(Number(b.delta)) - Math.abs(Number(a.delta)))
    .slice(0, TOP);
  return (
    <Card>
      <CardHeader>
        <CardHeading id="largest-moves">Largest moves</CardHeading>
        <CardDescription>The three largest moves against {previous}.</CardDescription>
      </CardHeader>
      <CardContent>
        <ul aria-labelledby="largest-moves" className="space-y-1 text-sm">
          {rows.map((row) => {
            const href = entityHref(movers.dimension, row.key);
            const name = splitLabel(row.label).name;
            return (
              <li key={`${row.provider ?? "scope"}:${row.key}`}>
                {href ? (
                  <Link href={href} className="font-medium text-primary hover:underline">
                    {name}
                  </Link>
                ) : (
                  <span className="font-medium">{name}</span>
                )}{" "}
                {moverSentence(row, previous, currency)}
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}
