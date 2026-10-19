import Link from "next/link";

import { EmptyState } from "@/components/empty-state";
import { StatusBadge } from "@/components/status-badge";
import type { Signal, Signals } from "@/lib/api";
import { formatUsd } from "@/lib/format";
import { providerLabel } from "@/lib/providers";
import { SIGNAL_KIND_LABELS, signalHref } from "@/lib/signals";

type KeyGaps = { first: Signal; kinds: Signal["kind"][] };

const POSTURE_KINDS = new Set<Signal["kind"]>([
  "no_owner",
  "no_limit",
  "owner_left",
  "idle_active",
  "new_key",
]);

function byKey(signals: Signal[]): KeyGaps[] {
  const keys = new Map<string, KeyGaps>();
  for (const signal of signals) {
    if (!POSTURE_KINDS.has(signal.kind)) continue;
    const id = `${signal.provider}:${signal.entity_id}`;
    const found = keys.get(id);
    if (found) found.kinds.push(signal.kind);
    else keys.set(id, { first: signal, kinds: [signal.kind] });
  }
  return [...keys.values()];
}

export function PostureList({
  signals,
  showProvider,
}: {
  signals: Signals | null;
  showProvider: boolean;
}) {
  if (signals === null)
    return <EmptyState message="Posture could not be loaded; reload to retry." />;
  const rows = byKey(signals.items);
  if (rows.length === 0) {
    return (
      <EmptyState message="Every active key has an owner, and its limit and use are in order." />
    );
  }
  return (
    <table className="w-full text-sm">
      <caption className="sr-only">Keys with a governance gap</caption>
      <thead>
        <tr className="border-b border-border text-left text-xs text-muted-foreground">
          <th scope="col" className="px-2 py-2 font-medium">
            Key
          </th>
          <th scope="col" className="px-2 py-2 font-medium">
            Gaps
          </th>
          <th scope="col" className="px-2 py-2 text-right font-medium">
            Last 30 days
          </th>
          <th scope="col" className="px-2 py-2 font-medium">
            Owner
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map(({ first, kinds }) => (
          <tr key={`${first.provider}:${first.entity_id}`} className="border-b border-border">
            <td className="px-2 py-2">
              <Link href={signalHref(first)} className="font-medium text-primary hover:underline">
                {first.label}
              </Link>
              {showProvider ? (
                <span className="ml-2 text-xs text-muted-foreground">
                  {providerLabel(first.provider)}
                </span>
              ) : null}
            </td>
            <td className="px-2 py-2">
              <span className="flex flex-wrap gap-1">
                {kinds.map((kind) => (
                  <StatusBadge key={kind} tone="warning">
                    {SIGNAL_KIND_LABELS[kind]}
                  </StatusBadge>
                ))}
              </span>
            </td>
            <td className="px-2 py-2 text-right font-mono">
              {formatUsd(first.dollars_at_risk)} {first.currency}
            </td>
            <td className="px-2 py-2">{first.owner ?? "no owner"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
