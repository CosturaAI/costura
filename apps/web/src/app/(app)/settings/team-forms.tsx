"use client";

import { useActionState } from "react";

import { ConfirmSubmit, Feedback, FieldError, invalid } from "@/components/form-feedback";
import { SubmitButton } from "@/components/submit-button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { idleAction } from "@/lib/action-errors";
import type { Team, TeamMember } from "@/lib/api";
import { memberValue, type MemberOptionGroups } from "@/lib/teams";

import {
  addTeamMemberAction,
  deleteTeamAction,
  removeTeamMemberAction,
  setTeamAction,
} from "./team-actions";

/** Name a new team; its slug is derived from the name. */
export function NewTeamForm() {
  const [state, action, pending] = useActionState(setTeamAction, idleAction);
  return (
    <form action={action} className="flex flex-wrap items-end gap-3">
      <div className="min-w-[16rem] flex-1">
        <label htmlFor="team-name" className="mb-1 block text-sm text-secondary-foreground">
          Team name
        </label>
        <Input
          id="team-name"
          name="name"
          placeholder="Platform"
          maxLength={80}
          aria-invalid={invalid(state, "name") || undefined}
          aria-describedby={invalid(state, "name") ? "team-name-error" : undefined}
        />
        <FieldError state={state} field="name" id="team-name-error" />
      </div>
      <SubmitButton size="lg" pending={pending}>
        {pending ? "Saving..." : "Add team"}
      </SubmitButton>
      <Feedback state={state} />
    </form>
  );
}

/** Map a person, a workspace or a key to the team; one in another team moves here. */
export function AddMemberForm({ team, groups }: { team: Team; groups: MemberOptionGroups }) {
  const [state, action, pending] = useActionState(addTeamMemberAction, idleAction);
  const id = `team-member-${team.slug}`;
  return (
    <form action={action} className="flex flex-wrap items-end gap-3">
      <input type="hidden" name="team" value={team.slug} />
      <div className="min-w-[16rem] flex-1">
        <label htmlFor={id} className="mb-1 block text-sm text-secondary-foreground">
          Add to {team.name}
        </label>
        <NativeSelect
          id={id}
          name="member"
          className="w-full px-3"
          defaultValue=""
          aria-invalid={invalid(state, "member") || undefined}
          aria-describedby={invalid(state, "member") ? `${id}-error` : undefined}
        >
          <option value="" disabled>
            Choose a person, workspace or key
          </option>
          {groups.map((group) => (
            <optgroup key={group.label} label={group.label}>
              {group.options.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </optgroup>
          ))}
        </NativeSelect>
        <FieldError state={state} field="member" id={`${id}-error`} />
      </div>
      <SubmitButton pending={pending}>{pending ? "Adding..." : "Add"}</SubmitButton>
      <Feedback state={state} />
    </form>
  );
}

export function RemoveMemberForm({ team, member }: { team: Team; member: TeamMember }) {
  const [state, action, pending] = useActionState(removeTeamMemberAction, idleAction);
  return (
    <form action={action} className="flex items-center justify-end gap-2">
      <input type="hidden" name="team" value={team.slug} />
      <input type="hidden" name="member" value={memberValue(member)} />
      <Feedback state={state} className="text-xs" />
      <SubmitButton
        variant="ghost"
        size="sm"
        pending={pending}
        aria-label={`Remove ${member.label} from ${team.name}`}
      >
        {pending ? "Removing..." : "Remove"}
      </SubmitButton>
    </form>
  );
}

export function DeleteTeamForm({ team }: { team: Team }) {
  const [state, action, pending] = useActionState(deleteTeamAction, idleAction);
  const formId = `delete-team-${team.slug}`;
  return (
    <form id={formId} action={action} className="flex items-center gap-2">
      <input type="hidden" name="team" value={team.slug} />
      <Feedback state={state} className="text-xs" />
      <ConfirmSubmit
        formId={formId}
        title={`Remove the team ${team.name}?`}
        description="Its mappings and its budgets are deleted; its spend reads (no team)."
        confirmLabel="Remove team"
        pending={pending}
        aria-label={`Remove the team ${team.name}`}
      >
        {pending ? "Removing..." : "Remove team"}
      </ConfirmSubmit>
    </form>
  );
}
