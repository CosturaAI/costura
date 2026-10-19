"use server";

import { z } from "zod";

import { describeError, idleInvite, type ActionState, type InviteState } from "@/lib/action-errors";
import { ApiError, api } from "@/lib/api";
import { parseForm, text } from "@/lib/form";
import { SETTINGS_PAGES, refresh } from "@/lib/mutations";
import { ROLE_LABELS, ROLES, type Role } from "@/lib/roles";
import { requireActiveOrg } from "@/lib/view";

/**
 * Server actions behind the members page: invitations, roles and removal.
 * Each returns a plain object the client form renders; nothing throws to the
 * browser. `field` names the input the message belongs to, when there is one.
 */

const RoleField = z.enum(ROLES as [Role, ...Role[]], { error: "Pick a role." });

const Invite = z.object({
  email: z.string().trim().catch("").pipe(z.string().min(1, "Type the e-mail address first.")),
  role: z.preprocess((value) => value ?? "member", RoleField),
});

const MemberRole = z.object({ user_id: z.coerce.number().catch(0), role: RoleField });

const MemberId = z.object({ user_id: z.coerce.number().catch(0), email: text() });

const InvitationId = z.object({ invitation_id: z.coerce.number().catch(0) });

export async function inviteAction(_prev: InviteState, form: FormData): Promise<InviteState> {
  const org = await requireActiveOrg();
  const parsed = parseForm(form, Invite, ["email"]);
  if (!parsed.ok) return { ...idleInvite, ...parsed.error, url: null, email: null };
  const { email, role } = parsed.data;
  try {
    const invitation = await api.invite(org, email, role);
    refresh(SETTINGS_PAGES);
    return {
      ok: true,
      message: `${invitation.email} is invited as ${ROLE_LABELS[invitation.role].toLowerCase()}.`,
      url: invitation.url ?? null,
      email: invitation.email,
    };
  } catch (error) {
    return {
      ok: false,
      message: describeError(error),
      field: error instanceof ApiError && error.status === 409 ? "email" : undefined,
      url: null,
      email: null,
    };
  }
}

export async function revokeInvitationAction(
  _prev: ActionState,
  form: FormData,
): Promise<ActionState> {
  const org = await requireActiveOrg();
  const id = parseForm(form, InvitationId);
  if (!id.ok) return id.error;
  try {
    await api.revokeInvitation(org, id.data.invitation_id);
    refresh(SETTINGS_PAGES);
    return { ok: true, message: "Invitation revoked; its link no longer works." };
  } catch (error) {
    return { ok: false, message: describeError(error) };
  }
}

export async function setMemberRoleAction(
  _prev: ActionState,
  form: FormData,
): Promise<ActionState> {
  const org = await requireActiveOrg();
  const parsed = parseForm(form, MemberRole);
  if (!parsed.ok) return parsed.error;
  const { user_id: userId, role } = parsed.data;
  try {
    const member = await api.setMemberRole(org, userId, role);
    refresh(SETTINGS_PAGES);
    return {
      ok: true,
      message: `${member.email} is now ${ROLE_LABELS[member.role].toLowerCase()}.`,
    };
  } catch (error) {
    return { ok: false, message: describeError(error) };
  }
}

export async function removeMemberAction(_prev: ActionState, form: FormData): Promise<ActionState> {
  const org = await requireActiveOrg();
  const parsed = parseForm(form, MemberId);
  if (!parsed.ok) return parsed.error;
  const { user_id: userId, email } = parsed.data;
  try {
    await api.removeMember(org, userId);
    refresh(SETTINGS_PAGES);
    return { ok: true, message: `${email} can no longer open this organization.` };
  } catch (error) {
    return { ok: false, message: describeError(error) };
  }
}
