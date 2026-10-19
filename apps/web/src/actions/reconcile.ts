"use server";

import { z } from "zod";

import { type ActionState } from "@/lib/action-errors";
import { api } from "@/lib/api";
import { monthText, parseForm, positiveId, text } from "@/lib/form";
import { RECONCILE_PAGES, runMutation } from "@/lib/mutations";
import { formScope } from "@/lib/view";

const UNKNOWN = "Unknown account or month.";

const Target = {
  account_id: positiveId(UNKNOWN),
  month: monthText(UNKNOWN),
};

const SetInvoice = z.object({
  ...Target,
  amount: text()
    .transform((value) => value.replace(/,/g, ""))
    .refine((value) => /^\d+(\.\d{1,2})?$/.test(value), "Enter the invoice total, like 1234.56."),
  note: text(),
});

/** Record what the provider invoiced one account for one month. Owner only on the API side. */
export async function setInvoiceAction(_prev: ActionState, form: FormData): Promise<ActionState> {
  const { org, provider } = await formScope(form);
  const parsed = parseForm(form, SetInvoice, ["amount"]);
  if (!parsed.ok) return parsed.error;
  const { account_id: accountId, month, amount, note } = parsed.data;
  return runMutation(async () => {
    await api.setInvoice(org, provider, accountId, month, amount, note || null);
    return `Invoice total for ${month} saved.`;
  }, RECONCILE_PAGES);
}

export async function deleteInvoiceAction(
  _prev: ActionState,
  form: FormData,
): Promise<ActionState> {
  const { org, provider } = await formScope(form);
  const parsed = parseForm(form, z.object(Target));
  if (!parsed.ok) return parsed.error;
  const { account_id: accountId, month } = parsed.data;
  return runMutation(async () => {
    await api.deleteInvoice(org, provider, accountId, month);
    return "Invoice total removed.";
  }, RECONCILE_PAGES);
}
