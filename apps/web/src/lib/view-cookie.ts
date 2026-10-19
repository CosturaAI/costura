import { cookies, headers } from "next/headers";

import { validDate, type TimeFramePreset } from "@/lib/time-range";
import { isLocalhost } from "@/lib/session-cookie";

/**
 * The view cookie: which organization, provider scope, dates and interval the pages render, and
 * the month a link without dates opens; none of them is in the URL. Same prefix rule as the
 * session cookie. The month and the scope are hints: `requireView` checks them against the organization's data and
 * falls back to a month with data or to `all`. Missing or malformed, the cookie counts as
 * absent and `/` picks an organization again.
 */
export const VIEW_COOKIE = "costura_view";
export const HOST_VIEW_COOKIE = `__Host-${VIEW_COOKIE}`;

export type ViewCookie = {
  org: string;
  month?: string | null;
  scope?: string | null;
  from?: string | null;
  to?: string | null;
  interval?: "day" | "week" | "month" | null;
  timeFrame?: TimeFramePreset | null;
};

const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;
const SLUG = /^[a-z0-9][a-z0-9-]{1,62}$/;

/** A cookie value into a view, or null when the value is not one this app wrote. */
export function parseViewCookie(value: string | undefined | null): ViewCookie | null {
  if (!value) return null;
  try {
    const parsed: unknown = JSON.parse(value);
    if (typeof parsed !== "object" || parsed === null) return null;
    const { org, month, scope, from, to, interval, timeFrame } = parsed as Record<string, unknown>;
    if (typeof org !== "string" || !SLUG.test(org)) return null;
    const validFrom = typeof from === "string" && validDate(from) ? from : null;
    const validTo = typeof to === "string" && validDate(to) ? to : null;
    const validRange = validFrom !== null && validTo !== null && validFrom <= validTo;
    return {
      org,
      month: typeof month === "string" && MONTH.test(month) ? month : null,
      scope: typeof scope === "string" && /^[a-z0-9_-]{1,32}$/.test(scope) ? scope : null,
      from: validRange ? validFrom : null,
      to: validRange ? validTo : null,
      interval: interval === "day" || interval === "week" || interval === "month" ? interval : null,
      timeFrame: isTimeFramePreset(timeFrame) ? timeFrame : null,
    };
  } catch {
    return null;
  }
}

export async function readViewCookie(): Promise<ViewCookie | null> {
  const store = await cookies();
  return parseViewCookie(store.get(HOST_VIEW_COOKIE)?.value ?? store.get(VIEW_COOKIE)?.value);
}

export function viewCookieName(host: string | null): string {
  return isLocalhost(host) ? VIEW_COOKIE : HOST_VIEW_COOKIE;
}

/** A year: the view outlives the session on purpose, so the next sign-in lands where the
 * last one left off. */
const VIEW_MAX_AGE = 365 * 24 * 60 * 60;

export async function writeViewCookie(view: ViewCookie): Promise<void> {
  const [store, requestHeaders] = await Promise.all([cookies(), headers()]);
  const host = requestHeaders.get("host");
  store.set({
    name: viewCookieName(host),
    value: JSON.stringify({
      org: view.org,
      month: view.month ?? null,
      scope: view.scope ?? null,
      from: view.from ?? null,
      to: view.to ?? null,
      interval: view.interval ?? null,
      timeFrame: view.timeFrame ?? null,
    }),
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    secure: !isLocalhost(host),
    maxAge: VIEW_MAX_AGE,
  });
}

function isTimeFramePreset(value: unknown): value is TimeFramePreset {
  return (
    typeof value === "string" &&
    [
      "this_month",
      "last_month",
      "last_7_days",
      "last_30_days",
      "last_90_days",
      "rolling_7_days",
      "rolling_30_days",
      "rolling_90_days",
      "quarter",
      "ytd",
      "custom",
    ].includes(value)
  );
}

export async function clearViewCookie(): Promise<void> {
  const store = await cookies();
  store.delete(VIEW_COOKIE);
  store.delete(HOST_VIEW_COOKIE);
}
