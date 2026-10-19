"use server";

import { redirect } from "next/navigation";
import { z } from "zod";

import { describeError, type ActionState } from "@/lib/action-errors";
import { ApiError, api } from "@/lib/api";
import { parseForm, text } from "@/lib/form";
import { isValidSlug, nextSlug } from "@/lib/org-name";
import { ALL } from "@/lib/providers";
import { writeViewCookie } from "@/lib/view-cookie";
import { welcomeHref } from "@/lib/setup";

/** The form's state after a refused creation; `suggestion` is the next free slug after a 409. */
export type NewOrgState = ActionState & { suggestion: string | null };

/**
 * `POST /orgs`, then the welcome page of the new organization. `redirect` throws and stays
 * outside the try, which only turns API refusals (409 taken, 422 invalid) into form messages.
 */
const NewOrg = z.object({
  name: text().refine((value) => !!value, "Give the organization a name."),
  slug: text().refine(
    isValidSlug,
    "The address needs 2 to 63 lowercase letters, digits or hyphens and cannot start with a hyphen.",
  ),
});

export async function createOrgAction(_prev: NewOrgState, form: FormData): Promise<NewOrgState> {
  const parsed = parseForm(form, NewOrg, ["name", "slug"]);
  if (!parsed.ok) return { ...parsed.error, suggestion: null };
  const { name, slug } = parsed.data;
  try {
    await api.createOrg(name, slug);
  } catch (error) {
    if (error instanceof ApiError && error.status === 409 && /reserved/.test(error.detail)) {
      return {
        ok: false,
        message: `The address /${slug} is reserved on this deployment. Choose another.`,
        field: "slug",
        suggestion: null,
      };
    }
    if (error instanceof ApiError && error.status === 409) {
      return {
        ok: false,
        message: `The address /${slug} is taken.`,
        field: "slug",
        suggestion: nextSlug(slug),
      };
    }
    return {
      ok: false,
      message: describeError(error),
      field: error instanceof ApiError && error.status === 422 ? "slug" : undefined,
      suggestion: null,
    };
  }
  await writeViewCookie({ org: slug, scope: ALL });
  redirect(welcomeHref());
}
