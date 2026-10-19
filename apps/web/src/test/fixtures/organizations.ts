/** Organization fixtures: organizations, the signed-in user, members and invitations. */

import type { Invitation, Me, Member, Organization, PendingInvitation } from "@/lib/api";

import { ORG } from "./common";

/** The caller's own organization, as the filtered `GET /orgs` and `GET /me` list it. */
export const organization: Organization = {
  slug: ORG,
  name: "Default organization",
  is_demo: false,
  role: "owner",
};

/** The read-only sample organization every signed-in user can open. */
export const demoOrganization: Organization = {
  slug: "demo",
  name: "Sample organization",
  is_demo: true,
  role: null,
};

export const me: Me = {
  user: { email: "owner@example.com", name: "Owner" },
  organizations: [organization, demoOrganization],
  demo_org: "demo",
  invitations: [],
};

export const members: Member[] = [
  {
    id: 1,
    email: "owner@example.com",
    name: "Owner",
    role: "owner",
    created_at: "2026-09-14T10:00:00Z",
    is_you: true,
  },
  {
    id: 2,
    email: "dev@example.com",
    name: null,
    role: "member",
    created_at: "2026-09-15T08:00:00Z",
    is_you: false,
  },
  {
    id: 3,
    email: "watcher@example.com",
    name: "Watcher",
    role: "viewer",
    created_at: "2026-09-15T09:00:00Z",
    is_you: false,
  },
];

/** The same invitation as the invitee sees it, on `/me` and the join page. */
export const pendingInvitation: PendingInvitation = {
  id: 7,
  organization: { slug: "acme", name: "Acme", is_demo: false, role: null },
  role: "member",
  invited_by: "owner@example.com",
  expires_at: "2026-09-28T12:00:00Z",
};

export const invitations: Invitation[] = [
  {
    id: 7,
    email: "newcomer@example.com",
    role: "member",
    invited_by: "owner@example.com",
    created_at: "2026-09-14T12:00:00Z",
    expires_at: "2026-09-28T12:00:00Z",
    status: "pending",
    url: null,
  },
];
