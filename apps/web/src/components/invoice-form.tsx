"use client";

import { useActionState, useState } from "react";

import { SubmitButton } from "@/components/submit-button";
import { Feedback, FieldError, invalid } from "@/components/form-feedback";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { idleAction } from "@/lib/action-errors";
import { useOnSuccess } from "@/lib/use-on-success";
import type { Invoice } from "@/lib/api";

import { deleteInvoiceAction, setInvoiceAction } from "@/actions/reconcile";

/**
 * Under the invoice check on Reconciliation: type in (or change, or remove) what the provider
 * invoiced one account for one month. Opens collapsed behind a button.
 */
export function InvoiceForm({
  provider,
  accountId,
  month,
  current,
}: {
  provider: string;
  accountId: number;
  month: string;
  current: Invoice | null;
}) {
  const [open, setOpen] = useState(false);
  const [state, action, pending] = useActionState(setInvoiceAction, idleAction);
  useOnSuccess(state, () => setOpen(false));
  const [removeState, removeAction, removing] = useActionState(deleteInvoiceAction, idleAction);
  const hidden = (
    <>
      <input type="hidden" name="provider" value={provider} />
      <input type="hidden" name="account_id" value={accountId} />
      <input type="hidden" name="month" value={month} />
    </>
  );
  if (!open) {
    return (
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <Button type="button" size="sm" variant="outline" onClick={() => setOpen(true)}>
          {current ? "Change the invoice total" : "Enter the invoice total"}
        </Button>
        {current ? (
          <form action={removeAction} className="flex items-center gap-2">
            {hidden}
            <SubmitButton size="sm" variant="ghost" pending={removing}>
              Remove
            </SubmitButton>
            <Feedback state={removeState} />
          </form>
        ) : null}
        <Feedback state={state} />
      </div>
    );
  }
  return (
    <form action={action} className="mt-2 space-y-3">
      {hidden}
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label
            className="block text-sm font-medium text-secondary-foreground"
            htmlFor="invoice_amount"
          >
            Invoice total ({current?.currency ?? "USD"})
          </label>
          <Input
            id="invoice_amount"
            name="amount"
            inputMode="decimal"
            required
            defaultValue={current?.amount ?? ""}
            placeholder="1234.56"
            className="mt-1"
            aria-invalid={invalid(state, "amount") || undefined}
            aria-describedby={invalid(state, "amount") ? "invoice_amount_error" : undefined}
          />
          <FieldError state={state} field="amount" id="invoice_amount_error" />
        </div>
        <div>
          <label
            className="block text-sm font-medium text-secondary-foreground"
            htmlFor="invoice_note"
          >
            Note (optional)
          </label>
          <Input
            id="invoice_note"
            name="note"
            defaultValue={current?.note ?? ""}
            placeholder="includes 8% VAT"
            className="mt-1"
          />
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <SubmitButton size="sm" pending={pending}>
          Save
        </SubmitButton>
        <Button type="button" size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
        <Feedback state={state} />
      </div>
    </form>
  );
}
