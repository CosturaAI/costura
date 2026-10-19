"use server";

import { redirect } from "next/navigation";
import { z } from "zod";

import { describeError, type ActionState } from "@/lib/action-errors";
import { ApiError, api } from "@/lib/api";
import { parseForm, text } from "@/lib/form";
import { safeNextPath } from "@/lib/return-path";
import { setSessionCookie } from "@/lib/session-cookie";

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/**
 * `POST /auth/dev-sign-in`, the token into the session cookie, then `/` decides where the
 * user lands, or the `next` path when one arrived with the form. `redirect` throws and stays
 * outside the try, which only turns API refusals into the form's message.
 */
const SignIn = z.object({
  email: text()
    .transform((value) => value.toLowerCase())
    .refine((value) => EMAIL.test(value), "Enter an e-mail address like you@example.com."),
  name: text(),
  secret: text(),
  next: text().transform((value) => safeNextPath(value)),
});

export async function signInAction(_prev: ActionState, form: FormData): Promise<ActionState> {
  const parsed = parseForm(form, SignIn, ["email"]);
  if (!parsed.ok) return parsed.error;
  const { email, name, secret, next } = parsed.data;
  let session;
  try {
    session = secret
      ? await api.devSignIn(email, name || undefined, secret)
      : await api.devSignIn(email, name || undefined);
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) {
      return {
        ok: false,
        message: secret
          ? "The operator e-mail or secret was refused."
          : error.detail.includes("disabled in this environment")
            ? "This API refuses the development sign-in; it runs in production mode."
            : "This API accepts the development sign-in only from a loopback address on this machine.",
      };
    }
    return {
      ok: false,
      message: describeError(error),
      field: error instanceof ApiError && error.status === 422 ? "email" : undefined,
    };
  }
  await setSessionCookie(session.token, session.expires_at);
  redirect(next);
}
