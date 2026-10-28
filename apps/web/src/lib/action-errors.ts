import { ApiError } from "@/lib/api-error";

/** What a form shows when the API refuses or does not answer a server action. */
export type ActionState = { ok: boolean; message: string | null; field?: string };

export const idleAction: ActionState = { ok: false, message: null };

/** The invite answer carries the join link, which the API never repeats; the form keeps it on
 * screen so the owner can copy it. The idle value lives here because a server-action
 * module may export nothing but async functions. */
export type InviteState = ActionState & { url: string | null; email: string | null };

export const idleInvite: InviteState = { ...idleAction, url: null, email: null };

/** The webhook save answer carries the signing secret, which the API never repeats. */
export type WebhookState = ActionState & { secret: string | null };

export const idleWebhook: WebhookState = { ...idleAction, secret: null };

/** One sentence for an instance whose API answers `writes_enabled: false`, shared by the
 * notice above write forms and the 403 answer of every server action. */
export const WRITES_DISABLED_MESSAGE =
  "This Costura instance does not accept changes from the browser: connecting a key, Sync now and reset are turned off here.";

/** What a form shows when the API process is not reachable from the web server. */
const API_UNREACHABLE_MESSAGE = "Costura did not answer. Retry in a moment.";

/**
 * A write posted from a tab that shows another organization than the view cookie names: the
 * cookie stays the authority, so the action refuses instead of acting on the other one.
 */
export class OrganizationMismatchError extends Error {
  constructor(
    public readonly shown: string,
    public readonly active: string,
  ) {
    super(
      `This tab shows ${shown} but ${active} was opened in another tab; reload before changing anything.`,
    );
  }
}

/**
 * `redirect()` (the api wrapper's answer to a 401) throws an error carrying a `NEXT_REDIRECT`
 * digest; actions call this inside catch-all blocks, so it leaves through here instead of
 * becoming a form message. Same check as `unstable_rethrow`, without the module the tests mock.
 */
function isRedirectError(error: unknown): boolean {
  const digest = (error as { digest?: unknown } | null)?.digest;
  return typeof digest === "string" && digest.startsWith("NEXT_REDIRECT");
}

/** An API detail as a sentence: capitalized, ending with a period. */
export function sentence(detail: string): string {
  const trimmed = detail.trim();
  if (!trimmed) return trimmed;
  const capitalized = `${trimmed[0]!.toUpperCase()}${trimmed.slice(1)}`;
  return /[.!?]$/.test(capitalized) ? capitalized : `${capitalized}.`;
}

/** The 404 the API answers for an organization that is gone or that the caller left. */
function organizationMissing(error: ApiError): boolean {
  return error.code === "unknown_organization" || /^unknown organization\b/.test(error.detail);
}

export function describeError(error: unknown): string {
  if (isRedirectError(error)) throw error;
  if (error instanceof OrganizationMismatchError) return error.message;
  if (error instanceof ApiError) {
    if (error.status === 403) {
      if (/read-only/.test(error.detail)) {
        return "The sample organization is read-only; connect a provider in your own organization.";
      }
      if (/write routes are disabled/.test(error.detail)) return WRITES_DISABLED_MESSAGE;
    }
    if (error.status === 404 && organizationMissing(error)) {
      return "Organization not found on the API.";
    }
    return sentence(error.detail);
  }
  if (error instanceof Error && /fetch failed|ECONNREFUSED/i.test(error.message)) {
    return API_UNREACHABLE_MESSAGE;
  }
  return error instanceof Error ? error.message : String(error);
}
