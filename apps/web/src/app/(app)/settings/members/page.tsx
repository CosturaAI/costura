import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { CardHeading } from "@/components/card-heading";
import { StatusBadge } from "@/components/status-badge";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, type Invitation, type Member } from "@/lib/api";
import { formatDate, formatRelative } from "@/lib/format";
import { ROLE_LABELS, roleLabel } from "@/lib/roles";

import { loadSettings } from "../data";
import {
  InviteForm,
  MemberRoleForm,
  RemoveMemberForm,
  RevokeInvitationForm,
} from "../member-forms";

export const metadata: Metadata = { title: "Members" };

/**
 * Members section: who can open this organization, and for an owner the controls that change
 * that. The invite card comes first because inviting is the action people arrive
 * looking for; the table below it carries the role select and the Remove button per row.
 * Members and viewers see the same table without controls.
 */
export default async function MembersSettingsPage() {
  const settings = await loadSettings();
  // The sample organization belongs to nobody: there is no member to list.
  if (settings.isDemo) notFound();
  const { org, canManage } = settings;
  const [members, invitations] = await Promise.all([
    api.members(org).catch(() => null),
    canManage ? api.invitations(org).catch(() => []) : Promise.resolve([]),
  ]);
  // A last owner keeps the role and the membership: without an owner nobody manages the keys.
  const owners = members?.filter((member) => member.role === "owner").length ?? 0;

  return (
    <div className="space-y-5">
      {canManage ? (
        <Card>
          <CardHeader>
            <CardHeading>Invite someone</CardHeading>
            <CardDescription>
              Costura sends no e-mail. The invitation answers with a link you pass on; only the
              address you type can use it.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <InviteForm org={org} />
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardHeading>Members</CardHeading>
          <CardDescription>
            {canManage
              ? "Owners manage keys, budgets and who belongs here. Members run imports and triage anomalies. Viewers read."
              : "Owners invite people and change roles."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {members === null ? (
            <p className="text-sm text-severity-critical">
              Could not load the members; reload to retry.
            </p>
          ) : (
            <MembersTable
              org={org}
              members={members}
              canManage={canManage}
              soleOwner={owners === 1}
            />
          )}
        </CardContent>
      </Card>

      {canManage && invitations.length > 0 ? (
        <Card>
          <CardHeader>
            <CardHeading>Pending invitations</CardHeading>
            <CardDescription>
              Nobody has claimed these yet. An expired one stops working; revoke it and invite the
              address again.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <InvitationsTable invitations={invitations} />
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

/** E-mail, name, role and join date per member; for an owner, the role select and Remove. */
function MembersTable({
  members,
  canManage,
  soleOwner,
}: {
  org: string;
  members: Member[];
  canManage: boolean;
  soleOwner: boolean;
}) {
  if (members.length === 0) {
    return <p className="text-sm text-muted-foreground">No member yet.</p>;
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <Table>
        <TableCaption className="sr-only">Members</TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead>e-mail</TableHead>
            <TableHead>name</TableHead>
            <TableHead>role</TableHead>
            <TableHead>joined</TableHead>
            {canManage ? <TableHead className="text-right">actions</TableHead> : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {members.map((member) => {
            const lastOwner = soleOwner && member.role === "owner";
            return (
              <TableRow key={member.id}>
                <TableCell className="font-mono text-xs">
                  {member.email}
                  {member.is_you ? <span className="ml-2 text-muted-foreground">(you)</span> : null}
                </TableCell>
                <TableCell>{member.name ?? "-"}</TableCell>
                <TableCell>
                  {canManage ? (
                    <MemberRoleForm member={member} lastOwner={lastOwner} />
                  ) : (
                    <StatusBadge tone={member.role === "owner" ? "info" : "neutral"}>
                      {member.role}
                    </StatusBadge>
                  )}
                </TableCell>
                <TableCell className="font-mono text-xs">{formatDate(member.created_at)}</TableCell>
                {canManage ? (
                  <TableCell className="text-right">
                    {lastOwner ? (
                      <span className="text-xs text-muted-foreground">last owner</span>
                    ) : (
                      <RemoveMemberForm member={member} lastOwner={lastOwner} />
                    )}
                  </TableCell>
                ) : null}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

/** One row per invitation nobody has claimed: address, role, who sent it, when it lapses. */
function InvitationsTable({ invitations }: { invitations: Invitation[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <Table>
        <TableCaption className="sr-only">Pending invitations</TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead>e-mail</TableHead>
            <TableHead>role</TableHead>
            <TableHead>invited by</TableHead>
            <TableHead>expires</TableHead>
            <TableHead className="text-right">actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {invitations.map((invitation) => (
            <TableRow key={invitation.id}>
              <TableCell className="font-mono text-xs">{invitation.email}</TableCell>
              <TableCell>{ROLE_LABELS[invitation.role] ?? roleLabel(invitation.role)}</TableCell>
              <TableCell className="font-mono text-xs">{invitation.invited_by ?? "-"}</TableCell>
              <TableCell>
                {invitation.status === "expired" ? (
                  <StatusBadge tone="warning">expired</StatusBadge>
                ) : (
                  <time dateTime={invitation.expires_at}>
                    {formatRelative(invitation.expires_at)}
                  </time>
                )}
              </TableCell>
              <TableCell className="text-right">
                <RevokeInvitationForm invitationId={invitation.id} email={invitation.email} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
