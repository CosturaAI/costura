"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { ApiError, api } from "@/lib/api";
import { safeNextPath } from "@/lib/return-path";
import { readViewCookie, writeViewCookie } from "@/lib/view-cookie";
import { ALL } from "@/lib/providers";
import {
  autoInterval,
  validRange,
  type QueryInterval,
  type TimeFramePreset,
} from "@/lib/time-range";
import { resolveScope } from "@/lib/view";

/**
 * The scope bar's controls and the account menu write the view cookie instead of navigating.
 * Setting a cookie from a server action makes the router re-render the current
 * page with the new view, so the URL stays as it is.
 */

const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;

/**
 * Merge the patch into the view; anything else in the cookie is kept. A month without dates
 * clears the range, and a range sets the month to the one of its last day.
 */
export async function setViewAction(patch: {
  scope?: string | null;
  month?: string | null;
  from?: string | null;
  to?: string | null;
  interval?: QueryInterval | null;
  timeFrame?: TimeFramePreset | null;
}): Promise<void> {
  const current = await readViewCookie();
  if (current === null) redirect("/");
  let month = patch.month === undefined ? current.month : patch.month;
  const scope = patch.scope === undefined ? current.scope : resolveScope(patch.scope);
  let from = patch.from === undefined ? current.from : patch.from;
  let to = patch.to === undefined ? current.to : patch.to;
  let interval = patch.interval === undefined ? current.interval : patch.interval;
  let timeFrame = patch.timeFrame === undefined ? current.timeFrame : patch.timeFrame;
  if (patch.month !== undefined && patch.from === undefined && patch.to === undefined) {
    from = null;
    to = null;
    interval = null;
    timeFrame = null;
  } else if (validRange(from, to)) {
    const rangeFrom = from!;
    const rangeTo = to!;
    month = rangeTo.slice(0, 7);
    interval = interval ?? autoInterval(rangeFrom, rangeTo);
  } else {
    from = null;
    to = null;
    interval = null;
  }
  await writeViewCookie({
    org: current.org,
    month: month && MONTH.test(month) ? month : null,
    scope,
    from,
    to,
    interval,
    timeFrame: timeFrame ?? null,
  });
  revalidatePath("/", "layout");
}

/**
 * The account menu: open another organization on the same page. The membership is checked
 * like `/o/{slug}` does, so a stale menu entry ends on the 404 page instead of a broken view;
 * the month is dropped because the other organization may not have it, and the scope resets
 * to every provider.
 */
export async function switchOrganizationAction(form: FormData): Promise<void> {
  const slug = String(form.get("slug") ?? "");
  const next = safeNextPath(String(form.get("next") ?? ""), "/overview");
  try {
    await api.org(slug);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) redirect("/o/-missing");
    throw error;
  }
  await writeViewCookie({ org: slug, month: null, scope: ALL });
  revalidatePath("/", "layout");
  redirect(next);
}
