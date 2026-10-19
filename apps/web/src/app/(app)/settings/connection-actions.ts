"use server";

import { redirect } from "next/navigation";
import { z } from "zod";

import { describeError, type ActionState } from "@/lib/action-errors";
import { ApiError, api, type SyncResult } from "@/lib/api";
import { connectFailure, connectedMessage } from "@/lib/connect";
import { checkbox, parseForm, text } from "@/lib/form";
import { EVERY_PAGE, RECONCILE_PAGES, SETTINGS_PAGES, refresh } from "@/lib/mutations";
import { providerLabel } from "@/lib/providers";
import { welcomeHref } from "@/lib/setup";
import { formScope, requireActiveOrg } from "@/lib/view";

/**
 * Server actions behind the connection forms: connect, accounts, credit prices, reset and
 * sync now. The admin key travels browser -> web server -> API over the local stack, so
 * `COSTURA_API_URL` stays server-side.
 * Each returns a plain object the client form renders; nothing throws to the
 * browser. `field` names the input the message belongs to, when there is one.
 */

/** One `SyncResult` per provider the POST covered; several under `all`. The API answers 202
 * with queued runs; the form polls `setup` through running to a terminal state. */
export type SyncState = { ok: boolean; message: string | null; results: SyncResult[] };

const SEAT_PRICE_MESSAGE = "Seat price must be a non-negative USD amount.";

/** Optional `account_id` field of the account forms; NaN and blanks read as absent. */
const accountField = () =>
  text().transform((raw) => {
    if (!raw) return undefined;
    const id = Number(raw);
    return Number.isInteger(id) && id > 0 ? id : undefined;
  });

/** Cursor's billing settings, present only when the form carries a seat price. */
const seatFields = {
  seat_price_usd: z.string().trim().optional(),
  include_included_in_business: checkbox(),
};

function cursorSettings(
  provider: string,
  seatPrice: string | undefined,
  includeIncluded: boolean,
): { seat_price_usd: string; include_included_in_business: boolean } | null | undefined {
  if (provider !== "cursor" || seatPrice === undefined) return undefined;
  const amount = Number(seatPrice);
  if (!seatPrice || !Number.isFinite(amount) || amount < 0) return null;
  return { seat_price_usd: seatPrice, include_included_in_business: includeIncluded };
}

const AccountOnly = z.object({ account_id: accountField() });

function connectSchema(provider: string) {
  return z
    .object({
      admin_key: text(),
      key_prefix: text(),
      key_label: text().transform((value) => value || "admin key"),
      mode: text().transform((value) => value || "connect"),
      label: text(),
      account_id: accountField(),
      workspace_id: text(),
      ...seatFields,
    })
    .superRefine((value, ctx) => {
      if (!value.admin_key) {
        ctx.addIssue({
          code: "custom",
          path: ["admin_key"],
          message: `Paste the ${value.key_label} first.`,
        });
        return;
      }
      if (value.mode !== "replace" && !value.workspace_id) {
        const message =
          provider === "codex"
            ? "Paste the Codex workspace ID first."
            : provider === "copilot"
              ? "Enter the GitHub organization first."
              : null;
        if (message) {
          ctx.addIssue({ code: "custom", path: ["workspace_id"], message });
          return;
        }
      }
      if (
        cursorSettings(provider, value.seat_price_usd, value.include_included_in_business) === null
      ) {
        ctx.addIssue({ code: "custom", path: ["seat_price_usd"], message: SEAT_PRICE_MESSAGE });
        return;
      }
      const key = value.admin_key;
      const prefixMatches =
        !value.key_prefix ||
        key.startsWith(value.key_prefix) ||
        (provider === "cursor" && (key.startsWith("crsr_") || key.startsWith("key_"))) ||
        (provider === "claude_ai" && key.startsWith("sk-ant-admin"));
      if (!prefixMatches) {
        const expected =
          provider === "cursor"
            ? "crsr_ (or legacy key_)"
            : provider === "claude_ai"
              ? "sk-ant-api01- (or sk-ant-admin)"
              : value.key_prefix;
        ctx.addIssue({
          code: "custom",
          path: ["admin_key"],
          message: `${providerLabel(provider)} ${value.key_label}s start with ${expected}; this looks like a different kind of key.`,
        });
        return;
      }
      if (value.mode === "replace" && value.account_id === undefined) {
        ctx.addIssue({
          code: "custom",
          path: ["mode"],
          message: "Choose the account whose key to replace.",
        });
      }
    });
}

