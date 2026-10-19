/**
 * Content-Security-Policy for one page response. `src/proxy.ts` sends it with a fresh
 * nonce per request; Next.js reads the nonce back from the request header and puts it on
 * its own scripts, so no inline script runs without it.
 *
 * 'strict-dynamic' lets a nonced script load the chunks it imports.
 * style-src keeps 'unsafe-inline': Tailwind sets style attributes and the Recharts theme
 * injects a <style> block (components/ui/chart.tsx). A style cannot run script.
 * 'unsafe-eval' is added only outside production so the dev server's React refresh can run.
 */
export function contentSecurityPolicy(nonce: string, production: boolean): string {
  const script = [
    "'self'",
    `'nonce-${nonce}'`,
    "'strict-dynamic'",
    ...(production ? [] : ["'unsafe-eval'"]),
  ];
  return [
    "default-src 'self'",
    `script-src ${script.join(" ")}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    "connect-src 'self'",
    "frame-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
    ...(production ? ["upgrade-insecure-requests"] : []),
  ].join("; ");
}

/** Where browsers post violation reports (`src/app/api/csp-report/route.ts`). */
const CSP_REPORT_PATH = "/api/csp-report";

/**
 * The same policy in report-only form with a report target. The enforced header stays
 * without one; this copy only makes a blocked script visible in the web server's log.
 */
export function contentSecurityPolicyReportOnly(nonce: string, production: boolean): string {
  return `${contentSecurityPolicy(nonce, production)}; report-uri ${CSP_REPORT_PATH}`;
}

/** 128 random bits, base64. */
export function createNonce(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return btoa(String.fromCharCode(...bytes));
}

type CspReport = Record<string, unknown>;

function origin(value: unknown): string {
  if (typeof value !== "string" || value.length === 0) return "-";
  try {
    return new URL(value).origin;
  } catch {
    return value.slice(0, 40);
  }
}

function pathOf(value: unknown): string {
  if (typeof value !== "string") return "-";
  try {
    return new URL(value).pathname;
  } catch {
    return "-";
  }
}

/** One log line for a violation report: directive, blocked origin, page path; no queries. */
export function summarizeCspReport(body: unknown): string | null {
  const report = (body as { "csp-report"?: CspReport } | null)?.["csp-report"];
  if (!report || typeof report !== "object") return null;
  const directive = report["effective-directive"] ?? report["violated-directive"] ?? "-";
  return `csp violation ${String(directive)} blocked ${origin(report["blocked-uri"])} on ${pathOf(
    report["document-uri"],
  )}`;
}
