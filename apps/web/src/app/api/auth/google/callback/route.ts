import { type NextRequest, NextResponse } from "next/server";

import { api } from "@/lib/api";
import { safeNextPath } from "@/lib/return-path";
import { clearGoogleOAuthCookie, readGoogleOAuthCookie } from "@/lib/oauth-transaction-cookie";
import { setSessionCookie } from "@/lib/session-cookie";

function signInUrl(request: NextRequest, error: string): URL {
  return new URL(`/sign-in?error=${encodeURIComponent(error)}`, request.url);
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  const transaction = await readGoogleOAuthCookie();
  const state = request.nextUrl.searchParams.get("state");
  const code = request.nextUrl.searchParams.get("code");
  const providerError = request.nextUrl.searchParams.get("error");
  try {
    if (providerError) {
      return NextResponse.redirect(signInUrl(request, "denied"));
    }
    if (!transaction || !state || !code || state !== transaction.state) {
      return NextResponse.redirect(signInUrl(request, "state"));
    }
    const signed = await api.googleCallback({
      code,
      state,
      nonce: transaction.nonce,
      code_verifier: transaction.codeVerifier,
    });
    await setSessionCookie(signed.token, signed.expires_at);
    return NextResponse.redirect(new URL(safeNextPath(transaction.next), request.url));
  } catch {
    return NextResponse.redirect(signInUrl(request, "callback"));
  } finally {
    await clearGoogleOAuthCookie();
  }
}
