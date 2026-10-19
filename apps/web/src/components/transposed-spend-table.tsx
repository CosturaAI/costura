import type { BucketedSeriesData } from "@/components/charts/spend-rows";
import { splitLabel } from "@/lib/dimensions";
import { formatDayShort, formatUsd } from "@/lib/format";

export function TransposedSpendTable({
  data,
  currency = "USD",
  caption,
}: {
  data: BucketedSeriesData;
  currency?: string;
  caption: string;
}) {
  const rows = [
    ...data.series.map((series, index) => ({
      key: `${series.provider ?? "scope"}:${series.key ?? index}`,
      label: splitLabel(series.label).name,
      values: series.values,
    })),
    ...(data.other ? [{ key: "__other__", label: "Other", values: data.other }] : []),
  ];

  return (
    <div className="overflow-auto">
      <table className="w-full min-w-max border-collapse text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-border bg-background text-left text-xs text-muted-foreground">
            <th
              scope="col"
              className="sticky left-0 z-10 min-w-44 bg-background px-4 py-3 font-medium"
            >
              Series
            </th>
            {data.buckets.map((bucket) => (
              <th key={bucket} scope="col" className="px-4 py-3 text-right font-medium">
                <span title={bucket}>{formatDayShort(bucket)}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} className="border-b border-border">
              <th
                scope="row"
                className="sticky left-0 z-10 max-w-64 bg-card px-4 py-3 text-left font-medium text-foreground"
                title={row.label}
              >
                <span className="block break-words">{row.label}</span>
              </th>
              {row.values.map((value, index) => (
                <td key={data.buckets[index]} className="px-4 py-3 text-right font-mono">
                  {formatUsd(Number(value))}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="bg-background font-medium">
            <th scope="row" className="sticky left-0 z-10 bg-background px-4 py-3 text-left">
              Total ({currency})
            </th>
            {data.total.map((value, index) => (
              <td key={data.buckets[index]} className="px-4 py-3 text-right font-mono">
                {formatUsd(Number(value))}
              </td>
            ))}
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
