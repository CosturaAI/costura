import { describeError } from "@/lib/action-errors";
import type { Account, Connection } from "@/lib/api";
import { ApiError } from "@/lib/api-error";

/**
 * Copy of the connect form's outcome, shared by the welcome page and the settings cards.
 * Lives outside the server action file because that file may only export async functions.
 */

/** Echoes what the API validated: provider, kind of key, last four characters of the key, and
 * whether the PUT enqueued the first import. */
export function connectedMessage(
  label: string,
  keyLabel: string,
  connection: Pick<Connection | Account, "key_hint" | "first_sync_run_id">,
): string {
  const identity = connection.key_hint
    ? `${label} ${keyLabel} ending in ${connection.key_hint} accepted`
    : `${label} ${keyLabel} accepted`;
  return connection.first_sync_run_id !== null
    ? `${identity}; the first import is starting.`
    : `${identity}.`;
}

/**
 * A 422 means the key itself was rejected. Temporary provider failures are 503 and unexpected
 * non-authentication responses are 502; both keep the API sentence, add a retry hint and leave
 * the key field neutral.
 */
export function connectFailure(error: unknown, label: string, keyLabel: string): string {
  if (error instanceof ApiError && error.status === 422) {
    const detail = error.detail;
    if (/HTTP 40[13]\b|status=40[13]\b/.test(detail)) {
      return `${label} rejected the key as invalid or revoked. Create a new ${keyLabel} in the console and paste it here.`;
    }
    return detail;
  }
  const described = describeError(error);
  if (error instanceof ApiError && error.status >= 500 && !/Retry in a moment\.$/.test(described)) {
    return `${described} Retry in a moment.`;
  }
  return described;
}
