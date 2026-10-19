"use client";

import { useActionState } from "react";

import { Feedback } from "@/components/form-feedback";
import { SubmitButton } from "@/components/submit-button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { idleAction } from "@/lib/action-errors";
import type { Snooze } from "@/lib/api";
import { SIGNAL_KIND_LABELS } from "@/lib/signals";

import { liftSnoozeAction, snoozeGapAction } from "@/actions/keys";

type GapKind = Snooze["kind"];

/** Snooze one open gap of a key for 7, 30 or 90 days, with an optional note. */
export function SnoozeGapForm({
  provider,
  keyId,
  kind,
}: {
  provider: string;
  keyId: string;
  kind: GapKind;
}) {
  const [state, action, pending] = useActionState(snoozeGapAction, idleAction);
  const id = `snooze-${kind}`;
  return (
    <form action={action} className="flex flex-wrap items-center gap-2 text-sm">
      <input type="hidden" name="provider" value={provider} />
      <input type="hidden" name="api_key_id" value={keyId} />
      <input type="hidden" name="kind" value={kind} />
      <label htmlFor={`${id}-days`} className="text-muted-foreground">
        Snooze {SIGNAL_KIND_LABELS[kind]} for
      </label>
      <NativeSelect id={`${id}-days`} name="days" defaultValue="30" className="w-24">
        <option value="7">7 days</option>
        <option value="30">30 days</option>
        <option value="90">90 days</option>
      </NativeSelect>
      <label htmlFor={`${id}-note`} className="sr-only">
        Why ({SIGNAL_KIND_LABELS[kind]})
      </label>
      <Input
        id={`${id}-note`}
        name="note"
        placeholder="Why (optional)"
        maxLength={280}
        className="min-w-0 flex-1"
      />
      <SubmitButton size="sm" variant="outline" pending={pending}>
        {pending ? "Snoozing..." : "Snooze"}
      </SubmitButton>
      <Feedback state={state} className="w-full text-xs" />
    </form>
  );
}

/** A snoozed gap: until when, why, and a button that brings it back now. */
export function SnoozedGap({ snooze }: { snooze: Snooze }) {
  const [state, action, pending] = useActionState(liftSnoozeAction, idleAction);
  return (
    <form action={action} className="flex flex-wrap items-center gap-2 text-sm">
      <input type="hidden" name="provider" value={snooze.provider} />
      <input type="hidden" name="api_key_id" value={snooze.key_id} />
      <input type="hidden" name="kind" value={snooze.kind} />
      <span className="text-muted-foreground">
        {SIGNAL_KIND_LABELS[snooze.kind]} snoozed until {snooze.until}
        {snooze.note ? `: ${snooze.note}` : ""}
      </span>
      <SubmitButton size="sm" variant="ghost" pending={pending}>
        {pending ? "Bringing back..." : "Bring back now"}
      </SubmitButton>
      <Feedback state={state} className="w-full text-xs" />
    </form>
  );
}
