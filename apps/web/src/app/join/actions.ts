"use server";

import { redirect } from "next/navigation";
import { z } from "zod";

import { describeError, type ActionState } from "@/lib/action-errors";
import { ApiError, api } from "@/lib/api";
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

/** The API answers 410 alike for an unknown, revoked, used or expired token and for an
 * address other than the invited one, so the refusal names every case. */
export async function claimInvitationAction(
  _prev: ActionState,
  form: FormData,
): Promise<ActionState> {
  const parsed = parseForm(form, z.object({ token: text(), email: text() }));
  const token = parsed.ok ? parsed.data.token : "";
  const email = parsed.ok ? parsed.data.email : "";
  let slug: string;
  try {
    slug = (await api.claimInvitation(token)).slug;
  } catch (error) {
    if (error instanceof ApiError && error.status === 410) {
      return {
        ok: false,
        message: `This link may not be for ${email || "the address you signed in with"}, or it was revoked or has expired. Sign out and open it again with the invited address, or ask an owner for a new invitation.`,
      };
    }
    return { ok: false, message: describeError(error) };
  }
  return land(slug);
}
