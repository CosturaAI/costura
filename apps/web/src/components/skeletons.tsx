import { cn } from "@/lib/utils";

/** Grey shimmer block; `skeleton` is the shimmer utility in globals.css. */
export function Skeleton({
  className,
  style,
}: {
  className?: string;
  style?: React.CSSProperties;
}) {
  return <div aria-hidden style={style} className={cn("skeleton rounded-md", className)} />;
}

export function SkeletonHeader() {
  return (
    <div className="space-y-2">
      <Skeleton className="h-6 w-64" />
      <Skeleton className="h-4 w-96 max-w-full" />
    </div>
  );
}

export function SkeletonKpis({ count = 4 }: { count?: number }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="space-y-3 rounded-xl bg-card p-4 ring-1 ring-foreground/10">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-7 w-32" />
          <Skeleton className="h-3 w-40" />
        </div>
      ))}
    </div>
  );
}

export function SkeletonCard({ rows = 5, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("space-y-3 rounded-xl bg-card p-4 ring-1 ring-foreground/10", className)}>
      <Skeleton className="h-4 w-40" />
      <Skeleton className="h-3 w-64 max-w-full" />
      <div className="space-y-2 pt-2">
        {Array.from({ length: rows }, (_, i) => (
          <Skeleton key={i} className="h-4 w-full" />
        ))}
      </div>
    </div>
  );
}

export function SkeletonChart({ height = 300 }: { height?: number }) {
  return (
    <div className="space-y-3 rounded-xl bg-card p-4 ring-1 ring-foreground/10">
      <Skeleton className="h-4 w-32" />
      <Skeleton style={{ height }} className="w-full" />
    </div>
  );
}

/** Inside a layout that already drew the header: the section's cards alone (Settings). */
export function SectionSkeleton({ cards = 1, rows = 4 }: { cards?: number; rows?: number }) {
  return (
    <div className="space-y-5" role="status" aria-label="Loading">
      {Array.from({ length: cards }, (_, i) => (
        <SkeletonCard key={i} rows={rows} />
      ))}
    </div>
  );
}

export function FilterBarSkeleton() {
  return (
    <div className="flex flex-wrap gap-2" aria-hidden>
      <Skeleton className="h-9 w-40" />
      <Skeleton className="h-9 w-28" />
      <Skeleton className="h-9 w-28" />
    </div>
  );
}

export function TableSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <div className="space-y-2 rounded-lg border border-border bg-card p-3" aria-hidden>
      <Skeleton className="h-8 w-full" />
      {Array.from({ length: rows }, (_, index) => (
        <Skeleton key={index} className="h-10 w-full" />
      ))}
    </div>
  );
}

export function EntitySkeleton() {
  return (
    <div className="space-y-5" role="status" aria-label="Loading">
      <SkeletonHeader />
      <SkeletonKpis />
      <SkeletonChart height={260} />
      <SkeletonCard rows={8} />
    </div>
  );
}

/** Generic page: header plus one table card. */
export function PageSkeleton({ rows = 12 }: { rows?: number }) {
  return (
    <div className="space-y-5" role="status" aria-label="Loading">
      <SkeletonHeader />
      <SkeletonCard rows={rows} />
    </div>
  );
}
