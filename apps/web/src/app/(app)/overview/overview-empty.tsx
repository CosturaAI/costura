import { ActivityCard } from "@/components/activity-card";
import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { api } from "@/lib/api";
import { isAll } from "@/lib/providers";
import { syncAction, welcomeHref } from "@/lib/setup";

/** Empty range: say why (no key, first import running, or nothing billed) and what to do. */
export async function NoSpend({
  org,
  provider,
  displayRange,
  activity,
}: {
  org: string;
  provider: string;
  displayRange: string;
  activity: Awaited<ReturnType<typeof api.activity>> | null;
}) {
  // The connection route refuses `all`; the setup answer carries the registry list with the
  // same connected flag, plus whether a first import is running and whether writes are on.
  const setup = await api.setup(org);
  const aggregated = isAll(provider);
  const inScope = aggregated
    ? setup.providers
    : setup.providers.filter((p) => p.provider === provider);
  const connected = inScope.some((p) => p.connected);
  const info = inScope[0];
  const noKey = aggregated
    ? "no provider key connected"
    : `no ${info?.label ?? provider} key connected`;
  const connectLabel = aggregated
    ? "Connect a provider"
    : `Connect your ${info?.label ?? provider} ${info?.key_label ?? "admin key"}`;
  const importing = setup.state === "syncing";
  return (
    <div className="space-y-5">
      <PageHeader title={displayRange} />
      {activity ? <ActivityCard rows={activity} /> : null}
      <EmptyState
        message={
          !connected
            ? `No spend recorded for ${displayRange}, and this organization has ${noKey}.`
            : importing
              ? `No spend recorded for ${displayRange}; the first import has not finished.`
              : `No spend recorded for ${displayRange}. The current and previous month are imported once a day.`
        }
        action={
          !connected
            ? { href: welcomeHref(), label: connectLabel }
            : importing
              ? { href: `/runs`, label: "See the first import" }
              : syncAction()
        }
      />
    </div>
  );
}
