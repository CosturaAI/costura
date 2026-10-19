"use client";

import { Bell } from "lucide-react";
import Link from "next/link";
import { useActionState, useCallback, useEffect, useRef, useState } from "react";

import { SubmitButton } from "@/components/submit-button";
import { Feedback } from "@/components/form-feedback";
import { OwnerLine } from "@/components/owners-card";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { idleAction } from "@/lib/action-errors";
import type { AlertItem, Alerts, InboxSignal, SignalKind } from "@/lib/api";
import { SEVERITY_LABEL, SEVERITY_TONE, shareSentence } from "@/lib/anomaly-impact";
import { KIND_LABELS, anomalyHref, episodeSentence, impactAmount } from "@/lib/anomaly-text";
import { splitLabel } from "@/lib/dimensions";
import { formatDayShort, formatUsd } from "@/lib/format";
import { SIGNAL_KIND_LABELS, SIGNAL_TONES, recurrenceNote, signalHref } from "@/lib/signals";
import { cn } from "@/lib/utils";

import {
  getAlertsAction,
  markAllReadAction,
  markSignalReadAction,
  setAlertSettingsAction,
} from "@/actions/alerts";

const POLL_MS = 60_000;
const SHOWN = 10;

const KIND_ORDER: SignalKind[] = [
  "anomaly",
  "sync_stale",
  "webhook_failing",
  "near_limit",
  "budget",
  "model_retiring",
  "unit_cost_up",
  "owner_left",
  "no_owner",
  "no_limit",
  "idle_active",
  "idle_seat",
  "seat_no_limit",
  "new_key",
];

/** "2 anomalies, 1 budget, 3 no owner": the unread count per kind, in queue order. */
export function unreadByKindSentence(unread: Record<string, number>): string {
  return KIND_ORDER.filter((kind) => (unread[kind] ?? 0) > 0)
    .map((kind) => {
      const count = unread[kind];
      if (kind === "anomaly") return `${count} ${count === 1 ? "anomaly" : "anomalies"}`;
      if (kind === "budget") return `${count} ${count === 1 ? "budget" : "budgets"}`;
      return `${count} ${SIGNAL_KIND_LABELS[kind]}`;
    })
    .join(", ");
}

/**
 * Bell in the top bar: the unread count of the caller's inbox for this organization and, on
 * click, the unread anomalies (impact and first owner, each opening its detail page) and the
 * unread budget alerts and key gaps (amount, owner and a link; opening one marks it read).
 * Polls the inbox every minute while opted in and the tab is visible, and once more when the
 * tab comes back. The layout renders it only for a signed-in member outside the sample
 * organization; before the opt-in the panel offers the switch instead of a list.
 */
