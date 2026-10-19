"use client";

import { useActionState, useState } from "react";

import { SubmitButton } from "@/components/submit-button";
import { Feedback, FieldError, invalid } from "@/components/form-feedback";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { idleAction } from "@/lib/action-errors";
import { useOnSuccess } from "@/lib/use-on-success";
import type { AssignmentKind, Owner } from "@/lib/api";

import { assignOwnerAction, unassignOwnerAction } from "../actions";

/**
 * Under "Who to contact" on a key anomaly: record (or replace, or remove) the person who answers
 * for the key. `current` is the assignment already in force, when the first owner came from
 * one; the form opens collapsed behind a button so the card stays a list of people.
 */
export function AssignOwnerForm({
  provider,
  kind,
  externalId,
  current,
}: {
  provider: string;
  kind: AssignmentKind;
  externalId: string;
  current: Owner | null;
}) {
  const [open, setOpen] = useState(false);
  const [state, action, pending] = useActionState(assignOwnerAction, idleAction);
  useOnSuccess(state, () => setOpen(false));
  const [removeState, removeAction, removing] = useActionState(unassignOwnerAction, idleAction);
  const what = kind === "api_key" ? "key" : "workspace";
  if (!open) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" size="sm" variant="outline" onClick={() => setOpen(true)}>
          {current ? "Change the assigned contact" : "Assign a contact"}
        </Button>
        {current ? (
          <form action={removeAction} className="flex items-center gap-2">
            <input type="hidden" name="provider" value={provider} />
            <input type="hidden" name="kind" value={kind} />
            <input type="hidden" name="external_id" value={externalId} />
            <SubmitButton size="sm" variant="ghost" pending={removing}>
              Remove
            </SubmitButton>
            <Feedback state={removeState} />
          </form>
        ) : (
          <p className="text-xs text-muted-foreground">
            Nobody in the provider inventory answers for this {what}? Record who does; it shows here
            first and on every anomaly of the {what}.
          </p>
        )}
        <Feedback state={state} />
      </div>
    );
  }
  return (
    <form action={action} className="space-y-3">
      <input type="hidden" name="provider" value={provider} />
      <input type="hidden" name="kind" value={kind} />
      <input type="hidden" name="external_id" value={externalId} />
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label
            className="block text-sm font-medium text-secondary-foreground"
            htmlFor="assign_email"
          >
            Contact e-mail
          </label>
          <Input
            id="assign_email"
            name="email"
            type="email"
            required
            defaultValue={current?.email ?? ""}
            placeholder="oncall@example.com"
            className="mt-1"
            aria-invalid={invalid(state, "email") || undefined}
            aria-describedby={invalid(state, "email") ? "assign_email_error" : undefined}
          />
          <FieldError state={state} field="email" id="assign_email_error" />
        </div>
        <div>
          <label
            className="block text-sm font-medium text-secondary-foreground"
            htmlFor="assign_note"
          >
            Note (optional)
          </label>
          <Input
            id="assign_note"
            name="note"
            defaultValue={current?.note ?? ""}
            placeholder="on-call for the gateway"
            className="mt-1"
          />
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <SubmitButton size="sm" pending={pending}>
          Save contact
        </SubmitButton>
        <Button type="button" size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
        <Feedback state={state} />
      </div>
    </form>
  );
}