const CreditPrice = z.object({
  account_id: accountField().refine((id) => id !== undefined, "Choose the Codex account."),
  effective_from: text().refine((value) => {
    const parsed = new Date(`${value}T00:00:00Z`);
    return (
      /^\d{4}-\d{2}-\d{2}$/.test(value) &&
      !Number.isNaN(parsed.getTime()) &&
      parsed.toISOString().slice(0, 10) === value
    );
  }, "Choose the date this credit rate starts."),
  price_per_credit: text().refine(
    (value) => !!value && Number.isFinite(Number(value)) && Number(value) > 0,
    "Credit price must be a positive USD amount.",
  ),
});

const DeleteCreditPrice = z.object({
  account_id: accountField().refine((id) => id !== undefined, "Credit rate not found."),
  price_id: z.coerce
    .number({ error: "Credit rate not found." })
    .int("Credit rate not found.")
    .min(1, "Credit rate not found."),
});

const RenameAccount = z.object({
  account_id: accountField().refine((id) => id !== undefined, "Choose the account to rename."),
  label: text().refine((value) => !!value, "Give the account a name."),
  ...seatFields,
});

const RemoveAccount = z.object({
  account_id: accountField().refine((id) => id !== undefined, "Choose the account to remove."),
});

/**
 * The form carries the registry prefix of its provider so the check needs no provider table.
 * Three writes share the field: `mode=connect` puts the provider's only key,
 * `mode=add` connects one more account (with an optional `label`), `mode=replace` swaps the
 * key of `account_id`. A label the API refuses (blank, too long, taken) lands on its field.
 */
export async function connectAction(_prev: ActionState, form: FormData): Promise<ActionState> {
  const { org, provider } = await formScope(form);
  const parsed = parseForm(form, connectSchema(provider), [
    "admin_key",
    "workspace_id",
    "seat_price_usd",
  ]);
  if (!parsed.ok) return parsed.error;
  const {
    admin_key: key,
    key_label: keyLabel,
    mode,
    label: accountLabel,
    account_id: account,
    workspace_id: workspaceId,
  } = parsed.data;
  // The schema refused a malformed seat price, so only "absent" or a value is left.
  const settings =
    cursorSettings(
      provider,
      parsed.data.seat_price_usd,
      parsed.data.include_included_in_business,
    ) ?? undefined;
  const label = providerLabel(provider);
  const connectionSettings =
    provider === "codex" || provider === "copilot"
      ? { workspace_id: workspaceId || undefined }
      : settings;
  try {
    // A key aimed at one account (replace, or connect on an account the environment fills)
    // goes to that account; "add" opens a new one; a bare connect takes the provider route.
    const result =
      account !== undefined && mode !== "add"
        ? await api.replaceAccountKey(org, provider, account, key)
        : mode === "add"
          ? await api.addAccount(org, provider, key, accountLabel, connectionSettings)
          : connectionSettings === undefined
            ? await api.connect(org, provider, key)
            : await api.connect(org, provider, key, connectionSettings);
    refresh(EVERY_PAGE);
    return { ok: true, message: connectedMessage(label, keyLabel, result) };
  } catch (error) {
    const labelProblem =
      error instanceof ApiError && error.status === 422 && /label/i.test(error.detail);
    return {
      ok: false,
      message: connectFailure(error, label, keyLabel),
      field: labelProblem
        ? "label"
        : error instanceof ApiError && error.status === 422 && /workspace_id/i.test(error.detail)
          ? "workspace_id"
          : error instanceof ApiError && error.status === 422
            ? "admin_key"
            : undefined,
    };
  }
}

export async function addCreditPriceAction(
  _prev: ActionState,
  form: FormData,
): Promise<ActionState> {
  const org = await requireActiveOrg();
  const parsed = parseForm(form, CreditPrice, ["effective_from", "price_per_credit"]);
  if (!parsed.ok) return parsed.error;
  const {
    account_id: account,
    effective_from: effectiveFrom,
    price_per_credit: price,
  } = parsed.data;
  try {
    await api.addCreditPrice(org, account as number, {
      effective_from: effectiveFrom,
      price_per_credit: price,
    });
    refresh([...SETTINGS_PAGES, ...RECONCILE_PAGES]);
    return { ok: true, message: "Credit rate added." };
  } catch (error) {
    const detail = error instanceof ApiError ? error.detail : "";
    return {
      ok: false,
      message: describeError(error),
      field: /effective_from|date/i.test(detail) ? "effective_from" : "price_per_credit",
    };
  }
}