export function AlertsBell({ initial, canWrite }: { initial: Alerts; canWrite: boolean }) {
  const [alerts, setAlerts] = useState(initial);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const panel = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLDivElement>(null);

  const refresh = useCallback(async () => {
    const result = await getAlertsAction();
    if (result.error !== null) {
      setError(result.error);
      return;
    }
    setError(null);
    setAlerts(result.alerts);
  }, []);

  useEffect(() => {
    if (!alerts.opted_in) return;
    const timer = setInterval(() => {
      if (!document.hidden) void refresh();
    }, POLL_MS);
    const onVisible = () => {
      if (!document.hidden) void refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [alerts.opted_in, refresh]);

  // A dialog takes focus when it opens and gives it back to its button when it closes;
  // otherwise a keyboard user stays on the bell while the panel sits below it.
  const wasOpen = useRef(false);
  useEffect(() => {
    if (open) {
      wasOpen.current = true;
      const first = dialog.current?.querySelector<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), [tabindex="0"]',
      );
      (first ?? dialog.current)?.focus();
      return;
    }
    if (!wasOpen.current) return;
    wasOpen.current = false;
    // A click that landed on a link already moved focus with the navigation; only an
    // orphaned focus (Escape, outside click) comes back to the bell.
    if (document.activeElement === null || document.activeElement === document.body) {
      trigger.current?.focus({ preventScroll: true });
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (panel.current && !panel.current.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  async function markAllRead() {
    const result = await markAllReadAction();
    if (result.error !== null) setError(result.error);
    else setAlerts(result.alerts);
  }

  const unread = alerts.items.filter((item) => item.read_at === null && item.status === "open");
  const unreadSignals = alerts.signals.filter((signal) => signal.read_at === null);
  const label = alerts.unread_count === 0 ? "Alerts" : `Alerts, ${alerts.unread_count} unread`;

  function openSignal(signal: InboxSignal) {
    setOpen(false);
    setAlerts((current) => ({
      ...current,
      unread_count: Math.max(0, current.unread_count - 1),
      unread_by_kind: {
        ...current.unread_by_kind,
        [signal.kind]: Math.max(0, (current.unread_by_kind[signal.kind] ?? 0) - 1),
      },
      signals: current.signals.map((s) =>
        s === signal ? { ...s, read_at: new Date().toISOString() } : s,
      ),
    }));
    void markSignalReadAction({
      kind: signal.kind,
      provider: signal.provider,
      read_reference: signal.read_reference,
    });
  }

  return (
    <div ref={panel} className="relative">
      <button
        ref={trigger}
        type="button"
        aria-label={label}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => {
          setOpen((current) => !current);
          if (!open) void refresh();
        }}
        className="relative inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
      >
        <Bell className="h-4 w-4" aria-hidden />
        {alerts.unread_count > 0 ? (
          <span
            aria-hidden
            className="absolute -top-0.5 -right-0.5 inline-flex min-w-4 items-center justify-center rounded-full bg-severity-critical px-1 font-mono text-[10px] leading-4 font-semibold text-on-solid"
          >
            {alerts.unread_count > 99 ? "99+" : alerts.unread_count}
          </span>
        ) : null}
      </button>
      {open ? (
        <div
          ref={dialog}
          role="dialog"
          aria-label="Alerts"
          tabIndex={-1}
          className="absolute right-0 z-30 mt-2 w-[min(24rem,calc(100vw-2rem))] rounded-lg border border-border bg-card p-3 text-sm shadow-lg outline-none"
        >
          {!alerts.opted_in ? (
            <OptIn optedIn={false} canWrite={canWrite} compact onSaved={() => void refresh()} />
          ) : (
            <>
              <div className="flex items-center justify-between gap-2 pb-2">
                <p className="font-medium text-foreground">
                  {alerts.unread_count === 0
                    ? "Nothing unread"
                    : `${alerts.unread_count} unread: ${unreadByKindSentence(alerts.unread_by_kind)}`}
                </p>
                {alerts.unread_count > 0 && canWrite ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => void markAllRead()}
                  >
                    Mark all read
                  </Button>
                ) : null}
              </div>
              {unread.length === 0 && unreadSignals.length === 0 ? (
                <p className="py-2 text-xs text-muted-foreground">
                  New anomalies, budget alerts and key gaps of this organization appear here as they
                  are found.
                </p>
              ) : (
                <ul className="max-h-80 divide-y divide-border overflow-y-auto">
                  {unread.slice(0, SHOWN).map((item) => (
                    <AlertRow key={item.id} item={item} onOpen={() => setOpen(false)} />
                  ))}
                  {unreadSignals.slice(0, SHOWN).map((signal) => (
                    <SignalRow
                      key={`${signal.kind}:${signal.provider}:${signal.read_reference}`}
                      signal={signal}
                      onOpen={() => openSignal(signal)}
                    />
                  ))}
                </ul>
              )}
              <p className="flex gap-4 pt-2 text-xs">
                <Link href={`/anomalies`} className="text-primary hover:underline">
                  All anomalies
                </Link>
                <Link href={`/overview`} className="text-primary hover:underline">
                  Needs a person
                </Link>
              </p>
            </>
          )}
          {error ? <p className="pt-2 text-xs text-severity-critical">{error}</p> : null}
        </div>
      ) : null}
    </div>
  );
}

function AlertRow({ item, onOpen }: { item: AlertItem; onOpen: () => void }) {
  const severity = item.severity;
  const share = shareSentence(item.impact_share);
  const episode = episodeSentence(item);
  return (
    <li className="space-y-1 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge tone={SEVERITY_TONE[severity]}>{SEVERITY_LABEL[severity]}</StatusBadge>
        <span className="text-xs text-muted-foreground">
          {item.series_kind === "account" ? "Claude Code login" : KIND_LABELS[item.series_kind]}
        </span>
        <Link
          href={anomalyHref(item.id)}
          onClick={onOpen}
          className="min-w-0 font-medium break-words text-primary hover:underline"
          title={item.label}
        >
          {splitLabel(item.label).name}
        </Link>
        <span className="text-xs text-muted-foreground">{formatDayShort(item.day)}</span>
      </div>
      <p className="flex flex-wrap items-baseline gap-x-2">
        <span className="font-mono font-semibold text-foreground">{impactAmount(item)}</span>
        {episode ? <span className="text-xs text-secondary-foreground">{episode}</span> : null}
        {share ? <span className="text-xs text-secondary-foreground">{share}</span> : null}
      </p>
      <OwnerLine owners={item.owners} gap={item.owners_gap} />
    </li>
  );
}

function SignalRow({ signal, onOpen }: { signal: InboxSignal; onOpen: () => void }) {
  return (
    <li className="space-y-1 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge tone={SIGNAL_TONES[signal.kind]}>
          {SIGNAL_KIND_LABELS[signal.kind]}
        </StatusBadge>
        <Link
          href={signalHref(signal)}
          onClick={onOpen}
          className="min-w-0 font-medium break-words text-primary hover:underline"
        >
          {splitLabel(signal.label).name}
        </Link>
      </div>
      <p className="flex flex-wrap items-baseline gap-x-2">
        <span className="font-mono font-semibold text-foreground">
          {formatUsd(signal.dollars_at_risk)} {signal.currency}
        </span>
        <span className="text-xs text-secondary-foreground">{signal.detail}</span>
        {recurrenceNote(signal.occurrences) ? (
          <span className="text-xs font-medium text-severity-warning">
            {recurrenceNote(signal.occurrences)}
          </span>
        ) : null}
      </p>
      <p className="text-xs text-muted-foreground">{signal.owner ?? "no owner"}</p>
    </li>
  );
}

/**
 * The opt-in switch, on the settings page and inside the bell before the opt-in. Posts
 * `opted_in` through a server action; read-only stacks show the state without the button.
 * `onSaved` runs after a successful save so the bell can reload its inbox without a navigation.
 */
export function OptIn({
  optedIn,
  canWrite,
  compact = false,
  className,
  onSaved,
}: {
  optedIn: boolean;
  canWrite: boolean;
  compact?: boolean;
  className?: string;
  onSaved?: () => void;
}) {
  const [state, action, pending] = useActionState(setAlertSettingsAction, idleAction);
  useEffect(() => {
    if (state.ok) onSaved?.();
  }, [state, onSaved]);
  return (
    <form action={action} className={cn("space-y-2", className)}>
      <input type="hidden" name="opted_in" value={optedIn ? "false" : "true"} />
      <p
        className={
          compact ? "text-sm text-secondary-foreground" : "text-sm text-secondary-foreground"
        }
      >
        {optedIn
          ? "You are notified in the bell about every new anomaly, budget alert and key gap of this organization."
          : "Get notified about new anomalies, budget alerts and key gaps in this organization."}
      </p>
      {canWrite ? (
        <SubmitButton
          size="sm"
          variant={optedIn ? "outline" : "default"}
          pending={pending}
          aria-pressed={optedIn}
        >
          {optedIn ? "Turn alerts off" : "Turn alerts on"}
        </SubmitButton>
      ) : (
        <p className="text-xs text-muted-foreground">
          Writes are off on this stack; the setting cannot change here.
        </p>
      )}
      <Feedback state={state} className="text-xs" />
    </form>
  );
}
