import Link from "next/link";

import type { SignalItem } from "@/lib/ui-types";

export function SignalStrip({ items }: { items: SignalItem[] }) {
  if (items.length === 0) return null;

  return (
    <ul
      aria-label="Signals"
      className="flex flex-wrap gap-x-6 gap-y-1 rounded-md border bg-background px-4 py-2 text-sm"
    >
      {items.map((item) => (
        <li key={`${item.label}:${item.href}`} className="flex flex-wrap items-baseline gap-x-2">
          <span className="text-muted-foreground">{item.label}</span>
          <span className="font-mono font-medium text-foreground">{item.value}</span>
          {item.meta ? <span className="text-xs text-muted-foreground">{item.meta}</span> : null}
          <Link href={item.href} className="text-primary hover:underline">
            {item.linkLabel}
          </Link>
        </li>
      ))}
    </ul>
  );
}
