"use server";

import { redirect } from "next/navigation";
import { z } from "zod";

import { describeError, type ActionState } from "@/lib/action-errors";
import { api } from "@/lib/api";
import { parseForm, text } from "@/lib/form";
import { EVERY_PAGE, refresh } from "@/lib/mutations";
import { ALL } from "@/lib/providers";
import { writeViewCookie } from "@/lib/view-cookie";
import { landingHref, overviewHref } from "@/lib/setup";

/**
 * Accepting an invitation, from the list or from a link. Both end in the organization: the
 * welcome page while it has no data, the overview once it does, the same rule the landing
 * page follows. `redirect` throws and stays outside the try.
 */
async function land(slug: string): Promise<never> {
  const setup = await api.setup(slug).catch(() => null);
  await writeViewCookie({ org: slug, scope: ALL });
  refresh(EVERY_PAGE);
  redirect(setup ? landingHref(setup) : overviewHref());
}

export async function acceptInvitationAction(
  _prev: ActionState,
  form: FormData,
): Promise<ActionState> {
  const parsed = parseForm(form, z.object({ invitation_id: z.coerce.number().catch(0) }));
  const id = parsed.ok ? parsed.data.invitation_id : 0;
  let slug: string;
  try {
    slug = (await api.acceptInvitation(id)).slug;
  } catch (error) {
    return { ok: false, message: describeError(error) };
  }
  return land(slug);
}

export async function claimInvitationAction(
  _prev: ActionState,
  form: FormData,
): Promise<ActionState> {
  const parsed = parseForm(form, z.object({ token: text() }));
  const token = parsed.ok ? parsed.data.token : "";
  let slug: string;
  try {
    slug = (await api.claimInvitation(token)).slug;
  } catch (error) {
    return { ok: false, message: describeError(error) };
  }
  return land(slug);
}
