/**
 * Receives Content-Security-Policy violation reports (the report-only header from
 * `src/proxy.ts`) and logs one line per report: the directive, the blocked URL's origin and
 * the page path, never query strings. Always 204, so a browser never retries.
 */

import { summarizeCspReport } from "@/lib/csp";

const MAX_BODY = 16_384;

export async function POST(request: Request): Promise<Response> {
  const text = (await request.text()).slice(0, MAX_BODY);
  try {
    const line = summarizeCspReport(JSON.parse(text));
    if (line) console.warn(line);
  } catch {
    return new Response(null, { status: 204 });
  }
  return new Response(null, { status: 204 });
}
