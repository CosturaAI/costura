/**
 * Where a redirect may land. The sign-in a join link asks for and the Google
 * round trip carry the target in a query parameter or a cookie, so they check it here: only a
 * path on this origin is followed, never an absolute or protocol-relative URL.
 */

const BASE = "http://costura.invalid";

/** Request header the proxy sets to the page path and query, read where a 401 redirects. */
export const PAGE_PATH_HEADER = "x-costura-path";

/**
 * Where an expired session sends the browser: the sign-in page saying the session ended, with
 * the page it was on as `next` when that path is on this origin and not the sign-in page.
 */
export function expiredSignInHref(page: string | null | undefined): string {
  const next = safeNextPath(page, "/");
  if (next === "/" || next === "/sign-in" || next.startsWith("/sign-in?")) {
    return "/sign-in?expired=1";
  }
  return `/sign-in?expired=1&next=${encodeURIComponent(next)}`;
}

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

/** Where an id-specific page goes when the organization changes: its list, else the overview. */
const ENTITY_LISTS: Record<string, string> = {
  anomalies: "/anomalies",
  keys: "/inventory?kind=api-keys",
  workspaces: "/inventory?kind=workspaces",
  people: "/inventory?kind=users",
  accounts: "/overview",
  models: "/overview",
};

/**
 * The page to land on after switching organization from `path`. A Settings section may be
 * one the other organization does not offer (owner only, sample only), and an id names a row
 * of the organization being left, so both move to a root that exists everywhere; any other
 * path stays as it is.
 */
export function switchedOrgPath(path: string): string {
  const [pathname = ""] = path.split(/[?#]/, 1);
  const segments = pathname.split("/").filter(Boolean);
  if (segments[0] === "settings") return "/settings";
  const list = segments.length > 1 ? ENTITY_LISTS[segments[0]!] : undefined;
  return list ?? path;
}
