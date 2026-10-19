import { StatusBadge } from "@/components/status-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { CHECK_LABELS, checkValue } from "@/lib/anomaly-evidence";
import type { AnomalyCheck } from "@/lib/api";

/** One row per noise filter of the detector: what was observed, the threshold, the verdict. */
export function AnomalyChecks({ checks }: { checks: AnomalyCheck[] }) {
  if (checks.length === 0) return null;
  return (
    <Table aria-label="Detection checks">
      <TableHeader>
        <TableRow>
          <TableHead>check</TableHead>
          <TableHead className="text-right">observed</TableHead>
          <TableHead className="text-right">threshold</TableHead>
          <TableHead>verdict</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {checks.map((check) => {
          const words = CHECK_LABELS[check.name];
          return (
            <TableRow key={check.name}>
              <TableCell>
                <span className="font-medium">{words.label}</span>
                <span className="block text-xs text-muted-foreground">vs {words.threshold}</span>
              </TableCell>
              <TableCell className="text-right font-mono text-xs">
                {checkValue(check, check.observed)}
              </TableCell>
              <TableCell className="text-right font-mono text-xs">
                {checkValue(check, check.threshold)}
              </TableCell>
              <TableCell>
                {check.passed ? (
                  <StatusBadge tone="success">holds</StatusBadge>
                ) : (
                  <span className="flex flex-wrap items-center gap-2">
                    <StatusBadge tone="critical">fails</StatusBadge>
                    <span className="text-xs text-muted-foreground">{check.reason}</span>
                  </span>
                )}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
