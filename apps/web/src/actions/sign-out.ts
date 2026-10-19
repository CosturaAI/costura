"use server";

import { redirect } from "next/navigation";

import { ApiError, api } from "@/lib/api";
import { clearSessionCookie } from "@/lib/session-cookie";
import { clearViewCookie } from "@/lib/view-cookie";

/**
 * Ends the API session and drops the cookie. A 401 means the session is already gone on the
 * API side, so the cookie is cleared all the same. Other refusals propagate to the boundary.
 */
export async function signOutAction(): Promise<void> {
  await endSession(api.signOut);
}

/** Every session of the user on every browser, for a token that leaked or a device that
 * went missing (SECURITY.md). */
export async function signOutEverywhereAction(): Promise<void> {
  await endSession(api.signOutEverywhere);
}

async function endSession(call: () => Promise<void>): Promise<void> {
  try {
    await call();
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 401)) throw error;
  }
  await clearSessionCookie();
  await clearViewCookie();
  redirect("/sign-in");
}
