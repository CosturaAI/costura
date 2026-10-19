import Link from "next/link";

import { seriesColor } from "@/components/charts/palette";
import { formatPercent, formatUsd } from "@/lib/format";

export type ProviderShare = {
  key: string;
  label: string;
  amount: string;
  share: string | null;
  href?: string | null;
};

/**
 * One stacked bar plus a legend with each provider's amount and share, shown inside the daily
 * spend card under the aggregated scope. A card of its own stretched to the height of the ranked
 * tables beside it, which left two rows floating in 600 px of white. Fewer than two
 * providers carry no comparison, so the strip renders nothing.
 */
export function ProviderStrip({
  items,
  currency = "USD",
  className,
}: {
  items: ProviderShare[];
  currency?: string;
  className?: string;
}) {
  if (items.length < 2) return null;
  const total = items.reduce((sum, item) => sum + Number(item.amount), 0);
  const widths = items.map((item) =>
    item.share !== null ? Number(item.share) : total > 0 ? (Number(item.amount) / total) * 100 : 0,
  );

  return (
    <div className={className}>
      <div
        aria-hidden
        className="flex h-2 w-full overflow-hidden rounded-full bg-muted"
        data-testid="provider-strip-bar"
      >
        {items.map((item, i) => (
          <span
            key={item.key}
            className="h-full first:rounded-l-full last:rounded-r-full"
            style={{ width: `${widths[i]}%`, backgroundColor: seriesColor(i) }}
          />
        ))}
      </div>
      <ul
        aria-label="Spend by provider"
        className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm"
        data-slot="provider-legend"
      >
        {items.map((item, i) => (
          <li key={item.key} className="flex min-w-0 items-baseline gap-2">
            <span
              aria-hidden
              className="mt-1 inline-block h-2.5 w-2.5 shrink-0 self-start rounded-sm"
              style={{ backgroundColor: seriesColor(i) }}
            />
            {item.href ? (
              <Link href={item.href} className="truncate font-medium hover:text-primary">
                {item.label}
              </Link>
            ) : (
              <span className="truncate font-medium">{item.label}</span>
            )}
            <span className="shrink-0 font-mono text-xs">
              {formatUsd(item.amount)} <span className="text-muted-foreground">{currency}</span>
              <span className="ml-1.5 text-muted-foreground">{formatPercent(item.share)}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
