import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { CardHeading } from "@/components/card-heading";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { api } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import { ROLE_DESCRIPTIONS, ROLE_LABELS } from "@/lib/roles";
import { readSessionToken } from "@/lib/session-cookie";

import { AcceptForm } from "./invitation-forms";

export const metadata: Metadata = { title: "Join" };

/**
 * The organizations waiting for the signed-in address. An owner invites an e-mail, not a
 * link-holder, so this page needs no token: whoever signs in with the invited address sees
 * the invitation here.
 */
export default async function JoinPage() {
  if ((await readSessionToken()) === null) redirect("/sign-in?next=/join");
  const me = await api.me();
  const own = me.organizations.filter((org) => !org.is_demo && org.role !== null);

  return (
    <main id="main" tabIndex={-1} className="mx-auto w-full max-w-xl space-y-6 px-4 py-10 sm:py-16">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          {me.invitations.length > 0 ? "You have been invited" : "No invitation waiting"}
        </h1>
        <p className="text-sm text-muted-foreground">
          Signed in as {me.user.email}. An invitation is bound to this address.
        </p>
      </header>

      {me.invitations.length === 0 ? (
        <Card>
          <CardHeader>
            <CardHeading>Nothing to join</CardHeading>
            <CardDescription>
              An invitation may have been sent to another address, or it was revoked or has expired.
              Ask an owner to invite {me.user.email} again.
            </CardDescription>
          </CardHeader>
          <CardContent className="text-sm">
            <Link href="/new" className="text-primary hover:underline">
              Create your own organization
            </Link>
          </CardContent>
        </Card>
      ) : (
        me.invitations.map((invitation) => (
          <Card key={invitation.id}>
            <CardHeader>
              <CardHeading>{invitation.organization.name}</CardHeading>
              <CardDescription>
                {invitation.invited_by
                  ? `${invitation.invited_by} invited you as ${ROLE_LABELS[invitation.role].toLowerCase()}. `
                  : `Invited as ${ROLE_LABELS[invitation.role].toLowerCase()}. `}
                {ROLE_DESCRIPTIONS[invitation.role]} Expires{" "}
                <time dateTime={invitation.expires_at}>
                  {formatRelative(invitation.expires_at)}
                </time>
                .
              </CardDescription>
            </CardHeader>
            <CardContent>
              <AcceptForm invitationId={invitation.id} name={invitation.organization.name} />
            </CardContent>
          </Card>
        ))
      )}

      {own.length > 0 ? (
        <p className="text-sm">
          <Link href="/" className="text-primary hover:underline">
            Back to {own[0]!.name}
          </Link>
        </p>
      ) : null}
    </main>
  );
}
