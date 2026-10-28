/**
 * The five entity routes (key, account, workspace, model, person) share one page and one
 * title: both read the entity through the same cached loader, so the tab names the entity
 * ("prod-agent") without a second round of requests.
 */

import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cache } from "react";

import { EntityPage } from "@/components/entity-page";
import { loadEntity, type EntityKind } from "@/lib/entity";
import { entityQueryHint } from "@/lib/resource-search";
import type { Search } from "@/lib/search";
import { requireView } from "@/lib/view";

type RouteProps = {
  params: Promise<Record<string, string>>;
  searchParams?: Promise<Search>;
};

/** Keys and accounts accept a provider/account hint from search results, models the provider
 * of the row that linked them; people resolve from the e-mail alone. */
const HINTED: readonly EntityKind[] = ["api_key", "account", "workspace", "model"];

const load = cache(
  async (
    kind: EntityKind,
    org: string,
    provider: string,
    from: string,
    to: string,
    id: string,
    hintProvider: string | undefined,
    hintAccount: number | undefined,
  ) =>
    loadEntity(kind, org, provider, { from, to }, id, {
      provider: hintProvider,
      account: hintAccount,
    }),
);

async function read(kind: EntityKind, param: string, props: RouteProps) {
  const raw = (await props.params)[param];
  const hint =
    HINTED.includes(kind) && props.searchParams ? entityQueryHint(await props.searchParams) : {};
  const { org, provider, period, organization } = await requireView();
  const data = await load(
    kind,
    org,
    provider,
    period.from,
    period.to,
    decodeURIComponent(raw!),
    hint.provider,
    hint.account,
  );
  return { data, organization, org };
}

export function entityPage(kind: EntityKind, param = "id") {
  return async function Page(props: RouteProps) {
    const { data, organization, org } = await read(kind, param, props);
    if (!data) notFound();
    return <EntityPage data={data} org={org} isDemo={organization.is_demo} />;
  };
}

export function entityMetadata(kind: EntityKind, fallback: string, param = "id") {
  return async function generateMetadata(props: RouteProps): Promise<Metadata> {
    try {
      const { data } = await read(kind, param, props);
      return { title: data ? `${data.name} - ${fallback}` : fallback };
    } catch {
      // The page renders the failure; the title falls back to the kind.
      return { title: fallback };
    }
  };
}
