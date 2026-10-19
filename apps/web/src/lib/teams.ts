import type { ApiKey, TeamMember, User, Workspace } from "@/lib/api";
import { providerLabel } from "@/lib/providers";

/** The slug the API stores for a team name: lowercase words joined by hyphens. */
export function teamSlug(name: string): string {
  return name
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 63)
    .replace(/-+$/g, "");
}

export type MemberOption = { value: string; label: string };
export type MemberOptionGroups = { label: string; options: MemberOption[] }[];

/** `kind|provider|id`, the value the add form posts and a row's remove button repeats. */
export function memberValue(member: Pick<TeamMember, "kind" | "provider" | "external_id">): string {
  return `${member.kind}|${member.provider}|${member.external_id}`;
}

export const TEAM_MEMBER_KIND_LABELS: Record<TeamMember["kind"], string> = {
  person: "person",
  api_key: "API key",
  workspace: "workspace",
};

/** People (one per e-mail), workspaces and active keys still in the inventory. */
export function memberOptions(
  users: User[],
  workspaces: Workspace[],
  keys: ApiKey[],
): MemberOptionGroups {
  const emails = [
    ...new Set(
      users
        .filter((u) => u.kind === "user" && !u.missing && u.email)
        .map((u) => u.email.toLowerCase()),
    ),
  ].sort();
  return [
    {
      label: "People",
      options: emails.map((email) => ({ value: `person|all|${email}`, label: email })),
    },
    {
      label: "Workspaces",
      options: workspaces
        .filter((w) => !w.missing && w.archived_at === null)
        .map((w) => ({
          value: `workspace|${w.provider}|${w.external_id}`,
          label: `${w.name} (${providerLabel(w.provider)})`,
        })),
    },
    {
      label: "API keys",
      options: keys
        .filter((k) => !k.missing && k.status === "active")
        .map((k) => ({
          value: `api_key|${k.provider}|${k.external_id}`,
          label: `${k.name} (${providerLabel(k.provider)})`,
        })),
    },
  ].filter((group) => group.options.length > 0);
}
