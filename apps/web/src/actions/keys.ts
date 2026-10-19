"use server";

import { z } from "zod";

import { type ActionState } from "@/lib/action-errors";
import { api } from "@/lib/api";
import { emailText, parseForm } from "@/lib/form";
import { PERSON_PAGES, runMutation } from "@/lib/mutations";
import { formScope } from "@/lib/view";

const Key = { api_key_id: z.string({ error: "Unknown key." }).min(1, "Unknown key.") };

const MarkKey = z.object({ ...Key, email: emailText("Enter the person's e-mail.") });

/**
 * Count a key's spend under one person in the person view. The API refuses an address no
 * provider account in the organization carries, so the person row always exists.
 */
export async function markPersonalKeyAction(
  _prev: ActionState,
  form: FormData,
): Promise<ActionState> {
  const { org, provider } = await formScope(form);
  const parsed = parseForm(form, MarkKey, ["email"]);
  if (!parsed.ok) return parsed.error;
  const { api_key_id: apiKeyId, email } = parsed.data;
  return runMutation(async () => {
    const saved = await api.markPersonalKey(org, provider, apiKeyId, email);
    return `This key's spend now counts under ${saved.email}.`;
  }, PERSON_PAGES);
}

export async function unmarkPersonalKeyAction(
  _prev: ActionState,
  form: FormData,
): Promise<ActionState> {
  const { org, provider } = await formScope(form);
  const parsed = parseForm(form, z.object(Key));
  if (!parsed.ok) return parsed.error;
  return runMutation(async () => {
    await api.unmarkPersonalKey(org, provider, parsed.data.api_key_id);
    return "Mark removed; the key counts as a service key again.";
  }, PERSON_PAGES);
}

const SNOOZE_KINDS = [
  "no_owner",
  "no_limit",
  "owner_left",
  "idle_active",
  "new_key",
  "idle_seat",
  "seat_no_limit",
] as const;

const SnoozeGap = z.object({
  ...Key,
  kind: z.enum(SNOOZE_KINDS, { error: "Unknown gap." }),
  days: z.enum(["7", "30", "90"], { error: "Pick 7, 30 or 90 days." }),
  note: z.string().trim().max(280, "Keep the note under 280 characters.").catch(""),
});

const LiftSnooze = z.object({ ...Key, kind: z.enum(SNOOZE_KINDS, { error: "Unknown gap." }) });

/** Snooze one gap of one key: it leaves the queue, the bell and the webhook until the date. */
export async function snoozeGapAction(_prev: ActionState, form: FormData): Promise<ActionState> {
  const { org, provider } = await formScope(form);
  const parsed = parseForm(form, SnoozeGap, ["days", "note"]);
  if (!parsed.ok) return parsed.error;
  const { api_key_id: keyId, kind, days, note } = parsed.data;
  return runMutation(async () => {
    const saved = await api.snoozeGap(org, provider, {
      kind,
      key_id: keyId,
      days: Number(days) as 7 | 30 | 90,
      note: note || null,
    });
    return `Snoozed until ${saved.until}.`;
  });
}

export async function liftSnoozeAction(_prev: ActionState, form: FormData): Promise<ActionState> {
  const { org, provider } = await formScope(form);
  const parsed = parseForm(form, LiftSnooze);
  if (!parsed.ok) return parsed.error;
  return runMutation(async () => {
    await api.liftSnooze(org, provider, parsed.data.kind, parsed.data.api_key_id);
    return "The gap is back in the queue.";
  });
}
