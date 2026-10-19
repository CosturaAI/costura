import { readFileSync } from "node:fs";
import { join } from "node:path";

import type { NextConfig } from "next";

/** The release in `apps/web/package.json`, bumped by release-please with `version.txt`; the
 * error panels put it in "Copy details". */
const { version } = JSON.parse(readFileSync(join(process.cwd(), "package.json"), "utf8")) as {
  version: string;
};

/**
 * Response headers on every route. The Content-Security-Policy carries a per-request
 * nonce, so `src/proxy.ts` sets it instead (`src/lib/csp.ts`).
 * HSTS only in production: a browser that saw it on localhost would refuse plain http there.
 */
const securityHeaders = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  { key: "X-DNS-Prefetch-Control", value: "off" },
  { key: "X-Permitted-Cross-Domain-Policies", value: "none" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  { key: "Cross-Origin-Resource-Policy", value: "same-origin" },
  ...(process.env.NODE_ENV === "production"
    ? [{ key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" }]
    : []),
];

const nextConfig: NextConfig = {
  poweredByHeader: false,
  // The production image runs `node server.js` from this build (apps/web/Dockerfile).
  output: "standalone",
  env: { NEXT_PUBLIC_COSTURA_VERSION: version },
  async headers() {
    return [{ source: "/(.*)", headers: securityHeaders }];
  },
};

export default nextConfig;
