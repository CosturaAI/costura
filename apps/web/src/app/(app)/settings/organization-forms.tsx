"use client";

import { useActionState } from "react";

import { SubmitButton } from "@/components/submit-button";
import { Feedback, FieldError, invalid } from "@/components/form-feedback";
import { Input } from "@/components/ui/input";
import { idleAction } from "@/lib/action-errors";

import { renameOrganizationAction } from "./organization-actions";

/**
 * The display name of the organization. Only the name changes: the slug is the id that the
 * API and every invitation link use, so it is shown next to the form as read-only.
 */
export function RenameOrganizationForm({ name }: { name: string }) {
  const [state, action, pending] = useActionState(renameOrganizationAction, idleAction);
  return (
    <form action={action} className="space-y-3">
      <div className="max-w-sm">
        <label htmlFor="organization-name" className="mb-1 block text-sm text-secondary-foreground">
          Name
        </label>
        <Input
          id="organization-name"
          name="name"
          defaultValue={name}
          maxLength={120}
          autoComplete="organization"
          aria-invalid={invalid(state, "name")}
          aria-describedby="organization-name-error"
        />
        <FieldError state={state} field="name" id="organization-name-error" />
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <SubmitButton size="sm" pending={pending}>
          {pending ? "Saving..." : "Save name"}
        </SubmitButton>
        <Feedback state={state} />
      </div>
    </form>
  );
}
