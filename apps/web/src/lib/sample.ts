import type { ProviderInfo } from "@/lib/api";
import { openOrgHref } from "@/lib/setup";

type InventoryKind = "api-keys" | "workspaces" | "users";

/** Inventory a provider never lists, in the words of why: an empty table there is the
 * provider's shape, not a missing import. */
const INVENTORY_GAPS: Record<string, Partial<Record<InventoryKind, string>>> = {
  cursor: {
    "api-keys": "Cursor has no API keys to list: its usage belongs to team members.",
    workspaces: "Cursor has no workspaces: every member belongs to the one team.",
  },
  openrouter: {
    users:
      "OpenRouter lists members only for an organization account; on a personal account, usage is read by key.",
  },
};

/** Why `provider` has no rows of `kind`, when that is how the provider works; else null. */
export function inventoryGap(provider: string, kind: InventoryKind): string | null {
  return INVENTORY_GAPS[provider]?.[kind] ?? null;
}

/**
 * What the read-only sample organization says instead of an action it cannot take. Pages ask
 * here rather than branching on `is_demo` with their own sentence, so the sample never offers
 * a control the API would refuse.
 */
export const sampleCopy = {
  /** Link from a budget summary to the budgets page. */
  budgetsLink: (isDemo: boolean) => (isDemo ? "View budgets" : "Manage budgets"),
  /** In place of "Set one" where the sample has no budget. */
  noBudget: "The sample's budgets are fixed and none covers this scope.",
};

/** The providers the sample has data for; the rest of the registry is not part of its story. */
export function sampleProviders(registry: ProviderInfo[]): ProviderInfo[] {
  return registry.filter((info) => info.accounts.length > 0);
}

/**
 * Where the sample banner sends the user: the first own organization's welcome, `/new` for a
 * signed-in user without one, `/sign-in` for a visitor (`null`).
 */
export function demoConnectHref(
  organizations: { slug: string; is_demo: boolean }[] | null,
): string {
  if (organizations === null) return "/sign-in";
  const own = organizations.find((o) => !o.is_demo);
  return own ? openOrgHref(own.slug, "/welcome") : "/new";
}
