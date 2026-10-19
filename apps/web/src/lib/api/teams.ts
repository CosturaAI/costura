/**
 * Teams and the people, API keys and workspaces mapped to them.
 */

import type { Schema } from "./schema";
import { get, send } from "./transport";

type Teams = Schema<"TeamsOut">;
export type Team = Schema<"TeamOut">;
export type TeamMember = Schema<"TeamMemberOut">;
export type TeamMemberKind = TeamMember["kind"];

const base = (org: string) => `/orgs/${encodeURIComponent(org)}/teams`;
const member = (
  org: string,
  slug: string,
  kind: TeamMemberKind,
  provider: string,
  externalId: string,
) =>
  `${base(org)}/${encodeURIComponent(slug)}/members/${kind}/${encodeURIComponent(provider)}/${encodeURIComponent(externalId)}`;

export const teamsApi = {
  teams: (org: string) => get<Teams>(base(org)),
  setTeam: (org: string, slug: string, name: string) =>
    send<Teams>("PUT", `${base(org)}/${encodeURIComponent(slug)}`, { name }),
  deleteTeam: (org: string, slug: string) =>
    send<void>("DELETE", `${base(org)}/${encodeURIComponent(slug)}`),
  setTeamMember: (
    org: string,
    slug: string,
    kind: TeamMemberKind,
    provider: string,
    externalId: string,
  ) => send<Teams>("PUT", member(org, slug, kind, provider, externalId)),
  deleteTeamMember: (
    org: string,
    slug: string,
    kind: TeamMemberKind,
    provider: string,
    externalId: string,
  ) => send<void>("DELETE", member(org, slug, kind, provider, externalId)),
};
