"use client";

import { Area, AreaChart } from "recharts";

import { ChartContainer } from "@/components/ui/chart";

/** Tiny trend line for a KPI card; no axes, no tooltip, one series. */
export function Sparkline({
  values,
  color = "var(--color-chart-1)",
  height = 36,
}: {
  values: (string | number)[];
  color?: string;
  height?: number;
}) {
  const rows = values.map((value, i) => ({ i, value: Number(value) }));
  if (!rows.some((row) => row.value > 0)) return null;
  return (
    <ChartContainer
      config={{ value: { color } }}
      className="aspect-auto w-full"
      style={{ height }}
      aria-hidden
    >
      {/* Decorative: the KPI text beside it carries the value, so no keyboard stop. */}
      <AreaChart
        data={rows}
        margin={{ top: 2, right: 0, bottom: 0, left: 0 }}
        accessibilityLayer={false}
      >
        <Area
          dataKey="value"
          type="monotone"
          stroke={color}
          strokeWidth={1.5}
          fill={color}
          fillOpacity={0.12}
          isAnimationActive={false}
          dot={false}
        />
      </AreaChart>
    </ChartContainer>
  );
}
