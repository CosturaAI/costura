import type { Schema } from "./schema";
/**
 * Organizations, members, invitations and the entity lookup.
 */

import { ALL } from "@/lib/providers";
import type { Role } from "@/lib/roles";

import { get, send } from "./transport";

export type EntityLookupKind = "key" | "workspace" | "account" | "model" | "anomaly";

export type EntityLookup = { provider: string; provider_account_id: number | null };

export type Organization = Schema<"OrganizationOut">;

export { DEMO_ORG } from "@/lib/public-demo";

export type Member = Schema<"MemberOut">;

/** An invitation as the owner who sent it sees it. `url` is the join link, present only in
 * the answer that created the invitation. */
export type Invitation = Schema<"InvitationOut">;

/** `GET /orgs/{org}/audit`: who changed keys, roles and settings, newest first. Owners only. */
export type AuditTrail = Schema<"AuditOut">;

export const organizationsApi = {
  /** The caller's organizations; 401 without a session. The sample one is not listed. */
  orgs: () => get<Organization[]>("/orgs"),
  /** One organization: a membership, or the public sample organization, which answers with
   * or without a session. 404 on an unknown slug or another tenant. */
  org: (slug: string) => get<Organization>(`/orgs/${encodeURIComponent(slug)}`),
  /** 409 on a taken slug, 422 on a slug outside `^[a-z0-9][a-z0-9-]{1,62}$` or a blank name. */
  createOrg: (name: string, slug: string) => send<Organization>("POST", "/orgs", { name, slug }),
  /** Owner only. The slug is the immutable id and has no rename route. 422 on a blank name. */
  renameOrg: (org: string, name: string) =>
    send<Organization>("PATCH", `/orgs/${encodeURIComponent(org)}`, { name }),
  /** Which provider (and account) an id belongs to; 404 when the organization has no such
   * key, workspace, account, model or anomaly. `scope` breaks a tie on a model
   * name shared by several providers. `account` picks one console when the same external id
   * exists twice. */
  entityLookup: (
    org: string,
    kind: EntityLookupKind,
    id: string,
    scope?: string,
    account?: number,
  ) =>
    get<EntityLookup>(
      `/orgs/${encodeURIComponent(org)}/entities/${kind}/${encodeURIComponent(id)}`,
      {
        ...(scope && scope !== ALL ? { scope } : {}),
        ...(account !== undefined ? { account } : {}),
      },
    ),
  members: (org: string) => get<Member[]>(`/orgs/${encodeURIComponent(org)}/members`),
  /** Owner only; 409 when the change would leave the organization without an owner. */
  setMemberRole: (org: string, userId: number, role: Role) =>
    send<Member>("PATCH", `/orgs/${encodeURIComponent(org)}/members/${userId}`, { role }),
  /** An owner removes anyone; anyone removes themself, which is how leaving works. 409 on
   * the last owner. */
  removeMember: (org: string, userId: number) =>
    send<void>("DELETE", `/orgs/${encodeURIComponent(org)}/members/${userId}`),
  /** Owner only; the answer carries the join link, which the API never repeats. 409 when the
   * address is already a member or already invited. */
  invite: (org: string, email: string, role: Role) =>
    send<Invitation>("POST", `/orgs/${encodeURIComponent(org)}/invitations`, { email, role }),
  /** Owner only: invitations nobody accepted or revoked, expired ones included. */
  invitations: (org: string) => get<Invitation[]>(`/orgs/${encodeURIComponent(org)}/invitations`),
  audit: (org: string, limit = 100, offset = 0) =>
    get<AuditTrail>(`/orgs/${encodeURIComponent(org)}/audit?limit=${limit}&offset=${offset}`),
  revokeInvitation: (org: string, id: number) =>
    send<void>("DELETE", `/orgs/${encodeURIComponent(org)}/invitations/${id}`),
  /** Join the organization an invitation names; 403 when the signed-in e-mail is not the
   * invited one, 410 when it was revoked, used or has expired. */
  acceptInvitation: (id: number) => send<Organization>("POST", `/invitations/${id}/accept`),
  claimInvitation: (token: string) => send<Organization>("POST", "/invitations/claim", { token }),
  /** Owner only: removes the organization once the typed slug matches. 409 while a sync is
   * queued or running. */
  deleteOrganization: (org: string, slug: string) =>
    send<void>("DELETE", `/orgs/${encodeURIComponent(org)}`, { slug }),
};
