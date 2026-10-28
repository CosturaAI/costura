"use server";

import { redirect } from "next/navigation";
import { z } from "zod";

import { describeError, type ActionState } from "@/lib/action-errors";
import { ApiError, api } from "@/lib/api";
import { checkbox, parseForm, text } from "@/lib/form";
import { EVERY_PAGE, SETTINGS_PAGES, refresh, runMutation } from "@/lib/mutations";
import { requireActiveOrg } from "@/lib/view";

/**
 * Server actions behind the organization page: rename and leave.
 * Each returns a plain object the client form renders; nothing throws to the
 * browser. `field` names the input the message belongs to, when there is one.
 */

const Rename = z.object({
  name: text().refine((value) => !!value, "Give the organization a name."),
});

const Leave = z.object({ user_id: z.coerce.number().catch(0) });

const AnomalySettings = z.object({
  sensitivity: z.preprocess(
    (value) => value ?? "normal",
    z.enum(["low", "normal", "high"], { error: "Sensitivity must be low, normal or high." }),
  ),
  retention_days: z.preprocess(
    (value) => value ?? "90",
    z.coerce
      .number({ error: "Retention must be a whole number of days from 30 to 365." })
      .int("Retention must be a whole number of days from 30 to 365.")
      .min(30, "Retention must be a whole number of days from 30 to 365.")
      .max(365, "Retention must be a whole number of days from 30 to 365."),
  ),
  idle_days: z.preprocess(
    (value) => value ?? "30",
    z.coerce
      .number({ error: "Idle must be a whole number of days from 7 to 365." })
      .int("Idle must be a whole number of days from 7 to 365.")
      .min(7, "Idle must be a whole number of days from 7 to 365.")
      .max(365, "Idle must be a whole number of days from 7 to 365."),
  ),
  new_key_days: z.preprocess(
    (value) => value ?? "7",
    z.coerce
      .number({ error: "New must be a whole number of days from 1 to 90." })
      .int("New must be a whole number of days from 1 to 90.")
      .min(1, "New must be a whole number of days from 1 to 90.")
      .max(90, "New must be a whole number of days from 1 to 90."),
  ),
  detect_drops: checkbox(),
  detect_new_principals: checkbox(),
});

/** Owner only. The organization ID stays: it is the slug the API and the links use. */
export async function renameOrganizationAction(
  _prev: ActionState,
  form: FormData,
): Promise<ActionState> {
  const parsed = parseForm(form, Rename, ["name"]);
  if (!parsed.ok) return parsed.error;
  try {
    const org = await requireActiveOrg(form);
    const renamed = await api.renameOrg(org, parsed.data.name);
    refresh(EVERY_PAGE);
    return { ok: true, message: `Renamed to ${renamed.name}.` };
  } catch (error) {
    return {
      ok: false,
      message: describeError(error),
      field: error instanceof ApiError && error.status === 422 ? "name" : undefined,
    };
  }
}

/**
 * Leaving is the same route an owner uses to remove someone, aimed at the caller. The
 * organization disappears from their list, so the browser lands on the landing page, which
 * routes to whatever is left. `redirect` throws and stays outside the try.
 */
export async function leaveOrganizationAction(
  _prev: ActionState,
  form: FormData,
): Promise<ActionState> {
  const parsed = parseForm(form, Leave);
  if (!parsed.ok) return parsed.error;
  try {
    await api.removeMember(await requireActiveOrg(form), parsed.data.user_id);
  } catch (error) {
    return { ok: false, message: describeError(error) };
  }
  refresh(EVERY_PAGE);
  redirect("/");
}

export async function saveAnomalySettingsAction(
  _prev: ActionState,
  form: FormData,
): Promise<ActionState> {
  const parsed = parseForm(form, AnomalySettings, [
    "sensitivity",
    "retention_days",
    "idle_days",
    "new_key_days",
  ]);
  if (!parsed.ok) return parsed.error;
  const {
    sensitivity,
    retention_days,
    idle_days,
    new_key_days,
    detect_drops,
    detect_new_principals,
  } = parsed.data;
  return runMutation(async () => {
    await api.saveAnomalySettings(await requireActiveOrg(form), {
      sensitivity,
      detect_drops,
      detect_new_principals,
      retention_days,
      idle_days,
      new_key_days,
    });
    return "Anomaly detection saved.";
  }, [...SETTINGS_PAGES, ["/anomalies"]]);
}

export async function deleteOrganizationAction(
  _prev: ActionState,
  form: FormData,
): Promise<ActionState> {
  let org: string;
  try {
    org = await requireActiveOrg(form);
  } catch (error) {
    return { ok: false, message: describeError(error) };
  }
  const slug = parseForm(form, z.object({ slug: text() }));
  if (!slug.ok || slug.data.slug !== org) {
    return { ok: false, message: `Type the organization ID (${org}) to confirm.`, field: "slug" };
  }
  try {
    await api.deleteOrganization(org, slug.data.slug);
  } catch (error) {
    return { ok: false, message: describeError(error), field: "slug" };
  }
  refresh(EVERY_PAGE);
  redirect("/");
}
