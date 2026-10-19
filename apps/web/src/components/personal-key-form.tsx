"use client";

import { useActionState, useState } from "react";

import { SubmitButton } from "@/components/submit-button";
import { Feedback, FieldError, invalid } from "@/components/form-feedback";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { idleAction } from "@/lib/action-errors";
import { useOnSuccess } from "@/lib/use-on-success";

import { markPersonalKeyAction, unmarkPersonalKeyAction } from "@/actions/keys";

/**
 * On an API key page: count the key's spend under one person, or remove that mark. Opens
 * collapsed behind a button; `marked` is the e-mail already in force, when a member set one.
 */
export function PersonalKeyForm({
  provider,
  apiKeyId,
  marked,
}: {
  provider: string;
  apiKeyId: string;
  marked: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [state, action, pending] = useActionState(markPersonalKeyAction, idleAction);
  useOnSuccess(state, () => setOpen(false));
  const [removeState, removeAction, removing] = useActionState(unmarkPersonalKeyAction, idleAction);
  if (!open) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" size="sm" variant="outline" onClick={() => setOpen(true)}>
          {marked ? "Change the person" : "Mark as one person's key"}
        </Button>
        {marked ? (
          <form action={removeAction} className="flex items-center gap-2">
            <input type="hidden" name="provider" value={provider} />
            <input type="hidden" name="api_key_id" value={apiKeyId} />
            <SubmitButton size="sm" variant="ghost" pending={removing}>
              Remove mark
            </SubmitButton>
            <Feedback state={removeState} />
          </form>
        ) : (
          <p className="text-xs text-muted-foreground">
            Only one person uses this key? Its spend then counts under them in the person view.
          </p>
        )}
        <Feedback state={state} />
      </div>
    );
  }
  return (
    <form action={action} className="space-y-3">
      <input type="hidden" name="provider" value={provider} />
      <input type="hidden" name="api_key_id" value={apiKeyId} />
      <div className="max-w-sm">
        <label
          className="block text-sm font-medium text-secondary-foreground"
          htmlFor="personal_key_email"
        >
          Person e-mail
        </label>
        <Input
          id="personal_key_email"
          name="email"
          type="email"
          required
          defaultValue={marked ?? ""}
          placeholder="you@example.com"
          className="mt-1"
          aria-invalid={invalid(state, "email") || undefined}
          aria-describedby={invalid(state, "email") ? "personal_key_email_error" : undefined}
        />
        <FieldError state={state} field="email" id="personal_key_email_error" />
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
