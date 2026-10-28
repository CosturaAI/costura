"use client";

import { useActionState, useState } from "react";

import {
  ConfirmSubmit,
  Feedback,
  FieldError,
  OrgField,
  invalid,
  useRemovalFeedback,
} from "@/components/form-feedback";
import { SubmitButton } from "@/components/submit-button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { idleAction } from "@/lib/action-errors";
import { useOnSuccess } from "@/lib/use-on-success";
import type { Team, TeamMember } from "@/lib/api";
import { memberValue, type MemberOptionGroups } from "@/lib/teams";

import {
  addTeamMemberAction,
  deleteTeamAction,
  removeTeamMemberAction,
  setTeamAction,
} from "./team-actions";

/** Name a new team; its slug is derived from the name. */
export function NewTeamForm({ org }: { org: string }) {
  const [state, action, pending] = useActionState(setTeamAction, idleAction);
  const [name, setName] = useState("");
  useOnSuccess(state, () => setName(""));
  return (
    <form action={action} className="flex flex-wrap items-end gap-3">
      <OrgField org={org} />
      <div className="min-w-[16rem] flex-1">
        <label htmlFor="team-name" className="mb-1 block text-sm text-secondary-foreground">
          Team name
        </label>
        <Input
          id="team-name"
          name="name"
          placeholder="Platform"
          maxLength={80}
          value={name}
          onChange={(event) => setName(event.target.value)}
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
export function AddMemberForm({
  org,
  team,
  groups,
}: {
  org: string;
  team: Team;
  groups: MemberOptionGroups;
}) {
  const [state, action, pending] = useActionState(addTeamMemberAction, idleAction);
  const id = `team-member-${team.slug}`;
  return (
    <form action={action} className="flex flex-wrap items-end gap-3">
      <OrgField org={org} />
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

export function RemoveMemberForm({
  org,
  team,
  member,
}: {
  org: string;
  team: Team;
  member: TeamMember;
}) {
  const [result, action, pending] = useActionState(removeTeamMemberAction, idleAction);
  const state = useRemovalFeedback(result);
  return (
    <form action={action} className="flex items-center justify-end gap-2">
      <OrgField org={org} />
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

export function DeleteTeamForm({ org, team }: { org: string; team: Team }) {
  const [result, action, pending] = useActionState(deleteTeamAction, idleAction);
  const state = useRemovalFeedback(result);
  const formId = `delete-team-${team.slug}`;
  return (
    <form id={formId} action={action} className="flex items-center gap-2">
      <OrgField org={org} />
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
