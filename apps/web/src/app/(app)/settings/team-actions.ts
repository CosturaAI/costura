"use server";

import { z } from "zod";

import { type ActionState } from "@/lib/action-errors";
import { api, type TeamMemberKind } from "@/lib/api";
import { parseForm, text } from "@/lib/form";
import { EVERY_PAGE, runMutation } from "@/lib/mutations";
import { teamSlug } from "@/lib/teams";
import { requireActiveOrg } from "@/lib/view";

/** Server actions behind Settings, Teams; see member-actions.ts for the pattern. */

const KINDS = ["person", "api_key", "workspace"] as const satisfies readonly TeamMemberKind[];

const SetTeam = z.object({
  name: text().refine((value) => value.length > 0 && value.length <= 80, "Name the team."),
});

const TeamSlug = z.object({ team: text() });

const Member = z.object({
  team: text(),
  member: z
    .string()
    .catch("")
    .transform((value) => {
      const [kind, provider, ...rest] = value.split("|");
      return { kind, provider, id: rest.join("|") };
    })
    .refine(
      (m): m is { kind: TeamMemberKind; provider: string; id: string } =>
        (KINDS as readonly string[]).includes(m.kind ?? "") && !!m.provider && !!m.id,
      "Choose a person, an API key or a workspace.",
    ),
});

export async function setTeamAction(_prev: ActionState, form: FormData): Promise<ActionState> {
  const org = await requireActiveOrg();
  const parsed = parseForm(form, SetTeam, ["name"]);
  if (!parsed.ok) return parsed.error;
  const slug = teamSlug(parsed.data.name);
  if (!slug) return { ok: false, message: "Use letters or digits in the name.", field: "name" };
  return runMutation(async () => {
    await api.setTeam(org, slug, parsed.data.name);
    return `Team ${parsed.data.name} saved.`;
  }, EVERY_PAGE);
}

export async function deleteTeamAction(_prev: ActionState, form: FormData): Promise<ActionState> {
  const org = await requireActiveOrg();
  const parsed = parseForm(form, TeamSlug);
  if (!parsed.ok) return parsed.error;
  return runMutation(async () => {
    await api.deleteTeam(org, parsed.data.team);
    return "Team removed with its mappings and budgets.";
  }, EVERY_PAGE);
}

export async function addTeamMemberAction(
  _prev: ActionState,
  form: FormData,
): Promise<ActionState> {
  const org = await requireActiveOrg();
  const parsed = parseForm(form, Member, ["member"]);
  if (!parsed.ok) return parsed.error;
  const { team, member } = parsed.data;
  return runMutation(async () => {
    await api.setTeamMember(org, team, member.kind, member.provider, member.id);
    return "Added to the team; spend moves with it.";
  }, EVERY_PAGE);
}

export async function removeTeamMemberAction(
  _prev: ActionState,
  form: FormData,
): Promise<ActionState> {
  const org = await requireActiveOrg();
  const parsed = parseForm(form, Member);
  if (!parsed.ok) return parsed.error;
  const { team, member } = parsed.data;
  return runMutation(async () => {
    await api.deleteTeamMember(org, team, member.kind, member.provider, member.id);
    return "Removed from the team.";
  }, EVERY_PAGE);
}
