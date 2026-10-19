import { CardHeading } from "@/components/card-heading";
import { StatusBadge } from "@/components/status-badge";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { SnoozeGapForm, SnoozedGap } from "@/components/entity/gap-snooze";
import type { ApiKey, Signal, Snooze } from "@/lib/api";
import { formatDate, formatUsd } from "@/lib/format";
import { SIGNAL_KIND_LABELS } from "@/lib/signals";

const OWNER_SOURCES: Record<NonNullable<ApiKey["owner_source"]>, string> = {
  assigned: "assigned in Costura",
  creator: "created the key",
  workspace_admin: "workspace admin",
};

function lastUse(key: ApiKey): string {
  if (!key.last_used_at) return "no use recorded";
  const day = formatDate(key.last_used_at);
  return key.last_used_source === "derived" ? `${day} (from spend, day precision)` : day;
}

function limit(key: ApiKey): string {
  if (!key.limit_reported) return "the provider does not report a per-key limit";
  if (key.spend_limit === null || key.spend_limit === undefined) return "no limit";
  const remaining =
    key.limit_remaining !== null && key.limit_remaining !== undefined
      ? `, ${formatUsd(key.limit_remaining)} left`
      : "";
  const reset = key.limit_reset ? ` (${key.limit_reset})` : "";
  return `${formatUsd(key.spend_limit)} USD${remaining}${reset}`;
}

export function KeyGovernance({
  apiKey,
  signals,
  snoozes = [],
  canSnooze = false,
  consoleUrl,
  consoleLabel,
}: {
  apiKey: ApiKey;
  signals: Signal[] | null;
  /** Gaps of this key a member snoozed. */
  snoozes?: Snooze[];
  /** Snooze controls are left out on the sample organization. */
  canSnooze?: boolean;
  consoleUrl: string | null;
  consoleLabel: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardHeading id="key-governance">Governance</CardHeading>
        <CardDescription>
          {signals === null ? (
            "Gaps could not be loaded; reload to retry."
          ) : signals.length === 0 ? (
            "No open gap: the key has an owner and its limit and use are in order."
          ) : (
            <span className="flex flex-wrap items-center gap-2">
              {signals.map((signal) => (
                <StatusBadge key={signal.kind} tone="warning">
                  {SIGNAL_KIND_LABELS[signal.kind]}
                </StatusBadge>
              ))}
            </span>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[auto_1fr]">
          <dt className="text-muted-foreground">Owner</dt>
          <dd>
            {apiKey.owner
              ? `${apiKey.owner}${apiKey.owner_source ? `, ${OWNER_SOURCES[apiKey.owner_source]}` : ""}`
              : "no owner"}
            {apiKey.creator_left ? "; the creator left the provider organization" : ""}
          </dd>
          <dt className="text-muted-foreground">Last used</dt>
          <dd>{lastUse(apiKey)}</dd>
          <dt className="text-muted-foreground">Spend limit</dt>
          <dd>{limit(apiKey)}</dd>
        </dl>
        {canSnooze && (signals?.length ?? 0) + snoozes.length > 0 ? (
          <div className="mt-4 space-y-2 border-t border-border pt-3">
            {(signals ?? []).map((signal) =>
              signal.kind === "anomaly" ||
              signal.kind === "budget" ||
              signal.kind === "sync_stale" ||
              signal.kind === "webhook_failing" ||
              signal.kind === "model_retiring" ||
              signal.kind === "near_limit" ||
              signal.kind === "unit_cost_up" ||
              signal.kind === "idle_seat" ||
              signal.kind === "seat_no_limit" ? null : (
                <SnoozeGapForm
                  key={signal.kind}
                  provider={signal.provider}
                  keyId={signal.entity_id}
                  kind={signal.kind}
                />
              ),
            )}
            {snoozes.map((snooze) => (
              <SnoozedGap key={snooze.kind} snooze={snooze} />
            ))}
          </div>
        ) : !canSnooze && snoozes.length > 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">
            {snoozes
              .map((s) => `${SIGNAL_KIND_LABELS[s.kind]} snoozed until ${s.until}`)
              .join("; ")}
          </p>
        ) : null}
        {consoleUrl ? (
          <a
            href={consoleUrl}
            target="_blank"
            rel="noreferrer"
            className="mt-3 inline-block text-sm text-primary hover:underline"
          >
            Open the keys in {consoleLabel}
          </a>
        ) : null}
      </CardContent>
    </Card>
  );
}
