import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { CardHeading } from "@/components/card-heading";
import { CopyButton } from "@/components/copy-button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { formatDate } from "@/lib/format";

import { requireView } from "@/lib/view";
import { loadSettings } from "../data";
import { RenameOrganizationForm } from "../organization-forms";

export const metadata: Metadata = { title: "Organization" };

/**
 * Organization section: the name (an owner changes it), the organization ID (nobody does) and
 * when it was created. The ID is the slug the API and the invitation links address, which is why it stays
 * fixed while the name is free to follow a rebrand.
 */
export default async function OrganizationSettingsPage() {
  const settings = await loadSettings();
  // The sample's name and id are fixed; its configuration has its own section.
  if (settings.isDemo) notFound();
  const { org, canManage, isOwner } = settings;
  const { organization } = await requireView();
  const name = organization.name;

  return (
    <>
      <Card>
        <CardHeader>
          <CardHeading>Name</CardHeading>
          <CardDescription>
            Shown in the account menu, and the organization list.
            {isOwner ? "" : " Only an owner can change it."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {canManage ? (
            <RenameOrganizationForm org={org} name={name} />
          ) : (
            <p className="text-sm text-foreground">{name}</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardHeading>Organization ID</CardHeading>
          <CardDescription>
            The permanent id of this organization. It appears in the API and invitation links, and
            does not change when the name does.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-3 text-sm sm:grid-cols-[8rem_1fr]">
            <dt className="text-muted-foreground">Organization ID</dt>
            <dd className="flex items-center gap-2">
              <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-foreground">
                {org}
              </code>
              <CopyButton value={org} label="Copy the organization ID" />
            </dd>
            <dt className="text-muted-foreground">Created</dt>
            <dd className="text-foreground">
              {organization.created_at ? formatDate(organization.created_at) : "Unknown"}
            </dd>
          </dl>
        </CardContent>
      </Card>
    </>
  );
}
