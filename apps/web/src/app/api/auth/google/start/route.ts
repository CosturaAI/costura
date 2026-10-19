import { type NextRequest, NextResponse } from "next/server";

import { api } from "@/lib/api";
import { safeNextPath } from "@/lib/return-path";
import { clearGoogleOAuthCookie, setGoogleOAuthCookie } from "@/lib/oauth-transaction-cookie";

export async function GET(request: NextRequest): Promise<NextResponse> {
  const next = safeNextPath(request.nextUrl.searchParams.get("next") ?? "");
  try {
    const started = await api.googleAuthorization();
    await setGoogleOAuthCookie(
      {
        state: started.state,
        nonce: started.nonce,
        codeVerifier: started.code_verifier,
        next,
      },
      started.expires_at,
    );
    return NextResponse.redirect(started.authorization_url);
  } catch {
    await clearGoogleOAuthCookie();
    return NextResponse.redirect(new URL("/sign-in?error=configuration", request.url));
  }
}
