import type { Signal, SignalKind } from "@/lib/api";
import { anomalyHref } from "@/lib/anomaly-text";
import { entityHref } from "@/lib/dimensions";
import type { Tone } from "@/lib/ui-types";

export const SIGNAL_KIND_LABELS: Record<SignalKind, string> = {
  anomaly: "anomaly",
  budget: "budget",
  sync_stale: "import stopped",
  webhook_failing: "webhook failing",
  model_retiring: "model retiring",
  near_limit: "near limit",
  idle_seat: "idle seat",
  seat_no_limit: "member without limit",
  unit_cost_up: "cost per token up",
  no_owner: "no owner",
  no_limit: "no limit",
  owner_left: "owner left",
  idle_active: "idle but active",
  new_key: "new key",
};

export const SIGNAL_TONES: Record<SignalKind, Tone> = {
  anomaly: "critical",
  budget: "warning",
  sync_stale: "critical",
  webhook_failing: "critical",
  model_retiring: "warning",
  near_limit: "critical",
  idle_seat: "neutral",
  seat_no_limit: "warning",
  unit_cost_up: "warning",
  no_owner: "warning",
  no_limit: "warning",
  owner_left: "critical",
  idle_active: "neutral",
  new_key: "info",
};

export function signalHref(
  signal: Pick<Signal, "kind" | "reference" | "entity_id"> & Partial<Pick<Signal, "entity_kind">>,
): string {
  if (signal.kind === "anomaly") return anomalyHref(Number(signal.reference));
  if (signal.kind === "budget") return "/budgets";
  if (signal.kind === "sync_stale") return "/settings/connections";
  if (signal.kind === "webhook_failing") return "/settings/anomalies";
  if (signal.kind === "near_limit" && signal.entity_kind === "limit") return "/budgets";
  if (signal.kind === "idle_seat" || signal.kind === "seat_no_limit") {
    return "/inventory?kind=users";
  }
  return entityHref("api_key", signal.entity_id) ?? "/inventory?kind=api-keys";
}

function ordinal(n: number): string {
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) return `${n}th`;
  return `${n}${({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th"}`;
}

/** "3rd time in 90 days" when the same entity's signal opened before; null the first time. */
export function recurrenceNote(occurrences: number): string | null {
  return occurrences >= 2 ? `${ordinal(occurrences)} time in 90 days` : null;
}

/** "3.5 hours" under two days, "4 days" after. */
export function openFor(hours: string): string {
  const value = Number(hours);
  if (value < 48) return `${value} ${value === 1 ? "hour" : "hours"}`;
  return `${Math.round(value / 24)} days`;
}
