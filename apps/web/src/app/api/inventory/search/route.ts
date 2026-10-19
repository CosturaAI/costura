import { forwardedRequestHeaders } from "@/lib/forwarded";
import { readSessionToken } from "@/lib/session-cookie";
import { readViewCookie } from "@/lib/view-cookie";
import { resolveScope } from "@/lib/view";

const LIMIT = /^(?:[1-8])$/;

function privateHeaders(): Headers {
  return new Headers({
    "cache-control": "private, no-store, max-age=0",
    "content-type": "application/json",
    expires: "0",
    pragma: "no-cache",
    "x-content-type-options": "nosniff",
  });
}

/**
 * Same-origin search. The organization and provider come from the view cookie, and the
 * session bearer stays on the server. The browser only sends the literal query.
 */
export async function GET(request: Request): Promise<Response> {
  const [token, view] = await Promise.all([readSessionToken(), readViewCookie()]);
  if (view === null) {
    return Response.json(
      { detail: "no active organization" },
      { status: 404, headers: privateHeaders() },
    );
  }
  const requested = new URL(request.url).searchParams;
  const q = requested.get("q") ?? "";
  if (q.length > 100 || q.trim().length < 2) {
    return Response.json(
      { detail: "q must contain 2 to 100 characters" },
      { status: 400, headers: privateHeaders() },
    );
  }
  const limit = requested.get("limit");
  if (limit !== null && !LIMIT.test(limit)) {
    return Response.json(
      { detail: "limit must be from 1 to 8" },
      { status: 400, headers: privateHeaders() },
    );
  }

  const provider = resolveScope(view.scope);
  const baseUrl = (process.env.COSTURA_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
  const upstreamUrl = new URL(
    `${baseUrl}/api/v1/orgs/${encodeURIComponent(view.org)}/providers/${encodeURIComponent(provider)}/inventory/search`,
  );
  upstreamUrl.searchParams.set("q", q);
  if (limit !== null) upstreamUrl.searchParams.set("limit", limit);
  const upstream = await fetch(upstreamUrl, {
    cache: "no-store",
    headers: await forwardedRequestHeaders(token ? { authorization: `Bearer ${token}` } : {}),
    signal: request.signal,
  });
  return new Response(await upstream.text(), {
    status: upstream.status,
    headers: privateHeaders(),
  });
}
