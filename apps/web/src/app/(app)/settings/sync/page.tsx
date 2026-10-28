import type { Metadata } from "next";
import Link from "next/link";

import { CardHeading } from "@/components/card-heading";
import { RunStatusPill } from "@/components/sync-progress";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import type { Connection, SchedulerRun } from "@/lib/api";
import { formatMinute, formatRelative } from "@/lib/format";
import { isAll } from "@/lib/providers";
import { anyConnected, newestSchedule } from "@/lib/scope";

import { SyncNowForm } from "../connection-forms";
import { importOverdue, loadSettings } from "../data";

export const metadata: Metadata = { title: "Sync" };

/** `scheduler_runs.trigger` in the words of whoever reads the row. */
const TRIGGERS: Record<string, string> = {
  scheduler: "automatic",
  api: "started here",
  manual: "started by hand",
  connect: "first import after connecting",
};

const RUN_STATUSES: readonly string[] = ["queued", "running", "succeeded", "failed", "skipped"];

/** `schedule.status` is a plain string in the API schema; an unknown one reads as importing. */
function runStatus(status: string): SchedulerRun["status"] | null {
  return RUN_STATUSES.includes(status) ? (status as SchedulerRun["status"]) : null;
}

function triggerLabel(trigger: string | null): string {
  if (trigger === null) return "";
  return TRIGGERS[trigger] ?? trigger;
}

/**
 * Sync section: when each provider last imported, when the next automatic import is due, and
 * the button that imports now. Times are relative because the decision they support is "is
 * this recent enough", with the exact instant in the title.
 */
export default async function SyncSettingsPage() {
  const settings = await loadSettings();
  const { org, provider, scope, canOperate, canWrite, isDemo } = settings;
  const aggregated = isAll(provider);
  const schedule = newestSchedule(scope) ?? scope.connections[0]?.schedule;
  const everRan = scope.connections.some((connection) => connection.schedule.last_run_at !== null);
  const connected = anyConnected(scope);
  const lastRunAt = newestSchedule(scope)?.last_run_at ?? null;
  const overdue = !isDemo && importOverdue(lastRunAt);

  return (
    <Card>
      <CardHeader>
        <CardHeading className="flex items-center gap-3">
          Automatic sync
          {schedule?.status ? <RunStatusPill status={runStatus(schedule.status)} /> : null}
        </CardHeading>
        <CardDescription>
          Once a day at {schedule?.schedule_at ?? "06:00"} UTC Costura imports the current and the
          previous month from every connected provider, then allocates the spend, detects anomalies,
          projects the month and checks the budgets.
          {isDemo
            ? " The sample runs the same steps on generated provider answers, and its run history keeps the imports that failed or retried."
            : null}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <dl className="grid gap-x-8 gap-y-2 text-sm sm:grid-cols-[10rem_1fr]">
          {aggregated ? (
            scope.providers.map((info, index) =>
              isDemo && scope.connections[index]!.accounts.length === 0 ? null : (
                <LastRun
                  key={info.provider}
                  term={info.label}
                  schedule={scope.connections[index]!.schedule}
                  connected={info.connected || isDemo}
                />
              ),
            )
          ) : schedule ? (
            <LastRun term="Last import" schedule={schedule} connected />
          ) : null}
          <dt className="text-muted-foreground">Next import</dt>
          <dd>
            {isDemo ? (
              "with the next sample refresh, once a day"
            ) : schedule?.next_run_at ? (
              <time dateTime={schedule.next_run_at}>{formatMinute(schedule.next_run_at)}</time>
            ) : (
              "none: connect a key first"
            )}
          </dd>
        </dl>
        {connected && !everRan ? (
          <p className="text-sm text-muted-foreground">
            No automatic run yet. Runs happen once a day for every connected provider; use Sync now
            to import today.
          </p>
        ) : null}
        {connected && overdue ? (
          <p className="text-sm text-severity-warning">
            No import has run since {formatMinute(lastRunAt)}, so the daily automatic import is not
            running. Use Sync now for today, or ask whoever runs Costura to check the daily import.
          </p>
        ) : null}
        {connected && canOperate ? (
          <div className="border-t border-border pt-4">
            <SyncNowForm
              org={org}
              provider={provider}
              hint={
                aggregated
                  ? "Runs every connected provider in turn, current and previous month each."
                  : undefined
              }
            />
          </div>
        ) : connected && canWrite ? (
          <p className="border-t border-border pt-4 text-sm text-muted-foreground">
            Members and owners run imports. Ask one of them, or wait for the daily run.
          </p>
        ) : null}
        <p className="text-xs text-muted-foreground">
          <Link href="/runs" className="text-primary hover:underline">
            Full run history
          </Link>
        </p>
      </CardContent>
    </Card>
  );
}

/** One row: how long ago the provider last imported, who started it, and what failed. */
function LastRun({
  term,
  schedule,
  connected,
}: {
  term: string;
  schedule: Connection["schedule"];
  connected: boolean;
}) {
  const trigger = triggerLabel(schedule.trigger);
  return (
    <>
      <dt className="text-muted-foreground">{term}</dt>
      <dd className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          {schedule.last_run_at ? (
            <span>
              <time dateTime={schedule.last_run_at}>
                {formatRelative(schedule.last_run_at)} ({formatMinute(schedule.last_run_at)})
              </time>
              {trigger ? `, ${trigger}` : null}
            </span>
          ) : (
            <span>{connected ? "never" : "not connected"}</span>
          )}
          {schedule.status && schedule.status !== "succeeded" ? (
            <RunStatusPill status={runStatus(schedule.status)} />
          ) : null}
        </div>
        {schedule.failed_steps.length > 0 ? (
          <div className="font-mono text-xs text-severity-critical">
            failed: {schedule.failed_steps.join(", ")}
          </div>
        ) : null}
        {schedule.error ? <div className="text-severity-critical">{schedule.error}</div> : null}
      </dd>
    </>
  );
}
