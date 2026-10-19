/**
 * The API's refusal as an exception. Kept apart from `api.ts` because that module reads the
 * session cookie through `next/headers`, which client components must not pull into their
 * bundle; `action-errors.ts` and `connect.ts` are imported by client forms and need only this.
 * `code` is the API's stable name for the refusal (`docs/operations/errors.md`), null when the
 * body carried none (a proxy answer, a non-JSON body).
 */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly path: string,
    public readonly detail: string,
    public readonly retryAfter: string | null = null,
    public readonly code: string | null = null,
  ) {
    super(`${status} ${path}: ${detail}${retryAfter ? `; retry after ${retryAfter}` : ""}`);
  }
}
