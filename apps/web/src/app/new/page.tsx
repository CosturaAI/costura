import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import { suggestOrgName } from "@/lib/org-name";
import { readSessionToken } from "@/lib/session-cookie";
import { openOrgHref } from "@/lib/setup";

import { NewOrgForm } from "./new-org-form";

export const metadata: Metadata = { title: "New organization" };

/**
 * Create an organization: one name field, pre-filled from the e-mail domain, with the address
 * shown live under it. The creator becomes owner and lands on the welcome page.
 */
export default async function NewOrgPage() {
  if ((await readSessionToken()) === null) redirect("/sign-in");
  const me = await api.me();
  const existing = me.organizations.find((org) => !org.is_demo && org.role !== null) ?? null;
  return (
    <main id="main" tabIndex={-1} className="mx-auto w-full max-w-xl space-y-6 px-4 py-10 sm:py-16">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          Name your organization
        </h1>
        <p className="text-sm text-muted-foreground">
          Signed in as {me.user.email}. Provider keys, budgets and members belong to an
          organization.
        </p>
      </header>
      {me.invitations.length > 0 ? (
        <p className="rounded-lg border border-border bg-background p-3 text-sm text-secondary-foreground">
          {me.invitations.length === 1
            ? `${me.invitations[0]!.organization.name} has invited you.`
            : `${me.invitations.length} organizations have invited you.`}{" "}
          <Link href="/join" className="font-medium text-primary hover:underline">
            Join instead of creating one
          </Link>
          .
        </p>
      ) : null}
      <NewOrgForm suggestedName={suggestOrgName(me.user.email)} />
      {existing ? (
        <p className="text-sm">
          <Link
            prefetch={false}
            href={openOrgHref(existing.slug)}
            className="text-primary hover:underline"
          >
            Back to {existing.name}
          </Link>
        </p>
      ) : null}
    </main>
  );
}
