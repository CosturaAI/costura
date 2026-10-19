"use server";

import { describeError, type ActionState } from "@/lib/action-errors";
import { api, type Alerts, type SignalRead } from "@/lib/api";
import { checkbox, parseForm } from "@/lib/form";
import { SETTINGS_PAGES, refresh } from "@/lib/mutations";
import { z } from "zod";
import { requireActiveOrg } from "@/lib/view";

/**
 * Server actions behind the inbox (bell and settings switch). They run on the web
 * server so the API stays server-side; the bell polls `getAlertsAction` while opted in.
 */

const signalRead = z.object({
  kind: z.enum([
    "budget",
    "sync_stale",
    "webhook_failing",
    "model_retiring",
    "near_limit",
    "idle_seat",
    "seat_no_limit",
    "unit_cost_up",
    "no_owner",
    "no_limit",
    "owner_left",
    "idle_active",
    "new_key",
  ]),
  provider: z.string().min(1).max(64),
  read_reference: z.string().min(1).max(255),
});

type AlertsResult = { alerts: Alerts; error: null } | { alerts: null; error: string };

export async function getAlertsAction(): Promise<AlertsResult> {
  const org = await requireActiveOrg();
  try {
    return { alerts: await api.alerts(org), error: null };
  } catch (error) {
    return { alerts: null, error: describeError(error) };
  }
}

/** Opt in or out of the inbox for one organization; the form carries `org` and `opted_in`. */
export async function setAlertSettingsAction(
  _prev: ActionState,
  form: FormData,
): Promise<ActionState> {
  const org = await requireActiveOrg();
  if (!org) return { ok: false, message: "Unknown organization." };
  const parsed = parseForm(form, z.object({ opted_in: checkbox() }));
  if (!parsed.ok) return parsed.error;
  const optedIn = parsed.data.opted_in;
  try {
    await api.setAlertSettings(org, optedIn);
    refresh([...SETTINGS_PAGES, ["/", "layout"]]);
    return {
      ok: true,
      message: optedIn
        ? "You will see new anomalies, budget alerts and key gaps of this organization in the bell."
        : "Alerts are off for this organization.",
    };
  } catch (error) {
    return { ok: false, message: describeError(error) };
  }
}

/** Every unread item of the organization becomes read for the caller. */
export async function markAllReadAction(): Promise<AlertsResult> {
  const org = await requireActiveOrg();
  try {
    return { alerts: await api.markAlertsRead(org, { all: true }), error: null };
  } catch (error) {
    return { alerts: null, error: describeError(error) };
  }
}

/**
 * The budget alert or key gap the caller opened from the bell becomes read. Failures are
 * swallowed: the link still navigates, and the item stays unread until the next try.
 */
export async function markSignalReadAction(signal: SignalRead): Promise<void> {
  const parsed = signalRead.safeParse(signal);
  if (!parsed.success) return;
  const org = await requireActiveOrg();
  try {
    await api.markAlertsRead(org, { signals: [parsed.data] });
  } catch {
    return;
  }
}
