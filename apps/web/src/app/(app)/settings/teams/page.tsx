import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { CardHeading } from "@/components/card-heading";
import { CouldNotLoad } from "@/components/could-not-load";
import { RemovalFeedback } from "@/components/form-feedback";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { api } from "@/lib/api";
import { ALL } from "@/lib/providers";
import { TEAM_MEMBER_KIND_LABELS, memberOptions, teamMemberOptions } from "@/lib/teams";

import { loadSettings } from "../data";
import { AddMemberForm, DeleteTeamForm, NewTeamForm, RemoveMemberForm } from "../team-forms";

export const metadata: Metadata = { title: "Teams" };

/**
 * Teams section: cost centers made of people, API keys and workspaces. Analyze groups by
 * team and Budgets takes a team under every provider; the order of the rule is on the page.
 */
export default async function TeamsSettingsPage() {
  const settings = await loadSettings();
  if (settings.isDemo) notFound();
  const { org, canManage } = settings;
  const [teams, users, workspaces, keys] = await Promise.all([
    api.teams(org).catch(() => null),
    canManage ? api.users(org, ALL, false).catch(() => null) : null,
    canManage ? api.workspaces(org, ALL, false).catch(() => null) : null,
    canManage ? api.apiKeys(org, ALL, false).catch(() => null) : null,
  ]);
  const groups = memberOptions(users?.items ?? [], workspaces?.items ?? [], keys?.items ?? []);
  return (
    <div className="space-y-5">
      <RemovalFeedback headingId="teams-heading" statusFirst>
        <Card>
          <CardHeader>
            <CardHeading id="teams-heading" tabIndex={-1}>
              Teams
            </CardHeading>
            <CardDescription>
              A line of spend counts under the team of its API key, else of its person, else of its
              workspace; the rest reads (no team). Group by team in{" "}
              <Link href="/explore?by=team" className="text-primary hover:underline">
                Analyze
              </Link>{" "}
              and set a team budget under Every provider in{" "}
              <Link href="/budgets" className="text-primary hover:underline">
                Budgets
              </Link>
              .
            </CardDescription>
          </CardHeader>
          {canManage ? (
            <CardContent>
              <NewTeamForm org={org} />
            </CardContent>
          ) : null}
        </Card>
        {teams === null ? (
          <CouldNotLoad what="the teams" />
        ) : teams.teams.length === 0 ? (
          <p className="text-sm text-muted-foreground">No team yet.</p>
        ) : (
          teams.teams.map((team) => {
            const options = teamMemberOptions(groups, teams.teams, team.slug);
            return (
              <Card key={team.slug}>
                <CardHeader>
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <CardHeading id={`team-${team.slug}-heading`} tabIndex={-1}>
                      {team.name}
                    </CardHeading>
                    {canManage ? <DeleteTeamForm org={org} team={team} /> : null}
                  </div>
                  <CardDescription>
                    {team.members.length === 0
                      ? "Nobody mapped yet."
                      : `${team.members.length} mapped.`}
                  </CardDescription>
                </CardHeader>
                <RemovalFeedback headingId={`team-${team.slug}-heading`} className="px-6">
                  <CardContent className="space-y-4">
                    {team.members.length > 0 ? (
                      <ul aria-label={`${team.name} members`} className="divide-y divide-border">
                        {team.members.map((member) => (
                          <li
                            key={`${member.kind}:${member.provider}:${member.external_id}`}
                            className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm"
                          >
                            <span className="flex min-w-0 flex-wrap items-baseline gap-2">
                              <span className="font-medium break-words">{member.label}</span>
                              <span className="text-xs text-muted-foreground">
                                {TEAM_MEMBER_KIND_LABELS[member.kind]}
                              </span>
                            </span>
                            {canManage ? (
                              <RemoveMemberForm org={org} team={team} member={member} />
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                    {canManage && options.length > 0 ? (
                      <AddMemberForm org={org} team={team} groups={options} />
                    ) : null}
                  </CardContent>
                </RemovalFeedback>
              </Card>
            );
          })
        )}
      </RemovalFeedback>
    </div>
  );
}
