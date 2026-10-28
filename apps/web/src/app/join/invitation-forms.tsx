"use client";

import { useActionState } from "react";

import { SubmitButton } from "@/components/submit-button";
import { Feedback } from "@/components/form-feedback";
import { idleAction } from "@/lib/action-errors";

import { acceptInvitationAction, claimInvitationAction } from "./actions";

/** Accept one invitation from the list; on success the action redirects into the organization. */
export function AcceptForm({ invitationId, name }: { invitationId: number; name: string }) {
  const [state, action, pending] = useActionState(acceptInvitationAction, idleAction);
  return (
    <form action={action} className="flex flex-wrap items-center gap-3">
      <input type="hidden" name="invitation_id" value={invitationId} />
      <SubmitButton size="lg" pending={pending}>
        {pending ? "Joining..." : `Join ${name}`}
      </SubmitButton>
      <Feedback state={state} />
    </form>
  );
}

/** Accept the invitation a link carries; the token never reaches the API from the browser. */
export function ClaimForm({ token, email }: { token: string; email: string }) {
  const [state, action, pending] = useActionState(claimInvitationAction, idleAction);
  return (
    <form action={action} className="space-y-3">
      <input type="hidden" name="token" value={token} />
      <input type="hidden" name="email" value={email} />
      <SubmitButton size="lg" pending={pending}>
        {pending ? "Joining..." : "Accept invitation"}
      </SubmitButton>
      <Feedback state={state} />
    </form>
  );
}