export async function deleteCreditPriceAction(
  _prev: ActionState,
  form: FormData,
): Promise<ActionState> {
  const org = await requireActiveOrg();
  const parsed = parseForm(form, DeleteCreditPrice);
  if (!parsed.ok) return parsed.error;
  const { account_id: account, price_id: priceId } = parsed.data;
  try {
    await api.deleteCreditPrice(org, account as number, priceId);
    refresh([...SETTINGS_PAGES, ...RECONCILE_PAGES]);
    return { ok: true, message: "Credit rate deleted." };
  } catch (error) {
    return { ok: false, message: describeError(error) };
  }
}

/** Forgets the key of `account_id`, or of the provider's only account without it. */
export async function disconnectAction(_prev: ActionState, form: FormData): Promise<ActionState> {
  const { org, provider } = await formScope(form);
  const parsed = parseForm(form, AccountOnly);
  if (!parsed.ok) return parsed.error;
  const account = parsed.data.account_id;
  try {
    if (account === undefined) await api.disconnect(org, provider);
    else await api.disconnectAccount(org, provider, account);
    refresh(EVERY_PAGE);
    return { ok: true, message: "Stored key removed." };
  } catch (error) {
    return { ok: false, message: describeError(error) };
  }
}

export async function renameAccountAction(
  _prev: ActionState,
  form: FormData,
): Promise<ActionState> {
  const { org, provider } = await formScope(form);
  const parsed = parseForm(form, RenameAccount, ["label"]);
  if (!parsed.ok) return parsed.error;
  const { account_id: account, label } = parsed.data;
  const settings = cursorSettings(
    provider,
    parsed.data.seat_price_usd,
    parsed.data.include_included_in_business,
  );
  if (settings === null) {
    return { ok: false, message: SEAT_PRICE_MESSAGE, field: "seat_price_usd" };
  }
  try {
    const renamed = await api.renameAccount(org, provider, account as number, label, settings);
    refresh(EVERY_PAGE);
    return {
      ok: true,
      message: settings === undefined ? `Renamed to ${renamed.label}.` : "Billing settings saved.",
    };
  } catch (error) {
    return {
      ok: false,
      message: describeError(error),
      field: error instanceof ApiError && error.status === 422 ? "label" : undefined,
    };
  }
}

/** Removes the account and every row synced under it; the API answers 409 while it syncs. */
export async function removeAccountAction(
  _prev: ActionState,
  form: FormData,
): Promise<ActionState> {
  const { org, provider } = await formScope(form);
  const parsed = parseForm(form, RemoveAccount);
  if (!parsed.ok) return parsed.error;
  try {
    await api.removeAccount(org, provider, parsed.data.account_id as number);
    refresh(EVERY_PAGE);
    return { ok: true, message: "Account removed with its synced data." };
  } catch (error) {
    return { ok: false, message: describeError(error) };
  }
}

/** "Sync started." for one provider; "Sync started for Anthropic and OpenRouter." for several;
 * a skipped entry carries the API's reason instead. */
function syncMessage(results: SyncResult[]): string {
  const started = results.filter((r) => r.status === "queued" || r.status === "running");
  const skipped = results.filter((r) => r.status === "skipped");
  const parts: string[] = [];
  if (started.length === 1 && results.length === 1) parts.push("Sync started.");
  else if (started.length > 0) {
    parts.push(`Sync started for ${started.map((r) => providerLabel(r.provider)).join(" and ")}.`);
  }
  for (const result of skipped) {
    const reason = result.error ?? "Nothing to sync.";
    parts.push(results.length > 1 ? `${providerLabel(result.provider)}: ${reason}` : reason);
  }
  return parts.join(" ") || "Nothing to sync.";
}

/**
 * Starts the organization over: `POST .../setup/reset` drops the stored keys and every synced
 * row, then the browser lands on the welcome page. `redirect` throws on purpose and must stay
 * outside the try, which only turns API refusals into the form's message.
 */
export async function resetSetupAction(): Promise<ActionState> {
  const org = await requireActiveOrg();
  try {
    await api.resetSetup(org);
  } catch (error) {
    return { ok: false, message: describeError(error) };
  }
  refresh(EVERY_PAGE);
  redirect(welcomeHref());
}

export async function syncNowAction(_prev: SyncState, form: FormData): Promise<SyncState> {
  const { org, provider } = await formScope(form);
  const parsed = parseForm(form, AccountOnly);
  const account = parsed.ok ? parsed.data.account_id : undefined;
  try {
    const { results } = await api.syncNow(org, provider, account);
    refresh([...SETTINGS_PAGES, ["/runs"]]);
    return {
      ok: results.some((r) => r.status === "queued" || r.status === "running"),
      message: syncMessage(results),
      results,
    };
  } catch (error) {
    return { ok: false, message: describeError(error), results: [] };
  }
}
