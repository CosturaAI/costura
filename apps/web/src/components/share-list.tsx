import Link from "next/link";

import { seriesColor } from "@/components/charts/palette";
import { splitLabel } from "@/lib/dimensions";
import { formatPercent, formatUsd } from "@/lib/format";

type ShareItem = {
  key?: string;
  label: string;
  amount: string;
  share: string | null;
  href?: string | null;
};

/** Ranked list with proportional bars; used for "where the money goes" by model or cost type. */
export function ShareList({ items, currency = "USD" }: { items: ShareItem[]; currency?: string }) {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">No spend in this period.</p>;
  }
  const max = items.reduce((m, item) => Math.max(m, Number(item.share ?? 0)), 0);
  return (
    <ul className="space-y-2">
      {items.map((item, i) => {
        const share = Number(item.share ?? 0);
        return (
          <li key={item.key ?? item.label} className="text-sm">
            <div className="flex items-baseline justify-between gap-3">
              <span className="flex min-w-0 items-center gap-2">
                <span
                  aria-hidden
                  className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm"
                  style={{ backgroundColor: seriesColor(i) }}
                />
                {item.href ? (
                  <Link
                    href={item.href}
                    className="min-w-0 font-medium break-words hover:text-primary hover:underline"
                  >
                    {splitLabel(item.label).name}
                  </Link>
                ) : (
                  <span className="min-w-0 font-medium break-words">
                    {splitLabel(item.label).name}
                  </span>
                )}
              </span>
              <span className="shrink-0 font-mono text-xs">
                {formatUsd(item.amount)} <span className="text-muted-foreground">{currency}</span>
                <span className="ml-2 inline-block w-14 text-right text-muted-foreground">
                  {formatPercent(item.share)}
                </span>
              </span>
            </div>
            <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${max > 0 ? (share / max) * 100 : 0}%`,
                  backgroundColor: seriesColor(i),
                }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}
