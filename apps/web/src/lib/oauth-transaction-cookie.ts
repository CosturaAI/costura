import { cookies, headers } from "next/headers";

import { isLocalhost } from "@/lib/session-cookie";

export const GOOGLE_OAUTH_COOKIE = "costura_google_oauth";
export const HOST_GOOGLE_OAUTH_COOKIE = `__Host-${GOOGLE_OAUTH_COOKIE}`;

export type GoogleOAuthTransaction = {
  state: string;
  nonce: string;
  codeVerifier: string;
  next: string;
};

const OAUTH_VALUE = /^[A-Za-z0-9_-]{32,128}$/;

export function parseGoogleOAuthCookie(value: string | undefined): GoogleOAuthTransaction | null {
  if (!value) return null;
  try {
    const parsed = JSON.parse(decodeURIComponent(value)) as Record<string, unknown>;
    if (
      typeof parsed.state !== "string" ||
      typeof parsed.nonce !== "string" ||
      typeof parsed.codeVerifier !== "string" ||
      typeof parsed.next !== "string" ||
      !OAUTH_VALUE.test(parsed.state) ||
      !OAUTH_VALUE.test(parsed.nonce) ||
      !OAUTH_VALUE.test(parsed.codeVerifier)
    ) {
      return null;
    }
    return {
      state: parsed.state,
      nonce: parsed.nonce,
      codeVerifier: parsed.codeVerifier,
      next: parsed.next,
    };
  } catch {
    return null;
  }
}

export async function readGoogleOAuthCookie(): Promise<GoogleOAuthTransaction | null> {
  const store = await cookies();
  return parseGoogleOAuthCookie(
    store.get(HOST_GOOGLE_OAUTH_COOKIE)?.value ?? store.get(GOOGLE_OAUTH_COOKIE)?.value,
  );
}

export async function setGoogleOAuthCookie(
  transaction: GoogleOAuthTransaction,
  expiresAt: string,
): Promise<void> {
  const [store, requestHeaders] = await Promise.all([cookies(), headers()]);
  const host = requestHeaders.get("host");
  store.set({
    name: isLocalhost(host) ? GOOGLE_OAUTH_COOKIE : HOST_GOOGLE_OAUTH_COOKIE,
    value: encodeURIComponent(JSON.stringify(transaction)),
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    secure: !isLocalhost(host),
    expires: new Date(expiresAt),
  });
}

export async function clearGoogleOAuthCookie(): Promise<void> {
  const store = await cookies();
  store.delete(GOOGLE_OAUTH_COOKIE);
  store.delete(HOST_GOOGLE_OAUTH_COOKIE);
}
