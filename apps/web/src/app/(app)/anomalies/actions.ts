"use server";

import { z } from "zod";

import { describeError, type ActionState } from "@/lib/action-errors";
import { api, type AnomalyStatus, type AssignmentKind } from "@/lib/api";
import { emailText, parseForm, positiveId, text } from "@/lib/form";
import { ANOMALY_PAGES, refresh } from "@/lib/mutations";
import { formScope, requireActiveOrg } from "@/lib/view";

/**
 * Server actions behind the acknowledge / ignore / reopen buttons. They run on the web server,
 * so the PATCH reaches the API from the web server.
 */

type StatusState = ActionState;

const STATUSES = ["open", "acknowledged", "ignored"] as const satisfies readonly AnomalyStatus[];
const ASSIGNMENT_KINDS = ["api_key", "workspace"] as const satisfies readonly AssignmentKind[];

const SetStatus = z.object({
  id: positiveId("Unknown anomaly or status."),
  status: z.enum(STATUSES, { error: "Unknown anomaly or status." }),
  reason: z.string().trim().max(280, "Keep the reason under 280 characters.").catch(""),
});

const BulkStatus = z.object({
  status: z.enum(STATUSES, { error: "Unknown status." }),
  ids: z
    .union([z.string(), z.array(z.string())])
    .catch([])
    .transform((value) =>
      (Array.isArray(value) ? value : [value]).map(Number).filter((id) => Number.isInteger(id)),
    )
    .refine((ids) => ids.length > 0, "Select at least one anomaly."),
});

const Target = {
  kind: z.enum(ASSIGNMENT_KINDS, { error: "Unknown key or workspace." }),
  external_id: z.string({ error: "Unknown key or workspace." }).min(1, "Unknown key or workspace."),
};

const AssignOwner = z.object({
  ...Target,
  email: emailText("Enter the contact's e-mail."),
  note: text(),
});

export async function setStatusAction(_prev: StatusState, form: FormData): Promise<StatusState> {
  const { org, provider } = await formScope(form);
  const parsed = parseForm(form, SetStatus);
  if (!parsed.ok) return parsed.error;
  const { id, status, reason } = parsed.data;
  try {
    await api.setAnomalyStatus(org, provider, id, status, reason || null);
    refresh(ANOMALY_PAGES);
    return { ok: true, message: `Marked ${status}.` };
  } catch (error) {
    return { ok: false, message: describeError(error) };
  }
}

/**
 * Marks anomalies read in the caller's inbox (`POST /orgs/{org}/alerts/read`). Failures are
 * swallowed: a visitor without an opt-in, the sample organization (403) or a stack with
 * writes off must not break the page that called it.
 */
export async function markReadAction(ids: number[]): Promise<void> {
  const valid = ids.filter((id) => Number.isInteger(id));
  if (valid.length === 0) return;
  const org = await requireActiveOrg();
  try {
    await api.markAlertsRead(org, { ids: valid });
  } catch {
    return;
  }
}

/**
 * Record who answers for the flagged key (or its workspace) when the inventory names nobody or
 * the wrong person. Any member may; the anomaly pages then list this contact first.
 */
export async function assignOwnerAction(_prev: ActionState, form: FormData): Promise<ActionState> {
  const { org, provider } = await formScope(form);
  const parsed = parseForm(form, AssignOwner, ["email"]);
  if (!parsed.ok) return parsed.error;
  const { kind, external_id: externalId, email, note } = parsed.data;
  try {
    const saved = await api.assignOwner(org, provider, kind, externalId, email, note || null);
    refresh(ANOMALY_PAGES);
    return {
      ok: true,
      message: `${saved.email} now answers for this ${kind === "api_key" ? "key" : "workspace"}.`,
    };
  } catch (error) {
    return { ok: false, message: describeError(error) };
  }
}

export async function unassignOwnerAction(
  _prev: ActionState,
  form: FormData,
): Promise<ActionState> {
  const { org, provider } = await formScope(form);
  const parsed = parseForm(form, z.object(Target));
  if (!parsed.ok) return parsed.error;
  const { kind, external_id: externalId } = parsed.data;
  try {
    await api.unassignOwner(org, provider, kind, externalId);
    refresh(ANOMALY_PAGES);
    return { ok: true, message: "Assigned contact removed; the inventory decides again." };
  } catch (error) {
    return { ok: false, message: describeError(error) };
  }
}

/** Same transition for every selected anomaly; one PATCH each, stops at the first refusal. */
export async function bulkStatusAction(_prev: StatusState, form: FormData): Promise<StatusState> {
  const { org, provider } = await formScope(form);
  const parsed = parseForm(form, BulkStatus);
  if (!parsed.ok) return parsed.error;
  const { status, ids } = parsed.data;
  let done = 0;
  try {
    for (const id of ids) {
      await api.setAnomalyStatus(org, provider, id, status);
      done += 1;
    }
    refresh(ANOMALY_PAGES);
    return { ok: true, message: `${done} marked ${status}.` };
  } catch (error) {
    if (done > 0) refresh(ANOMALY_PAGES);
    return {
      ok: false,
      message: `${done} of ${ids.length} marked ${status}; then: ${describeError(error)}`,
    };
  }
}
