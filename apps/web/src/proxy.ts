import { type NextRequest, NextResponse } from "next/server";

import { contentSecurityPolicy, contentSecurityPolicyReportOnly, createNonce } from "@/lib/csp";

/**
 * Every page gets a Content-Security-Policy with a fresh nonce (`lib/csp.ts`). The root
 * layout reads `x-nonce`, which also keeps every page dynamically rendered: a prerendered
 * page would carry no nonce and its scripts would be blocked.
 */
export function proxy(request: NextRequest): NextResponse {
  const nonce = createNonce();
  const production = process.env.NODE_ENV === "production";
  const policy = contentSecurityPolicy(nonce, production);
  const headers = new Headers(request.headers);
  headers.set("x-nonce", nonce);
  headers.set("Content-Security-Policy", policy);
  const response = NextResponse.next({ request: { headers } });
  response.headers.set("Content-Security-Policy", policy);
  response.headers.set(
    "Content-Security-Policy-Report-Only",
    contentSecurityPolicyReportOnly(nonce, production),
  );
  return response;
}

export const config = {
  matcher: ["/((?!_next/|api/|favicon.ico).*)"],
};
