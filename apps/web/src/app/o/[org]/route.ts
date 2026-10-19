import { ApiError, api } from "@/lib/api";
import { safeNextPath } from "@/lib/return-path";
import { writeViewCookie } from "@/lib/view-cookie";
import { validRange, type TimeFramePreset } from "@/lib/time-range";
import { resolveScope } from "@/lib/view";

const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;
const TIME_FRAMES: readonly string[] = [
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
];
const NO_STORE = { "cache-control": "private, no-store, max-age=0" };
/** Renders the 404 page; see `app/o/-missing/page.tsx`. */
const MISSING_PATH = "/o/-missing";

/** The app router's prefetch header, and the browsers' speculative-load hints. */
function isPrefetch(request: Request): boolean {
  return (
    request.headers.get("next-router-prefetch") !== null ||
    request.headers.get("sec-purpose")?.includes("prefetch") === true ||
    request.headers.get("purpose") === "prefetch"
  );
}

/**
 * Open an organization: `/o/{slug}` is the one address that names one. A member,
 * or anyone on the public sample organization, gets the view cookie written for it and lands
 * on `next` (a path on this origin) or the overview; `?scope=` and `?month=` seed the view
 * when they are valid. `?from=&to=` (with an optional `?time_frame=` preset) carry a
 * time frame across, so a link that changes the scope keeps the dates on screen. An unknown or foreign slug lands on the 404 page.
 */
export async function GET(
  request: Request,
  context: { params: Promise<{ org: string }> },
): Promise<Response> {
  const { org } = await context.params;
  const url = new URL(request.url);
  // Opening is a side effect (the cookie changes the whole view), so a prefetch of a link to
  // this address must not do it. `<Link>`s to `/o/` also carry `prefetch={false}`.
  if (isPrefetch(request)) return new Response(null, { status: 204, headers: NO_STORE });
  try {
    await api.org(org);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return new Response(null, { status: 302, headers: { ...NO_STORE, location: MISSING_PATH } });
    }
    throw error;
  }
  const month = url.searchParams.get("month");
  const scope = url.searchParams.get("scope");
  const from = url.searchParams.get("from");
  const to = url.searchParams.get("to");
  const range = validRange(from, to) ? { from: from!, to: to! } : null;
  const timeFrame = url.searchParams.get("time_frame");
  await writeViewCookie({
    org,
    month: range ? range.to.slice(0, 7) : month && MONTH.test(month) ? month : null,
    scope: scope ? resolveScope(scope) : null,
    ...(range
      ? {
          ...range,
          timeFrame:
            timeFrame && TIME_FRAMES.includes(timeFrame as TimeFramePreset)
              ? (timeFrame as TimeFramePreset)
              : null,
        }
      : {}),
  });
  const next = safeNextPath(url.searchParams.get("next"), "/overview");
  // A relative Location: `request.url` names the host the server listens on, not the one the
  // browser used, and the cookie just written belongs to the latter.
  const headers = new Headers({ ...NO_STORE, location: next });
  return new Response(null, { status: 302, headers });
}
