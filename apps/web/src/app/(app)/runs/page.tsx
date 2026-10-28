import type { Metadata } from "next";
import { AreaNav, DATA_HEALTH } from "@/components/area-nav";
import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { QuerySelect } from "@/components/query-select";
import { RunsTable } from "@/components/runs-table";
import { ENDPOINT_LABELS } from "@/lib/run-labels";
import { Card, CardContent } from "@/components/ui/card";
import { api } from "@/lib/api";
import { isAll, providerLabel } from "@/lib/providers";
import { first, positiveInt, type Search } from "@/lib/search";
import { syncAction, welcomeHref } from "@/lib/setup";

import { requireView } from "@/lib/view";

export const metadata: Metadata = { title: "Run history" };

const labelCounts = Object.values(ENDPOINT_LABELS).reduce<Record<string, number>>(
  (counts, label) => ({ ...counts, [label]: (counts[label] ?? 0) + 1 }),
  {},
);
const JOB_OPTIONS = [
  { value: "all", label: "All jobs" },
  ...Object.entries(ENDPOINT_LABELS).map(([value, label]) => ({
    value,
    label: labelCounts[label]! > 1 ? `${label} (${value.replaceAll("_", " ")})` : label,
  })),
];

/** Full sync history; the header pill shows the latest run per job. */
export default async function RunsPage({ searchParams }: { searchParams: Promise<Search> }) {
  const { org, provider } = await requireView();
  const query = await searchParams;
  const endpoint = first(query.endpoint) || undefined;
  const limit = positiveInt(first(query.limit), 500) ?? 50;

  // The setup answer only decides where the empty state links; a failure keeps the page up.
  const [{ runs }, setupResult] = await Promise.all([
    api.runs(org, provider, limit, endpoint),
    Promise.allSettled([api.setup(org)]).then(([r]) => r),
  ]);
  const setup = setupResult.status === "fulfilled" ? setupResult.value : null;
  const connected =
    setup?.providers.some((p) => p.connected && (isAll(provider) || p.provider === provider)) ??
    true;

  return (
    <div className="space-y-4">
      <AreaNav label="Data health" items={DATA_HEALTH} current="/runs" />
      <PageHeader
        title="Run history"
        description={`${
          runs.length < limit
            ? `${runs.length} job${runs.length === 1 ? "" : "s"}`
            : `Latest ${limit} jobs`
        } for ${isAll(provider) ? "every provider" : providerLabel(provider)}.`}
      >
        <QuerySelect
          name="endpoint"
          value={endpoint ?? "all"}
          options={JOB_OPTIONS}
          label="Job"
          emptyValue="all"
        />
      </PageHeader>

      {runs.length === 0 ? (
        <EmptyState
          message="No runs yet."
          action={connected ? syncAction() : { href: welcomeHref(), label: "Connect a provider" }}
        />
      ) : (
        <Card>
          <CardContent className="overflow-x-auto p-0">
            <RunsTable runs={runs} showProvider={isAll(provider)} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
