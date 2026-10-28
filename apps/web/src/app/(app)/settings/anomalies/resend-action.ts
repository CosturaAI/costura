"use server";

import { z } from "zod";

import { describeError, type ActionState } from "@/lib/action-errors";
import { api } from "@/lib/api";
import { parseForm, positiveId } from "@/lib/form";
import { SETTINGS_PAGES, refresh } from "@/lib/mutations";
import { requireActiveOrg } from "@/lib/view";

/**
 * Resend one row of the webhook delivery history. The API renders the signal again as it
 * stands now (payloads are not stored) and answers whether the destination accepted it.
 */

const Resend = z.object({
  delivery_id: positiveId("Pick a delivery to resend."),
});

export async function resendDeliveryAction(
  _prev: ActionState,
  form: FormData,
): Promise<ActionState> {
  const parsed = parseForm(form, Resend);
  if (!parsed.ok) return parsed.error;
  try {
    const org = await requireActiveOrg(form);
    const result = await api.resendWebhookDelivery(org, parsed.data.delivery_id);
    refresh(SETTINGS_PAGES);
    return result.delivered
      ? { ok: true, message: "Posted again." }
      : { ok: false, message: `The webhook did not accept it (${result.error}).` };
  } catch (error) {
    return { ok: false, message: describeError(error) };
  }
}
