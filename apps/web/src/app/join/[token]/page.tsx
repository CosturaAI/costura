import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { signOutAction } from "@/actions/sign-out";
import { CardHeading } from "@/components/card-heading";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { api } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import { ROLE_DESCRIPTIONS, ROLE_LABELS } from "@/lib/roles";
import { readSessionToken } from "@/lib/session-cookie";

import { ClaimForm } from "../invitation-forms";

export const metadata: Metadata = { title: "Join" };

/**
 * The page an invitation link opens. Signing in comes first, because the invitation is bound
 * to an address: the token alone grants nothing, and `/me` already lists what waits for the
 * address signed in. When the link names a different address, the page says which one instead
 * of failing silently.
 */
export default async function ClaimInvitationPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  if ((await readSessionToken()) === null) {
    redirect(`/sign-in?next=/join/${encodeURIComponent(token)}`);
  }
  const me = await api.me();
  // The token is not readable from here; an invitation for this address is what makes the
  // link claimable, and the claim below is what verifies the token itself.
  const waiting = me.invitations[0] ?? null;

  return (
    <main id="main" tabIndex={-1} className="mx-auto w-full max-w-xl space-y-6 px-4 py-10 sm:py-16">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          Join {waiting ? waiting.organization.name : "an organization"}
        </h1>
        <p className="text-sm text-muted-foreground">Signed in as {me.user.email}.</p>
      </header>

      <Card>
        <CardHeader>
          <CardHeading>{waiting ? waiting.organization.name : "This invitation"}</CardHeading>
          <CardDescription>
            {waiting ? (
              <>
                {waiting.invited_by
                  ? `${waiting.invited_by} invited you as ${ROLE_LABELS[waiting.role].toLowerCase()}. `
                  : `Invited as ${ROLE_LABELS[waiting.role].toLowerCase()}. `}
                {ROLE_DESCRIPTIONS[waiting.role]} Expires{" "}
                <time dateTime={waiting.expires_at}>{formatRelative(waiting.expires_at)}</time>.
              </>
            ) : (
              <>
                Nothing is waiting for {me.user.email}. If the link was sent to another address,
                sign out and sign in with that one; otherwise ask an owner for a new invitation.
              </>
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <ClaimForm token={token} />
          <form action={signOutAction} className="text-sm text-muted-foreground">
            Wrong account?{" "}
            <button type="submit" className="text-primary hover:underline">
              Sign out
            </button>{" "}
            and open the link again.
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
