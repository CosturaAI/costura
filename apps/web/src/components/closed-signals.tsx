import { CardHeading } from "@/components/card-heading";
import { StatusBadge } from "@/components/status-badge";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import type { SignalHistory } from "@/lib/api";
import { formatDayShort, formatUsd } from "@/lib/format";
import { SIGNAL_KIND_LABELS, SIGNAL_TONES, openFor } from "@/lib/signals";

const TOP = 10;

/** What closed lately and how long each stayed open, from the worker's signal history. */
export function ClosedSignals({ history }: { history: SignalHistory | null }) {
  const items = history?.items ?? [];
  return (
    <Card>
      <CardHeader>
        <CardHeading id="closed-signals">Closed in the last 90 days</CardHeading>
        <CardDescription>
          {history === null
            ? "Could not be loaded; reload to retry."
            : items.length === 0
              ? "Nothing closed yet. The worker records signals every 15 minutes."
              : "Every signal that needed a person and no longer does, with how long it stayed open."}
        </CardDescription>
      </CardHeader>
      {items.length > 0 ? (
        <CardContent>
          <ul aria-labelledby="closed-signals" className="divide-y divide-border">
            {items.slice(0, TOP).map((item) => (
              <li
                key={`${item.kind}:${item.provider}:${item.entity_id}:${item.closed_at}`}
                className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2 text-sm"
              >
                <span className="flex min-w-0 flex-wrap items-baseline gap-2">
                  <StatusBadge tone={SIGNAL_TONES[item.kind]}>
                    {SIGNAL_KIND_LABELS[item.kind]}
                  </StatusBadge>
                  <span className="font-medium break-words">{item.label}</span>
                  <span className="text-xs text-muted-foreground">{item.detail}</span>
                </span>
                <span className="flex items-baseline gap-3 text-xs text-muted-foreground">
                  <span className="font-mono text-foreground">
                    {formatUsd(item.dollars_at_risk)} {item.currency}
                  </span>
                  <span>
                    closed {formatDayShort(item.closed_at.slice(0, 10))} after{" "}
                    {openFor(item.hours_open)}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </CardContent>
      ) : null}
    </Card>
  );
}
