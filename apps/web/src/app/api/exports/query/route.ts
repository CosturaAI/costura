import { readSessionToken } from "@/lib/session-cookie";
import { readViewCookie } from "@/lib/view-cookie";
import { forwardedRequestHeaders } from "@/lib/forwarded";

const QUERY_KEYS = new Set([
  "measure",
  "dimensions",
  "start",
  "end",
  "interval",
  "compare",
  "top",
  "projection",
  "lookback",
  "horizon",
  "f",
  "api_key",
  "account",
  "workspace",
  "model",
  "provider",
  "person",
  "provider_account",
]);
const RESPONSE_HEADERS = ["content-disposition", "content-length", "content-type"] as const;
const DATE = /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/;

function privateHeaders(): Headers {
  return new Headers({
    "cache-control": "private, no-store, max-age=0",
    expires: "0",
    pragma: "no-cache",
    "x-content-type-options": "nosniff",
  });
}

/**
 * CSV download of the range query. The organization is the active one (view cookie); the
 * query string names the measure, dates and filters the link was rendered for, so a download
 * started from a page keeps that page's query even when the view changes meanwhile.
 */
export async function GET(request: Request): Promise<Response> {
  // Without a session the request goes upstream without a bearer: the API serves the public
  // sample organization and answers 401 for every other one.
  const [token, view] = await Promise.all([readSessionToken(), readViewCookie()]);
  if (view === null) {
    return Response.json(
      { detail: "no active organization" },
      { status: 404, headers: privateHeaders() },
    );
  }
  const requested = new URL(request.url).searchParams;
  const start = requested.get("start") ?? "";
  const end = requested.get("end") ?? "";
  if (!DATE.test(start) || !DATE.test(end)) {
    return Response.json(
      { detail: "start and end must be YYYY-MM-DD" },
      { status: 400, headers: privateHeaders() },
    );
  }

  const baseUrl = (process.env.COSTURA_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
  const upstreamUrl = new URL(`${baseUrl}/api/v1/orgs/${encodeURIComponent(view.org)}/query`);
  for (const [key, value] of requested) {
    if (QUERY_KEYS.has(key) && value !== "") {
      if (key === "f") upstreamUrl.searchParams.append(key, value);
      else upstreamUrl.searchParams.set(key, value);
    }
  }
  upstreamUrl.searchParams.set("format", "csv");

  const upstreamHeaders = await forwardedRequestHeaders(
    token ? { authorization: `Bearer ${token}` } : {},
  );
  const upstream = await fetch(upstreamUrl, {
    cache: "no-store",
    headers: upstreamHeaders,
    signal: request.signal,
  });
  const headers = privateHeaders();
  for (const name of RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value !== null) headers.set(name, value);
  }
  return new Response(upstream.body, { status: upstream.status, headers });
}
