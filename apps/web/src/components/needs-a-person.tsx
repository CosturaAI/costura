import Link from "next/link";

import { CardHeading } from "@/components/card-heading";
import { StatusBadge } from "@/components/status-badge";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import type { Signals } from "@/lib/api";
import { formatUsd } from "@/lib/format";
import { SIGNAL_KIND_LABELS, SIGNAL_TONES, recurrenceNote, signalHref } from "@/lib/signals";

const TOP = 3;

export function NeedsAPerson({ signals }: { signals: Signals | null }) {
  return (
    <Card>
      <CardHeader>
        <CardHeading id="needs-a-person">Needs a person</CardHeading>
        <CardDescription>
          {signals === null
            ? "Could not be loaded; reload to retry."
            : signals.total === 0
              ? "Nothing needs a person."
              : `${signals.total} open, most money first; open anomalies of any date, this month's budgets and every active key.`}
        </CardDescription>
      </CardHeader>
      {signals && signals.items.length > 0 ? (
        <CardContent>
          <ul aria-labelledby="needs-a-person" className="divide-y divide-border">
            {signals.items.slice(0, TOP).map((signal) => (
              <li
                key={`${signal.kind}:${signal.provider}:${signal.reference}`}
                className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2 text-sm"
              >
                <span className="flex min-w-0 flex-wrap items-baseline gap-2">
                  <StatusBadge tone={SIGNAL_TONES[signal.kind]}>
                    {SIGNAL_KIND_LABELS[signal.kind]}
                  </StatusBadge>
                  <Link
                    href={signalHref(signal)}
                    className="font-medium break-words text-primary hover:underline"
                  >
                    {signal.label}
                  </Link>
                  <span className="text-xs text-muted-foreground">{signal.detail}</span>
                  {recurrenceNote(signal.occurrences) ? (
                    <span className="text-xs font-medium text-severity-warning">
                      {recurrenceNote(signal.occurrences)}
                    </span>
                  ) : null}
                </span>
                <span className="flex items-baseline gap-3 text-xs text-muted-foreground">
                  <span className="font-mono text-foreground">
                    {formatUsd(signal.dollars_at_risk)} {signal.currency}
                  </span>
                  <span>{signal.owner ?? "no owner"}</span>
                </span>
              </li>
            ))}
          </ul>
        </CardContent>
      ) : null}
    </Card>
  );
}
