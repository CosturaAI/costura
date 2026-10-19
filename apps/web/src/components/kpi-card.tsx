import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/**
 * Headline number with an optional delta and footnote. `deltaTone` names the color: a spend
 * increase is "critical" (more money), a decrease "success"; "neutral" when direction is not a
 * judgement (allocation coverage, cache share). `emphasis="primary"` marks the one figure a
 * row is about (the month's total): a larger value and a brand rule on the left, so the four
 * cards read as one primary and three secondary instead of four equals.
 */
export function KpiCard({
  label,
  value,
  unit,
  delta,
  deltaTone = "neutral",
  hint,
  children,
  className,
  emphasis = "secondary",
}: {
  label: string;
  value: string;
  unit?: string;
  delta?: string | null;
  deltaTone?: "success" | "critical" | "neutral";
  hint?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
  emphasis?: "primary" | "secondary";
}) {
  const toneClass = {
    success: "bg-severity-success-bg text-severity-success",
    critical: "bg-severity-critical-bg text-severity-critical",
    neutral: "bg-muted text-muted-foreground",
  }[deltaTone];
  return (
    <Card
      className={cn(
        "gap-2 py-4",
        emphasis === "primary" && "border-l-4 border-l-primary bg-accent/40",
        className,
      )}
      data-emphasis={emphasis}
    >
      <CardHeader className="px-4">
        <CardDescription className="text-xs leading-tight font-medium tracking-wide text-muted-foreground uppercase">
          {label}
        </CardDescription>
        <CardTitle
          className={cn(
            "flex flex-wrap items-baseline gap-x-2 font-mono font-semibold tracking-tight",
            emphasis === "primary" ? "text-3xl text-foreground" : "text-2xl",
          )}
        >
          {value}
          {unit ? <span className="text-sm font-medium text-muted-foreground">{unit}</span> : null}
          {delta ? (
            <span className={cn("rounded px-1.5 py-0.5 font-sans text-xs font-medium", toneClass)}>
              {delta}
            </span>
          ) : null}
        </CardTitle>
      </CardHeader>
      {hint || children ? (
        <CardContent className="px-4 text-xs text-muted-foreground">
          {hint ? <p>{hint}</p> : null}
          {children}
        </CardContent>
      ) : null}
    </Card>
  );
}
