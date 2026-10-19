import { StatusBadge } from "@/components/status-badge";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { SchedulerRun, SyncStep } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import { runStatusLabel, runStatusTone } from "@/lib/setup";

const STEP_LABELS: Record<string, string> = {
  cost: "Costs",
  total: "Costs (provider total)",
  usage: "Usage",
  inventory: "Inventory",
  allocate: "Allocation",
  detect: "Anomalies",
  project: "Projection",
  budgets: "Budgets",
};

function stepTone(status: SyncStep["status"]): "success" | "critical" | "neutral" {
  if (status === "ok") return "success";
  if (status === "failed") return "critical";
  return "neutral";
}

/** Queued / Importing / Ready / Failed pill; "Importing" before the run exists. */
export function RunStatusPill({ status }: { status: SchedulerRun["status"] | null }) {
  return <StatusBadge tone={runStatusTone(status)}>{runStatusLabel(status)}</StatusBadge>;
}

/**
 * Step table of one scheduler run (step, month, status, attempts, time, detail), shared by the
 * welcome page and the settings Sync now form. Rows appear as the run records them; an active
 * run ends with a queue or importing line, and a failed one with its error.
 */
export function SyncProgress({ run, caption }: { run: SchedulerRun; caption: string }) {
  const active = run.status === "queued" || run.status === "running";
  return (
    <div className="space-y-2">
      <div className="overflow-x-auto rounded-lg border border-border">
        <Table>
          <TableCaption className="sr-only">{caption}</TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>step</TableHead>
              <TableHead>month</TableHead>
              <TableHead>status</TableHead>
              <TableHead className="text-right">attempts</TableHead>
              <TableHead className="text-right">time</TableHead>
              <TableHead>detail</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {run.steps.map((step, index) => (
              <TableRow key={`${step.step}-${step.month ?? index}`}>
                <TableCell>{STEP_LABELS[step.step] ?? step.step}</TableCell>
                <TableCell className="font-mono text-xs">{step.month ?? "-"}</TableCell>
                <TableCell>
                  <StatusBadge tone={stepTone(step.status)}>{step.status}</StatusBadge>
                </TableCell>
                <TableCell className="text-right font-mono text-xs">{step.attempts}</TableCell>
                <TableCell className="text-right font-mono text-xs">
                  {formatDuration(step.duration_seconds)}
                </TableCell>
                <TableCell className="max-w-md truncate text-xs text-muted-foreground">
                  {step.detail ?? ""}
                </TableCell>
              </TableRow>
            ))}
            {active ? (
              <TableRow>
                <TableCell colSpan={6} className="text-xs text-muted-foreground">
                  {run.status === "queued"
                    ? "Queued: waiting for a worker."
                    : run.steps.length === 0
                      ? "Starting: the first report is being fetched."
                      : "Still importing; the next step appears when it finishes."}
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
      </div>
      {run.error ? <p className="text-sm text-severity-critical">{run.error}</p> : null}
    </div>
  );
}
