import type { Schema } from "./schema";
/**
 * The signed-in user, Google and development sign-in, and sign-out.
 */

import type { Organization } from "./organizations";
import { get, send } from "./transport";

type SessionUser = { email: string; name: string | null };

/** An invitation as the person who received it sees it: on `/me` and on the join page. */
export type PendingInvitation = Omit<Schema<"PendingInvitationOut">, "organization"> & {
  organization: Organization;
};

/** Answer of `GET /me`: the signed-in user, the organizations they belong to, the slug of the
 * public sample organization (not among `organizations`) and the invitations waiting for
 * their e-mail. */
export type Me = Omit<Schema<"MeOut">, "user" | "organizations" | "invitations"> & {
  user: SessionUser;
  organizations: Organization[];
  invitations: PendingInvitation[];
};

/** Answer of `POST /auth/dev-sign-in`; `token` goes into the session cookie, never to the page. */
type SignIn = { token: string; expires_at: string; user: SessionUser };

type GoogleAuthStatus = Schema<"GoogleAuthStatusOut">;

type GoogleAuthorization = Schema<"GoogleAuthorizationOut">;

export const sessionApi = {
  me: () => get<Me>("/me"),
  /** `me` for the sign-in page: a stale cookie answers 401 as an `ApiError` instead of a detour
   * back to the same page. */
  session: () => get<Me>("/me", undefined, { unauthorized: "throw" }),
  /** Public capability state. It contains no Google credential value. */
  googleAuth: () => get<GoogleAuthStatus>("/auth/google", undefined, { auth: false }),
  googleAuthorization: () =>
    send<GoogleAuthorization>("POST", "/auth/google/authorization", undefined, { auth: false }),
  googleCallback: (body: { code: string; state: string; nonce: string; code_verifier: string }) =>
    send<SignIn>("POST", "/auth/google/callback", body, { auth: false }),
  /** Development stand-in for Google sign-in. Production accepts it only for the configured
   * operator e-mail and secret. */
  devSignIn: (email: string, name?: string, secret?: string) =>
    send<SignIn>(
      "POST",
      "/auth/dev-sign-in",
      { email, name: name || undefined, secret: secret || undefined },
      { auth: false },
    ),
  /** 401 (session already gone) comes back as an `ApiError`; the action clears the cookie anyway. */
  signOut: () => send<void>("POST", "/auth/sign-out", undefined, { unauthorized: "throw" }),
  /** Every session of the caller, this one included. */
  signOutEverywhere: () =>
    send<void>("DELETE", "/auth/sessions", undefined, { unauthorized: "throw" }),
};
