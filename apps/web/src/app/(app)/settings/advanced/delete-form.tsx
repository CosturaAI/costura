"use client";

import { useActionState } from "react";

import { SubmitButton } from "@/components/submit-button";
import { Feedback, FieldError, OrgField, invalid } from "@/components/form-feedback";
import { Input } from "@/components/ui/input";
import { idleAction } from "@/lib/action-errors";

import { deleteOrganizationAction } from "../organization-actions";

export function DeleteOrganizationForm({ slug }: { slug: string }) {
  const [state, action, pending] = useActionState(deleteOrganizationAction, idleAction);
  return (
    <form action={action} className="space-y-3">
      <OrgField org={slug} />
      <label htmlFor="delete-org-slug" className="text-sm font-medium text-foreground">
        Type the organization ID <span className="font-mono">{slug}</span> to delete this
        organization
      </label>
      <Input
        id="delete-org-slug"
        name="slug"
        autoComplete="off"
        required
        aria-invalid={invalid(state, "slug") || undefined}
        aria-describedby={invalid(state, "slug") ? "delete-org-slug-error" : undefined}
      />
      <FieldError state={state} field="slug" id="delete-org-slug-error" />
      <SubmitButton variant="destructive" pending={pending}>
        Delete organization
      </SubmitButton>
      <Feedback state={state} />
    </form>
  );
}
