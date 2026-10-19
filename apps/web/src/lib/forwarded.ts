import { headers } from "next/headers";

/**
 * Copy the browser address and request id from the incoming request onto a call to the API.
 * The API trusts only the Compose subnet, so this header is the client address behind Caddy.
 * Outside a request (a unit test, a script) the headers stay as given.
 */
export async function forwardedRequestHeaders(base?: HeadersInit): Promise<Headers> {
  const out = new Headers(base);
  try {
    const incoming = await headers();
    const forwarded = incoming.get("x-forwarded-for");
    const requestId = incoming.get("x-request-id");
    if (forwarded) out.set("x-forwarded-for", forwarded);
    if (requestId) out.set("x-request-id", requestId);
  } catch {
    // `headers()` throws when there is no incoming request.
  }
  return out;
}
