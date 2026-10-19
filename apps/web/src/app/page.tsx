import { redirect } from "next/navigation";

import { DEMO_ORG, api, type Organization } from "@/lib/api";
import { readSessionToken } from "@/lib/session-cookie";
import { readViewCookie } from "@/lib/view-cookie";
import { landingHref, openOrgHref } from "@/lib/setup";

const ROLE_ORDER: Record<string, number> = { owner: 0, member: 1, viewer: 2 };

/** Owned organizations first, then memberships, then read-only ones, alphabetical by slug
 * inside each group. */
function homeOrganization(organizations: Organization[]): Organization | null {
  const own = organizations.filter((org) => !org.is_demo && org.role !== null);
  own.sort(
    (a, b) =>
      (ROLE_ORDER[a.role ?? ""] ?? 3) - (ROLE_ORDER[b.role ?? ""] ?? 3) ||
      a.slug.localeCompare(b.slug),
  );
  return own[0] ?? null;
}

/**
 * `/` -> `/sign-in` without a session (`/o/demo` when `COSTURA_PUBLIC_DEMO_HOME=true`), `/join`
 * for someone invited but not yet a member of anything, `/new` without either. With a view
 * cookie naming an organization the caller is still a member of, the welcome page while it has
 * no key, else the overview. Otherwise the first owned organization is opened through
 * `/o/{slug}`, which writes the cookie (a page cannot) and lands the same way.
 */
export default async function Home() {
  if ((await readSessionToken()) === null) {
    redirect(process.env.COSTURA_PUBLIC_DEMO_HOME === "true" ? `/o/${DEMO_ORG}` : "/sign-in");
  }
  const [me, view] = await Promise.all([api.me(), readViewCookie()]);
  const remembered =
    view === null ? null : (me.organizations.find((org) => org.slug === view.org) ?? null);
  if (remembered !== null) {
    const setup = await api.setup(remembered.slug);
    redirect(landingHref(setup));
  }
  const org = homeOrganization(me.organizations);
  // Being invited is the likelier reason to arrive with no organization than wanting to
  // create one, so the invitation comes first.
  if (org === null && me.invitations.length > 0) redirect("/join");
  if (org === null) redirect("/new");
  const setup = await api.setup(org.slug);
  redirect(openOrgHref(org.slug, landingHref(setup)));
}
