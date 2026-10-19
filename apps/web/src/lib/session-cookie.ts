import { cookies, headers } from "next/headers";

/**
 * The session cookie the web server keeps for the API bearer token. Server-only: pages read
 * it during rendering, server actions set and clear it (Next.js allows `set` and `delete`
 * only in Server Functions and Route Handlers). The Google callback sets the same cookie.
 *
 * Over HTTPS the cookie carries the `__Host-` prefix: browsers then refuse it unless it is
 * `Secure`, has `Path=/` and no `Domain`, so a subdomain or a plain-http page cannot plant
 * one. The prefix needs `Secure`, which localhost cannot set, so the plain name serves there.
 */

export const SESSION_COOKIE = "costura_session";
export const HOST_SESSION_COOKIE = `__Host-${SESSION_COOKIE}`;

export async function readSessionToken(): Promise<string | null> {
  const [store, requestHeaders] = await Promise.all([cookies(), headers()]);
  const secure = store.get(HOST_SESSION_COOKIE)?.value;
  const value = isLocalhost(requestHeaders.get("host"))
    ? (secure ?? store.get(SESSION_COOKIE)?.value)
    : secure;
  return value ? value : null;
}

/** Browsers drop a `secure` cookie set over plain http, which is how localhost is served. */
export function isLocalhost(host: string | null): boolean {
  return /^(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/i.test(host ?? "");
}

export function sessionCookieName(host: string | null): string {
  return isLocalhost(host) ? SESSION_COOKIE : HOST_SESSION_COOKIE;
}

export async function setSessionCookie(token: string, expiresAt: string): Promise<void> {
  const [store, requestHeaders] = await Promise.all([cookies(), headers()]);
  const host = requestHeaders.get("host");
  const expires = new Date(expiresAt);
  store.set({
    name: sessionCookieName(host),
    value: token,
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    secure: !isLocalhost(host),
    ...(Number.isNaN(expires.getTime()) ? {} : { expires }),
  });
}

export async function clearSessionCookie(): Promise<void> {
  const store = await cookies();
  store.delete(SESSION_COOKIE);
  store.delete(HOST_SESSION_COOKIE);
}
