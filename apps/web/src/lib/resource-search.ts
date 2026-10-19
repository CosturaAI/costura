import type { InventorySearchItem } from "@/lib/api";
import { personHref } from "@/lib/dimensions";
import { hasAccountLabel, PROVIDERS, providerLabel } from "@/lib/providers";
import { first, positiveInt, type Search } from "@/lib/search";

export const RESOURCE_GROUPS = [
  { kind: "person", label: "People" },
  { kind: "service", label: "Services" },
  { kind: "api_key", label: "API keys" },
  { kind: "workspace", label: "Workspaces / Projects" },
] as const;

export type EntityHint = { provider?: string; account?: number };

/** Provider and provider-account hints carried on a search result address. */
export function entityQueryHint(query: Search): EntityHint {
  const provider = first(query.provider);
  return {
    provider: provider && PROVIDERS.includes(provider) ? provider : undefined,
    account: positiveInt(first(query.provider_account)),
  };
}

/** Stable cmdk value. The visible label can repeat across providers and accounts. */
export function resourceValue(item: InventorySearchItem): string {
  return [item.kind, item.providers.join(","), item.provider_account_id ?? "", item.id].join(":");
}

/** Where selecting a result goes. People stay on the e-mail page; other kinds name the
 * provider and account so a repeated external id opens the row that matched. */
export function resourceHref(item: InventorySearchItem): string {
  const path =
    item.kind === "person"
      ? personHref(item.id)
      : item.kind === "service"
        ? `/accounts/${encodeURIComponent(item.id)}`
        : item.kind === "api_key"
          ? `/keys/${encodeURIComponent(item.id)}`
          : `/workspaces/${encodeURIComponent(item.id)}`;
  if (item.kind === "person" || item.providers.length !== 1) return path;
  const params = new URLSearchParams({ provider: item.providers[0]! });
  if (item.provider_account_id != null) {
    params.set("provider_account", String(item.provider_account_id));
  }
  return `${path}?${params.toString()}`;
}

/** Provider, account and hint on one line. The account is omitted when it only repeats
 * the provider name. */
export function resourceDetail(item: InventorySearchItem): string {
  const provider = item.providers.map(providerLabel).join(", ");
  const account =
    item.providers.length === 1 && hasAccountLabel(item.providers[0]!, item.provider_account_label)
      ? item.provider_account_label
      : null;
  return [provider, account, item.hint].filter((part) => part).join(" · ");
}
