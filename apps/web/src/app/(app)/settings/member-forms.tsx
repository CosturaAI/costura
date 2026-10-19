"use client";

import { useActionState } from "react";

import { SubmitButton } from "@/components/submit-button";
import { CopyButton } from "@/components/copy-button";
import { ConfirmSubmit, Feedback, FieldError, invalid } from "@/components/form-feedback";
import { NativeSelect } from "@/components/ui/native-select";
import { Input } from "@/components/ui/input";
import { idleAction, idleInvite } from "@/lib/action-errors";
import type { Member } from "@/lib/api";
import { ROLE_DESCRIPTIONS, ROLE_LABELS, ROLES } from "@/lib/roles";

import {
  inviteAction,
  removeMemberAction,
  revokeInvitationAction,
  setMemberRoleAction,
} from "./member-actions";
import { leaveOrganizationAction } from "./organization-actions";

/**
 * The owner-only controls of the Members section and the "Leave organization" button of the
 * Account section. Every one of them posts to a server action, so the API token
 * stays on the web server and a refusal comes back as a sentence next to the control.
 */

/** Role picker shared by the invite card and each member row. */
function RoleOptions() {
  return (
    <>
      {ROLES.map((role) => (
        <option key={role} value={role}>
          {ROLE_LABELS[role]}
        </option>
      ))}
    </>
  );
}

/**
 * Invite by e-mail. Nothing is sent: the answer carries a link bound to that address, which
 * the owner copies into whatever channel they already use.
 */
export function InviteForm({ org }: { org: string }) {
  const [state, action, pending] = useActionState(inviteAction, idleInvite);
  return (
    <form action={action} className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-[16rem] flex-1">
          <label
            htmlFor={`invite-email-${org}`}
            className="mb-1 block text-sm text-secondary-foreground"
          >
            E-mail
          </label>
          <Input
            id={`invite-email-${org}`}
            name="email"
            type="email"
            autoComplete="off"
            placeholder="person@example.com"
            aria-invalid={invalid(state, "email")}
            aria-describedby={`invite-email-error-${org}`}
          />
          <FieldError state={state} field="email" id={`invite-email-error-${org}`} />
        </div>
        <div>
          <label
            htmlFor={`invite-role-${org}`}
            className="mb-1 block text-sm text-secondary-foreground"
          >
            Role
          </label>
          <NativeSelect id={`invite-role-${org}`} name="role" defaultValue="member">
            <RoleOptions />
          </NativeSelect>
        </div>
        <SubmitButton size="lg" pending={pending}>
          {pending ? "Inviting..." : "Invite"}
        </SubmitButton>
      </div>
      <details className="text-xs text-muted-foreground">
        <summary className="cursor-pointer font-medium text-secondary-foreground">
          What each role can do
        </summary>
        <dl className="mt-2 space-y-1">
          {ROLES.map((role) => (
            <div key={role} className="flex gap-2">
              <dt className="w-16 shrink-0 font-medium text-secondary-foreground">
                {ROLE_LABELS[role]}
              </dt>
              <dd>{ROLE_DESCRIPTIONS[role]}</dd>
            </div>
          ))}
        </dl>
      </details>
      {state.ok && state.url ? (
        <div className="space-y-2 rounded-lg border border-severity-success/30 bg-severity-success-bg p-3">
          <p className="text-sm text-foreground">{state.message}</p>
          <div className="flex flex-wrap items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded bg-card px-2 py-1 font-mono text-xs">
              {state.url}
            </code>
            <CopyButton value={state.url} label="Copy the invitation link" />
          </div>
          <p className="text-xs text-muted-foreground">
            This link is shown once. Expires in 14 days, and only {state.email} can use it.
          </p>
        </div>
      ) : (
        <Feedback state={state} />
      )}
    </form>
  );
}

/** Role of one member, submitted on change; the last owner's own select is disabled. */
export function MemberRoleForm({ member, lastOwner }: { member: Member; lastOwner: boolean }) {
  const [state, action, pending] = useActionState(setMemberRoleAction, idleAction);
  return (
    <form action={action} className="flex flex-wrap items-center gap-2">
      <input type="hidden" name="user_id" value={member.id} />
      <label htmlFor={`role-${member.id}`} className="sr-only">
        Role of {member.email}
      </label>
      <NativeSelect
        id={`role-${member.id}`}
        name="role"
        defaultValue={member.role}
        disabled={lastOwner}
        aria-disabled={pending || undefined}
        aria-describedby={lastOwner ? `role-${member.id}-note` : undefined}
        onChange={(event) => {
          if (!pending) event.currentTarget.form?.requestSubmit();
        }}
      >
        <RoleOptions />
      </NativeSelect>
      {lastOwner ? (
        <span id={`role-${member.id}-note`} className="sr-only">
          The last owner keeps the role
        </span>
      ) : null}
      <Feedback state={state} className="text-xs" />
    </form>
  );
}

export function RemoveMemberForm({ member, lastOwner }: { member: Member; lastOwner: boolean }) {
  const [state, action, pending] = useActionState(removeMemberAction, idleAction);
  const formId = `remove-member-${member.id}`;
  return (
    <form id={formId} action={action} className="flex flex-wrap items-center gap-2">
      <input type="hidden" name="user_id" value={member.id} />
      <input type="hidden" name="email" value={member.email} />
      <ConfirmSubmit
        formId={formId}
        title={`Remove ${member.email}?`}
        description="They lose access to this organization at once. Their account, their other organizations and the anomalies they triaged stay as they are; an owner can invite them again."
        confirmLabel="Remove"
        variant="ghost"
        pending={pending}
        disabled={lastOwner}
      >
        {pending ? "Removing..." : "Remove"}
      </ConfirmSubmit>
      <Feedback state={state} className="text-xs" />
    </form>
  );
}

export function RevokeInvitationForm({
  invitationId,
  email,
}: {
  invitationId: number;
  email: string;
}) {
  const [state, action, pending] = useActionState(revokeInvitationAction, idleAction);
  const formId = `revoke-invitation-${invitationId}`;
  return (
    <form id={formId} action={action} className="flex flex-wrap items-center gap-2">
      <input type="hidden" name="invitation_id" value={invitationId} />
      <ConfirmSubmit
        formId={formId}
        title={`Revoke the invitation to ${email}?`}
        description="The link stops working. You can invite the same address again afterwards."
        confirmLabel="Revoke"
        variant="ghost"
        pending={pending}
      >
        {pending ? "Revoking..." : "Revoke"}
      </ConfirmSubmit>
      <Feedback state={state} className="text-xs" />
    </form>
  );
}

/** Account section: give up your own membership. Hidden for a last owner. */
export function LeaveOrganizationForm({
  org,
  name,
  userId,
}: {
  org: string;
  name: string;
  userId: number;
}) {
  const [state, action, pending] = useActionState(leaveOrganizationAction, idleAction);
  const formId = `leave-organization-${org}`;
  return (
    <form id={formId} action={action} className="flex flex-wrap items-center gap-3">
      <input type="hidden" name="user_id" value={userId} />
      <ConfirmSubmit
        formId={formId}
        title={`Leave ${name}?`}
        description="You lose access to this organization's spend, keys and settings. An owner can invite you back."
        confirmLabel="Leave"
        variant="outline"
        size="lg"
        pending={pending}
      >
        {pending ? "Leaving..." : "Leave organization"}
      </ConfirmSubmit>
      <Feedback state={state} />
    </form>
  );
}
