/**
 * Where a redirect may land. The sign-in a join link asks for and the Google
 * round trip carry the target in a query parameter or a cookie, so they check it here: only a
 * path on this origin is followed, never an absolute or protocol-relative URL.
 */

const BASE = "http://costura.invalid";

/** A path on this origin, query string kept, or `fallback` when the input points elsewhere. */
export function safeNextPath(candidate: string | null | undefined, fallback = "/"): string {
  if (!candidate || !candidate.startsWith("/") || candidate.startsWith("//")) return fallback;
  if (candidate.includes("\\") || /[\u0000-\u001f\u007f]/.test(candidate)) return fallback;
  let resolved: URL;
  try {
    resolved = new URL(candidate, BASE);
  } catch {
    return fallback;
  }
  if (resolved.origin !== BASE) return fallback;
  return candidate;
}
