/**
 * Server-only transport to the Costura API (`/api/v1`): the session bearer, query encoding,
 * request deduplication per render and the 401 detour to `/sign-in`.
 */

import { redirect } from "next/navigation";
import { cache } from "react";

import { ApiError } from "@/lib/api-error";
import { forwardedRequestHeaders } from "@/lib/forwarded";
import { appendUsageFilters } from "@/lib/query-export";
import { readSessionToken } from "@/lib/session-cookie";

import type { UsageFilters } from "./spend";

function baseUrl(): string {
  return (process.env.COSTURA_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
}

const cachedGet = cache(
  async (url: string, auth: boolean, unauthorized: "redirect" | "throw"): Promise<unknown> =>
    request(new URL(url), { cache: "no-store" }, { auth, unauthorized }),
);

export async function get<T>(
  path: string,
  query?:
    URLSearchParams | Record<string, string | number | boolean | readonly string[] | undefined>,
  options: RequestOptions = {},
): Promise<T> {
  const url = new URL(`${baseUrl()}/api/v1${path}`);
  if (query instanceof URLSearchParams) {
    for (const [key, value] of query) url.searchParams.append(key, value);
  } else {
    for (const [key, value] of Object.entries(query ?? {})) {
      if (Array.isArray(value)) {
        for (const item of value) {
          if (item !== "") url.searchParams.append(key, item);
        }
      } else if (value !== undefined && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return cachedGet(
    url.toString(),
    options.auth !== false,
    options.unauthorized ?? "redirect",
  ) as Promise<T>;
}

export function withFilters(
  query: Record<string, string | number | boolean | undefined>,
  filters: UsageFilters = {},
): URLSearchParams {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  appendUsageFilters(params, filters);
  return params;
}

/** Write helper for the guarded routes; the API answers 403 outside a local stack. */
export async function send<T>(
  method: "PUT" | "POST" | "DELETE" | "PATCH",
  path: string,
  body?: unknown,
  options: RequestOptions = {},
): Promise<T> {
  const url = new URL(`${baseUrl()}/api/v1${path}`);
  return request<T>(
    url,
    {
      method,
      cache: "no-store",
      headers: body === undefined ? undefined : { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    },
    options,
  );
}

type RequestOptions = {
  /** `false` for the sign-in call, the one route that runs before a session exists. */
  auth?: boolean;
  /** `throw` where a 401 is an answer, not a detour: the sign-in page and the sign-out action. */
  unauthorized?: "redirect" | "throw";
};

/**
 * Every call carries the session cookie's token as a bearer. A 401 means no session or an
 * expired one, so the wrapper sends the browser to `/sign-in` with `redirect`, which throws a
 * control-flow error Next.js handles in pages and server actions alike; `describeError` in
 * `lib/action-errors.ts` rethrows it out of the actions' catch blocks.
 */
async function request<T>(url: URL, init: RequestInit, options: RequestOptions = {}): Promise<T> {
  const path = url.pathname.replace(/^\/api\/v1/, "");
  const headers = await forwardedRequestHeaders(init.headers);
  if (options.auth !== false) {
    const token = await readSessionToken();
    if (token) headers.set("authorization", `Bearer ${token}`);
  }
  const response = await fetch(url, { ...init, headers });
  if (response.status === 401 && options.unauthorized !== "throw") redirect("/sign-in");
  if (!response.ok) {
    let detail = response.statusText;
    let code: string | null = null;
    try {
      const body = (await response.json()) as { detail?: unknown; code?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
      else if (body.detail !== undefined) detail = JSON.stringify(body.detail);
      if (typeof body.code === "string") code = body.code;
    } catch {
      // body was not JSON; keep the status text
    }
    throw new ApiError(response.status, path, detail, response.headers.get("retry-after"), code);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export type Period = string | { from: string; to: string };

export function periodPath(period: Period): string {
  return typeof period === "string" ? period : period.to.slice(0, 7);
}

export function periodQuery(period: Period): { start?: string; end?: string } {
  return typeof period === "string" ? {} : { start: period.from, end: period.to };
}

export const scope = (org: string, provider: string) =>
  `/orgs/${encodeURIComponent(org)}/providers/${encodeURIComponent(provider)}`;
