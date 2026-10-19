"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, useTransition } from "react";

import { RunStatusPill, SyncProgress } from "@/components/sync-progress";
import { Button } from "@/components/ui/button";
import type { ProviderInfo, SchedulerRun, Setup } from "@/lib/api";
import { formatMonth } from "@/lib/format";
import {
  currentMonth,
  openOrgHref,
  runFor,
  runStatusText,
  shouldPoll,
  showSyncBanner,
} from "@/lib/setup";

import { getSetupAction, startSyncAction } from "@/actions/welcome";

const POLL_MS = 2000;

/**
 * Band under the header of every scoped page while an import runs or the first one failed:
 * one row per provider being imported with its pill, a one-line status, the step table behind
 * "Show steps" and Retry after a failure. Polls `setup` every two seconds while a run can
 * still change. When a poll sees the organization become `ready`, the band turns into the
 * "First data is in" link and stays until dismissed or the browser navigates away; a run that
 * finishes on an organization that already had data lets the band go and refreshes the page.
 */
export function SyncBanner({
  org,
  initial,
  canWrite,
}: {
  org: string;
  initial: Setup;
  /** False for a viewer: imports belong to members and owners. */
  canWrite: boolean;
}) {
  const router = useRouter();
  const [setup, setSetup] = useState(initial);
  const [pollError, setPollError] = useState<string | null>(null);
  const [arrived, setArrived] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const lastState = useRef(initial.state);

  const refresh = useCallback(async () => {
    const result = await getSetupAction(org);
    if (result.error !== null) {
      setPollError(result.error);
      return;
    }
    setPollError(null);
    if (lastState.current !== "ready" && result.setup.state === "ready") setArrived(true);
    lastState.current = result.setup.state;
    setSetup(result.setup);
  }, [org]);

  const polling = shouldPoll(setup);
  const wasPolling = useRef(polling);
  useEffect(() => {
    if (polling) {
      wasPolling.current = true;
      const timer = setInterval(() => void refresh(), POLL_MS);
      return () => clearInterval(timer);
    }
    // The page under the band was rendered before the run finished; reload its data once.
    if (wasPolling.current) {
      wasPolling.current = false;
      router.refresh();
    }
    return undefined;
  }, [polling, refresh, router]);

  if (arrived) {
    if (dismissed) return null;
    const month = setup.first_month ?? currentMonth();
    return (
      <div
        role="status"
        className="border-b border-severity-success/30 bg-severity-success-bg px-4 py-2 sm:px-6"
      >
        <div className="mx-auto flex w-full max-w-screen-2xl flex-wrap items-center justify-between gap-3 text-sm text-secondary-foreground">
          <p>
            First data is in -{" "}
            <Link
              prefetch={false}
              href={openOrgHref(org, "/overview", { month })}
              className="font-medium text-primary hover:underline"
            >
              open {formatMonth(month)}
            </Link>
          </p>
          <Button type="button" variant="ghost" size="sm" onClick={() => setDismissed(true)}>
            Dismiss
          </Button>
        </div>
      </div>
    );
  }

  if (!showSyncBanner(setup)) return null;
  // On an organization that already has data only the providers still importing are listed.
  const rows = setup.providers.filter(
    (p) =>
      p.connected &&
      (setup.state !== "ready" || runFor(setup.runs, p.provider)?.status !== "succeeded"),
  );
  return (
    <section
      aria-label="Import progress"
      className="border-b border-border bg-card px-4 py-3 sm:px-6"
    >
      <div className="mx-auto w-full max-w-screen-2xl space-y-3">
        {pollError ? (
          <p role="alert" className="text-sm text-severity-critical">
            {pollError}
          </p>
        ) : null}
        {rows.map((info) => (
          <ProviderRow
            key={info.provider}
            org={org}
            info={info}
            run={runFor(setup.runs, info.provider)}
            workerSeenAt={setup.worker_seen_at ?? null}
            canWrite={canWrite && setup.writes_enabled}
            onStarted={refresh}
          />
        ))}
      </div>
    </section>
  );
}

/** One provider: pill, status line, the step table behind a toggle, Retry after a failure. */
function ProviderRow({
  org,
  info,
  run,
  workerSeenAt,
  canWrite,
  onStarted,
}: {
  org: string;
  info: ProviderInfo;
  run: SchedulerRun | null;
  workerSeenAt: string | null;
  canWrite: boolean;
  onStarted: () => void;
}) {
  const [pending, start] = useTransition();
  const [message, setMessage] = useState<string | null>(null);
  const failed = run !== null && (run.status === "failed" || run.status === "skipped");
  const retry = () =>
    start(async () => {
      const result = await startSyncAction(org, info.provider);
      setMessage(result.ok ? null : result.message);
      if (result.ok) onStarted();
    });
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className="font-medium text-foreground">{info.label}</span>
        <RunStatusPill status={run?.status ?? null} />
        <span className="text-muted-foreground">
          {runStatusText(run, { worker_seen_at: workerSeenAt })}
        </span>
        {failed && canWrite ? (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={pending ? undefined : retry}
            aria-disabled={pending || undefined}
          >
            {pending ? "Starting..." : "Retry"}
          </Button>
        ) : null}
        {message ? <span className="text-severity-critical">{message}</span> : null}
      </div>
      {run !== null ? (
        <details className="text-sm">
          <summary className="cursor-pointer text-primary hover:underline">Show steps</summary>
          <div className="pt-2">
            <SyncProgress run={run} caption={`${info.label} steps`} />
          </div>
        </details>
      ) : null}
    </div>
  );
}
