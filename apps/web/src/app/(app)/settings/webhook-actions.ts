"use server";

import { z } from "zod";

import { describeError, type ActionState, type WebhookState } from "@/lib/action-errors";
import { api } from "@/lib/api";
import { parseForm } from "@/lib/form";
import { SETTINGS_PAGES, refresh, runMutation } from "@/lib/mutations";
import { requireActiveOrg } from "@/lib/view";

/**
 * Server actions behind the webhook card on Settings, Anomalies: save the URL (the answer
 * carries the signing secret once), post a test message, and remove the destination.
 */

const WebhookUrl = z.object({
  url: z
    .string()
    .trim()
    .catch("")
    .pipe(
      z
        .string()
        .min(1, "Paste the webhook URL first.")
        .max(2048, "The URL is longer than 2048 characters.")
        .startsWith("https://", "The webhook URL must start with https://."),
    ),
});

export async function saveWebhookAction(
  _prev: WebhookState,
  form: FormData,
): Promise<WebhookState> {
  const org = await requireActiveOrg();
  const parsed = parseForm(form, WebhookUrl, ["url"]);
  if (!parsed.ok) return { ...parsed.error, secret: null };
  try {
    const saved = await api.saveWebhook(org, parsed.data.url);
    refresh(SETTINGS_PAGES);
    return {
      ok: true,
      message: `Saved. New signals post to ${saved.host}; the ones open now are not sent.`,
      secret: saved.signing_secret,
    };
  } catch (error) {
    return { ok: false, message: describeError(error), field: "url", secret: null };
  }
}

export async function testWebhookAction(): Promise<ActionState> {
  const org = await requireActiveOrg();
  try {
    const result = await api.testWebhook(org);
    return result.delivered
      ? { ok: true, message: "The test message was delivered." }
      : { ok: false, message: `The webhook did not accept the test message (${result.error}).` };
  } catch (error) {
    return { ok: false, message: describeError(error) };
  }
}

export async function removeWebhookAction(): Promise<ActionState> {
  const org = await requireActiveOrg();
  return runMutation(async () => {
    await api.removeWebhook(org);
    return "The webhook is removed; nothing is sent until one is saved again.";
  }, SETTINGS_PAGES);
}

const Digest = z.object({
  digest: z.enum(["off", "weekly", "monthly"], { error: "Pick off, weekly or monthly." }),
});

export async function setDigestAction(_prev: ActionState, form: FormData): Promise<ActionState> {
  const org = await requireActiveOrg();
  const parsed = parseForm(form, Digest);
  if (!parsed.ok) return parsed.error;
  const { digest } = parsed.data;
  return runMutation(async () => {
    await api.setWebhookDigest(org, digest);
    return digest === "off"
      ? "The digest is off."
      : `A ${digest} digest will be posted ${digest === "weekly" ? "on Mondays" : "on the 2nd"}.`;
  }, SETTINGS_PAGES);
}
