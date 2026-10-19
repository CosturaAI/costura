import type { Metadata } from "next";
import Link from "next/link";

import { InventoryTables, type InventoryKind } from "@/components/inventory-tables";
import { PostureList } from "@/components/posture-list";
import { PageHeader } from "@/components/page-header";
import { QuerySelect } from "@/components/query-select";
import { api } from "@/lib/api";
import { spendKey } from "@/lib/dimensions";
import { periodTitle } from "@/lib/time-range";
import { isAll } from "@/lib/providers";
import { first, oneOf, type Search } from "@/lib/search";
import { cn } from "@/lib/utils";

import { requireView } from "@/lib/view";

export const metadata: Metadata = { title: "Resources" };

const KINDS = ["api-keys", "workspaces", "users"] as const;
const TABS = [...KINDS, "posture"] as const;
const KIND_LABELS: Record<InventoryKind, string> = {
  "api-keys": "API keys",
  workspaces: "Workspaces / Projects",
  users: "People & services",
};

const MISSING_OPTIONS = [
  { value: "false", label: "current only" },
  { value: "true", label: "include missing" },
] as const;

/** Usage dimension whose row keys are the inventory kind's external ids. */
const SPEND_DIMENSION: Record<InventoryKind, string> = {
  "api-keys": "api_key",
  workspaces: "workspace",
  users: "account",
};

export default async function InventoryPage({ searchParams }: { searchParams: Promise<Search> }) {
  const { org, provider, period, organization } = await requireView();
  const periodLabel = periodTitle(period.from, period.to);
  const query = await searchParams;
  const tab = oneOf(first(query.kind), TABS, "api-keys");
  const kind: InventoryKind = tab === "posture" ? "api-keys" : tab;
  const includeMissing = first(query.include_missing) === "true";
  const suffix = includeMissing ? "&include_missing=true" : "";

  if (tab === "posture") {
    const signals = await api.signals(org, provider).catch(() => null);
    return (
      <div className="space-y-4">
        <PageHeader
          title="Resources"
          description="Active keys with a governance gap, most spend in the last 30 days first. Fix each one in the provider console."
        />
        <ResourceTabs tab={tab} suffix={suffix} />
        <PostureList signals={signals} showProvider={isAll(provider)} />
      </div>
    );
  }

  const [apiKeys, workspaces, users, usage] = await Promise.all([
    kind === "api-keys" ? api.apiKeys(org, provider, includeMissing) : null,
    kind === "workspaces" ? api.workspaces(org, provider, includeMissing) : null,
    kind === "users" ? api.users(org, provider, includeMissing) : null,
    api.usage(org, provider, period, SPEND_DIMENSION[kind]),
  ]);
  // Keyed by provider and id: two providers may reuse an external id.
  const spend = Object.fromEntries(
    usage.rows
      .filter((row) => row.key !== null)
      .map((row) => [
        spendKey(row.provider ?? provider, row.key as string),
        { amount: row.amount, tokens: row.total_tokens },
      ]),
  );

  return (
    <div className="space-y-4">
      <PageHeader
        title="Resources"
        description={
          <>
            Keys, workspaces and people the provider still returns, with each one&apos;s spend in{" "}
            {periodLabel}. Include missing to see rows that stopped coming back. Click a name for
            its page.
          </>
        }
      >
        <QuerySelect
          name="include_missing"
          value={includeMissing ? "true" : "false"}
          options={MISSING_OPTIONS}
          label="Show"
        />
      </PageHeader>

      <ResourceTabs tab={tab} suffix={suffix} />

      <InventoryTables
        kind={kind}
        apiKeys={apiKeys?.items}
        workspaces={workspaces?.items}
        users={users?.items}
        spend={spend}
        periodLabel={periodLabel}
        showProvider={isAll(provider)}
        provider={provider}
        isDemo={organization.is_demo}
      />
    </div>
  );
}

function ResourceTabs({ tab, suffix }: { tab: (typeof TABS)[number]; suffix: string }) {
  return (
    <nav aria-label="Resource kind" className="flex flex-wrap gap-1 border-b border-border">
      {TABS.map((k) => (
        <Link
          key={k}
          href={`/inventory?kind=${k}${suffix}`}
          aria-current={tab === k ? "page" : undefined}
          className={cn(
            "-mb-px min-h-9 border-b-2 px-3 py-2 text-sm font-medium",
            tab === k
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground",
          )}
        >
          {k === "posture" ? "Posture" : KIND_LABELS[k]}
        </Link>
      ))}
    </nav>
  );
}
