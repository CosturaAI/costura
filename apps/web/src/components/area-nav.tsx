import Link from "next/link";

import { cn } from "@/lib/utils";

/** Local nav shared by the pages of one area. The hrefs are the existing routes. */
export const GUARDRAILS = [
  { href: "/anomalies", label: "Anomalies" },
  { href: "/budgets", label: "Budgets" },
] as const;

export const DATA_HEALTH = [
  { href: "/reconcile", label: "Reconciliation" },
  { href: "/settings/sync", label: "Sync status" },
  { href: "/runs", label: "Run history" },
] as const;

export function AreaNav({
  label,
  items,
  current,
}: {
  label: string;
  items: readonly { href: string; label: string }[];
  current: string;
}) {
  return (
    <nav aria-label={label} className="hidden flex-wrap gap-1 border-b border-border sm:flex">
      {items.map((item) => {
        const active = current === item.href;
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "-mb-px min-h-9 shrink-0 border-b-2 px-3 py-2 text-sm font-medium",
              active
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
