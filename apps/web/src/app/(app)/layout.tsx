import Link from "next/link";

import { AlertsBell } from "@/components/alerts-bell";
import { DataFreshness } from "@/components/data-freshness";
import { DemoBanner } from "@/components/demo-banner";
import { freshnessBand } from "@/lib/freshness";
import { ResourceSearch } from "@/components/resource-search";
import { ScopeBreadcrumb } from "@/components/scope-bar";
import { BottomTabs, MobileNav, Sidebar, type SidebarUser } from "@/components/sidebar-nav";
import { SyncBanner } from "@/components/sync-banner";
import { api, type Run } from "@/lib/api";
import { canOperate } from "@/lib/roles";
import { demoConnectHref } from "@/lib/sample";
import { loadScopeConnections, newestSchedule, writesEnabled } from "@/lib/scope";
import { readSessionToken } from "@/lib/session-cookie";
import { welcomeHref } from "@/lib/setup";
import { brandName } from "@/lib/theme";
import { requireView } from "@/lib/view";

const FRESHNESS_RUNS = 50;

/**
 * The shell every page shares: sidebar, scope bar (provider, time frame, freshness), the band
 * under the header (sample-data notice on the demo organization, import progress elsewhere)
 * and the content column. The organization, the scope and the time frame come from the view
 * cookie through `requireView`, which also decides whether the view exists; the runs list,
 * the open anomaly count (any day, so the badge keeps it across time frames), the setup
 * state, the organization list and the signed-in user are decoration and a failure in any
 * of them leaves the page up. The sample
 * organization is public: without a session the shell renders it read-only with a sign-in
 * link instead of the account menu. Under `all` the freshness pill reads the newest scheduler
 * run across providers. A signed-in member of a real organization also gets the anomaly
 * alerts bell next to the pill; visitors and the sample organization do not.
 */
export default async function ScopeLayout({ children }: { children: React.ReactNode }) {
  const {
    org,
    provider,
    from,
    to,
    interval,
    organization: current,
    registry,
  } = await requireView();
  const signedIn = (await readSessionToken()) !== null;
  const scope = await loadScopeConnections(org, provider, registry);
  const schedule = newestSchedule(scope);
  // The select offers the providers with a key or with synced runs; every registered one
  // when the organization has neither, so a first key can still be connected from the scope.
  const active = registry.filter((p) => p.connected || p.last_run !== null).map((p) => p.provider);
  const providerOptions = active.length > 0 ? active : registry.map((p) => p.provider);
  // The inbox belongs to a signed-in member of a real organization; the sample one has none.
  const inbox = signedIn && !current.is_demo;
  const [runsResult, anomaliesResult, setupResult, meResult, alertsResult] =
    await Promise.allSettled([
      api.runs(org, provider, FRESHNESS_RUNS),
      api.anomalies(org, provider, { from, to }, "open", undefined, "severity"),
      api.setup(org),
      signedIn ? api.me() : Promise.resolve(null),
      inbox ? api.alerts(org) : Promise.resolve(null),
    ]);
  const runs: Run[] = runsResult.status === "fulfilled" ? runsResult.value.runs : [];
  const asOf = runsResult.status === "fulfilled" ? (runsResult.value.as_of ?? null) : null;
  const now = asOf ? new Date(asOf) : new Date();
  const openAnomalies =
    anomaliesResult.status === "fulfilled" ? anomaliesResult.value.open_total : 0;
  const setup = setupResult.status === "fulfilled" ? setupResult.value : null;
  const me = meResult.status === "fulfilled" ? meResult.value : null;
  const alerts = alertsResult.status === "fulfilled" ? alertsResult.value : null;

  const band = freshnessBand(runs, now);
  const orgName = current.name;
  const isDemo = current.is_demo;
  const badges = { anomalies: openAnomalies };
  const user: SidebarUser | null | undefined = me
    ? {
        email: me.user.email,
        invitations: me.invitations.length,
        organizations: me.organizations
          .filter((o) => !o.is_demo)
          .map((o) => ({ slug: o.slug, name: o.name, role: o.role ?? null })),
      }
    : signedIn
      ? undefined
      : null;
  const account = { slug: org, name: orgName, role: current.role ?? null, isDemo };

  return (
    <div className="flex min-h-dvh flex-1">
      <Sidebar account={account} badges={badges} user={user} brandName={brandName()} />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-(--public-demo-bar) z-20 border-b border-border bg-background/95 backdrop-blur print:hidden">
          <div className="mx-auto flex w-full max-w-screen-2xl flex-wrap items-center gap-2 px-3 py-2 sm:flex-nowrap sm:px-6">
            <MobileNav
              brandName={brandName()}
              account={account}
              badges={badges}
              user={user}
              scope={{ provider, providers: providerOptions }}
            />
            <div className="order-last w-full min-w-0 sm:order-none sm:w-auto sm:flex-1">
              <ScopeBreadcrumb
                provider={provider}
                providers={providerOptions}
                from={from}
                to={to}
                interval={interval}
              />
            </div>
            <div className="ml-auto flex shrink-0 items-center gap-2">
              <ResourceSearch />
              <DataFreshness
                runs={runs}
                now={asOf}
                measureAge={!current.is_demo}
                runsHref="/runs"
                schedule={schedule}
                settingsHref="/settings/sync"
                welcomeHref={welcomeHref()}
                writesEnabled={writesEnabled(scope)}
              />
              {alerts ? <AlertsBell initial={alerts} canWrite={writesEnabled(scope)} /> : null}
            </div>
          </div>
        </header>
        {!isDemo && band ? (
          <p className="border-b border-border bg-severity-warning-bg px-4 py-1.5 text-xs text-severity-warning sm:px-6">
            {band}{" "}
            <Link href="/runs" className="font-medium underline">
              Run history
            </Link>
          </p>
        ) : null}
        {isDemo ? (
          <DemoBanner
            connectHref={demoConnectHref(signedIn ? (me?.organizations ?? []) : null)}
            orgName={orgName}
          />
        ) : setup ? (
          <SyncBanner org={org} initial={setup} canWrite={canOperate(current.role)} />
        ) : null}
        <main
          id="main"
          tabIndex={-1}
          className="mx-auto w-full max-w-screen-2xl flex-1 px-4 py-5 pb-[calc(4.5rem+env(safe-area-inset-bottom))] sm:px-6 lg:pb-5"
        >
          {children}
        </main>
        <BottomTabs badges={badges} />
      </div>
    </div>
  );
}
