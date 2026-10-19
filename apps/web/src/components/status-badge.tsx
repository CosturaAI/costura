import { Badge } from "@/components/ui/badge";
import type { RunStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

import type { Tone } from "@/lib/ui-types";

const tones: Record<Tone, string> = {
  success: "bg-severity-success-bg text-severity-success",
  warning: "bg-severity-warning-bg text-severity-warning",
  critical: "bg-severity-critical-bg text-severity-critical",
  info: "bg-severity-info-bg text-severity-info",
  neutral: "bg-muted text-muted-foreground",
};

export function StatusBadge({
  tone,
  children,
  className,
}: {
  tone: Tone;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Badge variant="outline" className={cn("border-transparent font-mono", tones[tone], className)}>
      {children}
    </Badge>
  );
}

/** `provider_sync_runs.status` -> tone. */
const RUN_TONES: Record<RunStatus, Tone> = {
  queued: "info",
  running: "info",
  skipped: "neutral",
  failed: "critical",
  succeeded: "success",
};

export function runTone(status: RunStatus): Tone {
  return RUN_TONES[status];
}
