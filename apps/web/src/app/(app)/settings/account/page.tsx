import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { OptIn } from "@/components/alerts-bell";
import { CardHeading } from "@/components/card-heading";
import { StatusBadge } from "@/components/status-badge";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { api } from "@/lib/api";
import { ROLE_DESCRIPTIONS, roleLabel } from "@/lib/roles";

import { loadSettings } from "../data";
import { LeaveOrganizationForm, SignOutEverywhereForm } from "../member-forms";

export const metadata: Metadata = { title: "Account settings" };

/**
 * Account section: the settings that belong to the caller rather than to the organization, so
 * that turning the bell on or ending one's sessions is never mistaken for a change everybody
 * sees. The sample organization has no members and therefore no account section.
 */
export default async function AccountSettingsPage() {
  const settings = await loadSettings();
  const { org, isDemo, isOwner, canWrite, role } = settings;
  if (isDemo) notFound();
  const [alerts, me, members] = await Promise.all([
    api.alerts(org).catch(() => null),
    api.me().catch(() => null),
    api.members(org).catch(() => null),
  ]);
  const organization = me?.organizations.find((o) => o.slug === org) ?? null;
  // Leaving addresses the caller's own membership row, which is also how the id is known.
  const you = members?.find((member) => member.is_you) ?? null;
  const owners = members?.filter((member) => member.role === "owner").length ?? 0;
  const lastOwner = you?.role === "owner" && owners === 1;

  return (
    <>
      <Card>
        <CardHeader>
          <CardHeading>You in this organization</CardHeading>
          <CardDescription>
            The account this browser is signed in as. Ask an owner to change your role.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {me === null ? (
            <p className="text-sm text-severity-critical">
              Could not load your account; reload to retry.
            </p>
          ) : (
            <div className="space-y-2">
              <p className="flex flex-wrap items-center gap-2 text-sm text-secondary-foreground">
                <span className="font-mono">{me.user.email}</span>
                {me.user.name ? (
                  <span className="text-muted-foreground">{me.user.name}</span>
                ) : null}
                {role ? (
                  <StatusBadge tone={isOwner ? "info" : "neutral"}>{roleLabel(role)}</StatusBadge>
                ) : null}
              </p>
              {role ? (
                <p className="text-sm text-muted-foreground">{ROLE_DESCRIPTIONS[role]}</p>
              ) : null}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardHeading>Alerts</CardHeading>
          <CardDescription>
            With alerts on, every anomaly, budget alert and key gap found from then on waits in the
            bell until you read it. This setting is yours alone; nothing is sent by e-mail.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {alerts === null ? (
            <p className="text-sm text-severity-critical">
              Could not load your alert setting; reload to retry.
            </p>
          ) : (
            <OptIn optedIn={alerts.opted_in} canWrite={canWrite} />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardHeading>Your sessions</CardHeading>
          <CardDescription>
            A session ends after 30 days, or after 7 days without a visit. Sign out everywhere when
            a device went missing: every session of yours ends at once, on this browser and any
            other.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <SignOutEverywhereForm />
        </CardContent>
      </Card>

      {you !== null && canWrite ? (
        <Card>
          <CardHeader>
            <CardHeading>Leave this organization</CardHeading>
            <CardDescription>
              {lastOwner
                ? "You are the only owner. Make someone else an owner first, then you can leave."
                : `Your account stays, and so does everything you did here. An owner of ${organization?.name ?? org} can invite you back.`}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {lastOwner ? (
              <p className="text-sm text-muted-foreground">
                Promote another member in{" "}
                <Link href="/settings/members" className="text-primary hover:underline">
                  Members
                </Link>
                .
              </p>
            ) : (
              <LeaveOrganizationForm org={org} name={organization?.name ?? org} userId={you.id} />
            )}
          </CardContent>
        </Card>
      ) : null}
    </>
  );
}
