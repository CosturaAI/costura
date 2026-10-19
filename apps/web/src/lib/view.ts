import { redirect } from "next/navigation";
import { cache } from "react";

import { ApiError, api, type Organization, type ProviderInfo } from "@/lib/api";
import { ALL, PROVIDERS } from "@/lib/providers";
import { readViewCookie } from "@/lib/view-cookie";
import { currentMonth } from "@/lib/setup";
import {
  autoInterval,
  MAX_RANGE_DAYS,
  monthRange,
  presetRange,
  SAMPLE_MAX_RANGE_DAYS,
  validRange,
  type DateRange,
  type QueryInterval,
  type TimeFramePreset,
} from "@/lib/time-range";

/**
 * The view every page renders: the active organization, the provider scope and the time frame,
 * none of which is in the URL. `requireView` reads the view cookie, checks it
 * against the API and resolves what the cookie only hints at. It is memoised per request, so
 * the layout and the page under it share one round of calls.
 *
 * Resolution: no cookie, an unknown organization or one the caller cannot open -> `/`, which
 * picks an organization again and writes the cookie through `/o/{slug}` (a page cannot set
 * cookies while rendering). The scope is the cookie's when it is `all` or a registered
 * provider, else `all`. The month is the cookie's when the scope has data for it or it is the
 * current month, else the newest month with data, else the current month. A resolved value
 * that differs from the cookie is not written back during render; the next view action does.
 */
export type View = {
  org: string;
  /** `all` or a concrete provider; named `provider` to match the API and the page code. */
  provider: string;
  month: string;
  from: string;
  to: string;
  period: DateRange;
  interval: QueryInterval;
  timeFrame: TimeFramePreset | null;
  organization: Organization;
  registry: ProviderInfo[];
};

type ViewOverrides = {
  from?: string | string[];
  to?: string | string[];
  interval?: string | string[];
  time_frame?: string | string[];
  period?: string | string[];
};

function firstOverride(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export function resolveScope(scope: string | null | undefined): string {
  if (!scope) return ALL;
  return scope === ALL || PROVIDERS.includes(scope) ? scope : ALL;
}

function resolveMonth(
  requested: string | null | undefined,
  months: string[],
  today: string = currentMonth(),
): string {
  if (requested && (months.includes(requested) || requested === today)) return requested;
  return months[0] ?? today;
}

export const requireView = cache(async (overrides: ViewOverrides = {}): Promise<View> => {
  const cookie = await readViewCookie();
  if (cookie === null) redirect("/");
  const provider = resolveScope(cookie.scope);
  let organization: Organization;
  let months: string[];
  let registry: ProviderInfo[];
  try {
    [organization, { months }, registry] = await Promise.all([
      api.org(cookie.org),
      api.months(cookie.org, provider),
      api.providers(cookie.org),
    ]);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) redirect("/");
    throw error;
  }
  const month = resolveMonth(cookie.month, months);
  const inherited = monthRange(month);
  const overrideFrom = firstOverride(overrides.from);
  const overrideTo = firstOverride(overrides.to);
  const overrideTimeFrame = urlTimeFrame(
    firstOverride(overrides.time_frame),
    firstOverride(overrides.period),
  );
  const longest = organization.is_demo ? SAMPLE_MAX_RANGE_DAYS : MAX_RANGE_DAYS;
  const hasOverrideRange = validRange(overrideFrom, overrideTo, longest);
  const hasCookieRange = validRange(cookie.from, cookie.to, longest);
  const semanticRange = overrideTimeFrame
    ? presetRange(overrideTimeFrame)
    : !hasOverrideRange && cookie.timeFrame && cookie.timeFrame !== "custom"
      ? presetRange(cookie.timeFrame)
      : null;
  const from = semanticRange
    ? semanticRange.from
    : hasOverrideRange
      ? overrideFrom!
      : hasCookieRange
        ? cookie.from!
        : inherited.from;
  const to = semanticRange
    ? semanticRange.to
    : hasOverrideRange
      ? overrideTo!
      : hasCookieRange
        ? cookie.to!
        : inherited.to;
  const timeFrame = overrideTimeFrame ?? (semanticRange ? (cookie.timeFrame ?? null) : null);
  const overrideInterval = firstOverride(overrides.interval);
  const interval =
    overrideInterval === "day" || overrideInterval === "week" || overrideInterval === "month"
      ? overrideInterval
      : (cookie.interval ?? autoInterval(from, to));
  return {
    org: cookie.org,
    provider,
    month,
    from,
    to,
    period: { from, to },
    interval,
    timeFrame,
    organization,
    registry,
  };
});

function urlTimeFrame(
  value: string | undefined,
  period: string | undefined,
): TimeFramePreset | null {
  if (value === "last_7_days" || value === "last_30_days" || value === "last_90_days") {
    return period === "rolling" ? (`rolling_${value.slice(5)}` as TimeFramePreset) : value;
  }
  if (value === "this_month" || value === "last_month" || value === "quarter" || value === "ytd") {
    return value;
  }
  return null;
}

type ScopeParams = { org: string; provider: string };

/**
 * The active organization slug alone, for server actions and pollers: no verification,
 * since the API answers 404 or 403 itself for an organization the caller cannot write to.
 */
export async function requireActiveOrg(): Promise<string> {
  const cookie = await readViewCookie();
  if (cookie === null) redirect("/");
  return cookie.org;
}

/** The view a server action posts against: the cookie's organization and hints, unverified. */
async function activeScope(): Promise<ScopeParams> {
  const cookie = await readViewCookie();
  if (cookie === null) redirect("/");
  return { org: cookie.org, provider: resolveScope(cookie.scope) };
}

/**
 * What a server action posted from a form acts on: the active organization, and the provider
 * the form row names (`provider` input; a card under `all` acts on its own provider) or else
 * the view's scope.
 */
export async function formScope(form: FormData): Promise<ScopeParams> {
  const view = await activeScope();
  const provider = String(form.get("provider") ?? "");
  return { org: view.org, provider: provider || view.provider };
}
