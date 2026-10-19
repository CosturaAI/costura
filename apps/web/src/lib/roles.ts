/**
 * The three organization roles and what each may do, in one place so the pages and the
 * settings sections agree. The API is the authority:
 * these helpers decide what to render, never what is allowed.
 */

export type Role = "owner" | "member" | "viewer";

export const ROLES: Role[] = ["owner", "member", "viewer"];

export const ROLE_LABELS: Record<Role, string> = {
  owner: "Owner",
  member: "Member",
  viewer: "Viewer",
};

export const ROLE_DESCRIPTIONS: Record<Role, string> = {
  owner: "Everything a member does, plus keys, budgets and who belongs here.",
  member: "Runs imports, triages anomalies and assigns owners. Cannot change keys or budgets.",
  viewer: "Reads every page. Changes nothing.",
};

/** True for the roles that may change what the organization holds: imports, anomaly status,
 * owner assignments, the getting-started card. */
export function canOperate(role: string | null | undefined): boolean {
  return role === "owner" || role === "member";
}

/** True for the role that decides keys, budgets and membership. */
export function canManage(role: string | null | undefined): boolean {
  return role === "owner";
}

export function roleLabel(role: string | null | undefined): string {
  return role && role in ROLE_LABELS ? ROLE_LABELS[role as Role] : "-";
}
