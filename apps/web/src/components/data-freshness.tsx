"use client";

import Link from "next/link";

import { RunsTable } from "@/components/runs-table";
import { runTone, StatusBadge } from "@/components/status-badge";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import type { Run, Schedule } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { ageLabel, freshness, freshnessTone } from "@/lib/freshness";
import type { Tone } from "@/lib/ui-types";
import { cn } from "@/lib/utils";

/**
 * Header pill: "Data as of <time>" with a green/red dot for the latest run per job. Clicking
 * opens a side panel with the latest run per job; the full history stays at `/runs`.
 */
export function automaticSyncLine(schedule: Schedule | undefined): string {
  if (!schedule || !schedule.last_run_at) return "Automatic sync: never";
  const when = formatDateTime(schedule.last_run_at).slice(0, 16);
  const verdict = schedule.status === "succeeded" ? "ok" : (schedule.status ?? "unknown");
  return `Automatic sync: ${when} ${verdict}`;
}

const STATUS_TEXT: Record<Tone, string> = {
  success: "text-severity-success",
  warning: "text-severity-warning",
  critical: "text-severity-critical",
  info: "text-severity-info",
  neutral: "text-secondary-foreground",
};

export function DataFreshness({
  runs,
  runsHref,
  schedule,
  settingsHref,
  welcomeHref,
  writesEnabled = true,
  now,
  measureAge = true,
}: {
  runs: Run[];
  runsHref: string;
  schedule?: Schedule;
  settingsHref?: string;
  /** Where "Connect a provider" leads before the first run; the link is dropped when the API
   * refuses writes, the sentence stays. */
  welcomeHref?: string;
  writesEnabled?: boolean;
  /** The API's clock when the runs were read; ages are measured against it. */
  now?: string | null;
  /** False on the sample organization, whose synthetic data has no meaningful age. */
  measureAge?: boolean;
}) {
  const state = freshness(runs);
  const clock = now ? new Date(now) : new Date();
  const mixed = new Set(runs.map((run) => run.provider)).size > 1;
  const tone =
    measureAge || state.asOf === null
      ? freshnessTone(state, clock)
      : state.failed > 0
        ? "critical"
        : "success";
  const age = measureAge ? ageLabel(state, clock) : null;
  const label =
    state.asOf === null
      ? "No data synced yet"
      : `Data as of ${formatDateTime(state.asOf).slice(0, 16)}${age ? `, ${age}` : ""}`;

  return (
    <Sheet>
      <SheetTrigger
        className={cn(
          "inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-secondary-foreground hover:bg-background",
        )}
      >
        <span className="sr-only">Data freshness:</span>
        <span
          aria-hidden
          className={cn(
            "inline-block h-2 w-2 rounded-full",
            tone === "success" && "bg-severity-success",
            tone === "warning" && "bg-severity-warning",
            tone === "critical" && "bg-severity-critical",
            tone === "neutral" && "bg-muted",
          )}
        />
        <span className="sm:hidden">
          {state.asOf === null
            ? "No data synced yet"
            : (age ?? `As of ${formatDateTime(state.asOf).slice(0, 10)}`)}
        </span>
        <span className="hidden sm:inline">{label}</span>
        {state.failed > 0 ? (
          <span className="text-severity-critical">
            {state.failed} failed job{state.failed > 1 ? "s" : ""}
          </span>
        ) : null}
      </SheetTrigger>
      <SheetContent side="right" className="w-full overflow-y-auto" style={{ maxWidth: "44rem" }}>
        <SheetHeader>
          <SheetTitle>Sync status</SheetTitle>
          <SheetDescription>
            Latest run of each job. Costs and usage come from the provider report; allocation is
            computed from them. Rows and charts reflect the newest succeeded run.
          </SheetDescription>
        </SheetHeader>
        <div className="px-4">
          <p
            className={cn(
              "mb-3 text-sm",
              STATUS_TEXT[schedule?.status ? runTone(schedule.status) : "neutral"],
            )}
          >
            {automaticSyncLine(schedule)}
            {settingsHref ? (
              <>
                {" "}
                <Link href={settingsHref} className="text-primary hover:underline">
                  Settings
                </Link>
              </>
            ) : null}
          </p>
          {state.latest.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No runs recorded. The first import starts when a provider is connected.
              {writesEnabled && welcomeHref ? (
                <>
                  {" "}
                  <Link href={welcomeHref} className="text-primary hover:underline">
                    Connect a provider
                  </Link>
                </>
              ) : null}
            </p>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-border">
              <RunsTable runs={state.latest} dense showProvider={mixed} />
            </div>
          )}
          <p className="mt-4 text-xs text-muted-foreground">
            <Link href={runsHref} className="text-primary hover:underline">
              Full run history
            </Link>
            {state.failed > 0 ? (
              <>
                {" "}
                <StatusBadge tone="critical">{state.failed} failed</StatusBadge>
              </>
            ) : null}
          </p>
        </div>
      </SheetContent>
    </Sheet>
  );
}
