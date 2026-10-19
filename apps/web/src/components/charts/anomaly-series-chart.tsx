"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceArea,
  ReferenceLine,
  XAxis,
  YAxis,
} from "recharts";

import { ChartContainer, ChartTooltip } from "@/components/ui/chart";
import type { SeriesPoint } from "@/lib/api";
import { formatCompactUsd, formatDayShort, formatUsd } from "@/lib/format";

import { ANOMALY_COLOR, OTHER_COLOR, PROJECTION_COLOR, seriesColor } from "./palette";

const SERIES_COLOR = seriesColor(0);

/**
 * The eight weeks of one series ending on the episode's last day: ordinary days in the
 * series color, the days the detector took as baseline samples in the projection color, the
 * anomalous days in the anomaly color under a shaded band; the expected amount and the bound
 * the rule compared against as horizontal lines, so "what normal looked like" sits next to
 * the episode.
 */
export function AnomalySeriesChart({
  series,
  day,
  endDay,
  expected,
  upperBound,
  lowerBound = null,
  currency = "USD",
  height = 240,
}: {
  series: SeriesPoint[];
  day: string;
  /** Last day of the episode; equal to `day` on a one-day episode. */
  endDay?: string;
  expected: string;
  upperBound: string;
  /** Drawn instead of the upper bound when the rule looked downwards. */
  lowerBound?: string | null;
  currency?: string;
  height?: number;
}) {
  const last = endDay ?? day;
  const rows = series.map((point) => ({
    day: point.day,
    amount: Number(point.amount),
    kind:
      point.day >= day && point.day <= last ? "anomaly" : point.baseline_sample ? "sample" : "day",
  }));
  const colors = { anomaly: ANOMALY_COLOR, sample: PROJECTION_COLOR, day: SERIES_COLOR };
  const episodeDays = rows.filter((row) => row.kind === "anomaly").length;
  const bound = lowerBound ?? upperBound;
  const boundLabel = lowerBound === null ? "upper bound" : "lower bound";
  if (!rows.some((row) => row.amount > 0)) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">No spend in this period.</p>
    );
  }
  return (
    <div className="space-y-3">
      <ul
        className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground"
        aria-label="Legend"
      >
        <li className="flex items-center gap-1.5">
          <Swatch color={SERIES_COLOR} /> daily spend
        </li>
        <li className="flex items-center gap-1.5">
          <Swatch color={PROJECTION_COLOR} /> baseline sample
        </li>
        <li className="flex items-center gap-1.5">
          <Swatch color={ANOMALY_COLOR} />{" "}
          {episodeDays > 1 ? `${episodeDays} anomalous days` : "anomaly day"}
        </li>
        <li className="flex items-center gap-1.5">
          <span aria-hidden className="inline-block w-3 border-t border-dashed border-border" />
          expected {formatUsd(expected)} and {boundLabel} {formatUsd(bound)}
        </li>
      </ul>
      <ChartContainer
        config={{ amount: { label: "spend", color: SERIES_COLOR } }}
        className="aspect-auto w-full"
        style={{ height }}
      >
        <BarChart
          data={rows}
          margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
          accessibilityLayer={false}
          role="presentation"
          aria-hidden="true"
        >
          <CartesianGrid vertical={false} strokeDasharray="3 3" />
          <XAxis
            dataKey="day"
            tickLine={false}
            axisLine={false}
            interval="preserveStartEnd"
            minTickGap={24}
            tickFormatter={(value: string) => formatDayShort(value)}
          />
          <YAxis
            tickLine={false}
            axisLine={false}
            width={56}
            tickFormatter={(value: number) => formatCompactUsd(value)}
          />
          <ChartTooltip
            cursor={{ fill: "var(--muted)" }}
            content={({ active, payload }) => {
              const row = payload?.[0]?.payload as (typeof rows)[number] | undefined;
              if (!active || !row) return null;
              return (
                <div className="rounded-md border border-border bg-card px-3 py-2 text-xs shadow-sm">
                  <p className="font-medium text-foreground">{formatDayShort(row.day)}</p>
                  <p className="font-mono text-secondary-foreground">
                    {formatUsd(row.amount)} {currency}
                  </p>
                  {row.kind !== "day" ? (
                    <p className="text-muted-foreground">
                      {row.kind === "anomaly" ? "part of the episode" : "baseline sample"}
                    </p>
                  ) : null}
                </div>
              );
            }}
          />
          {episodeDays > 1 ? (
            <ReferenceArea
              x1={day}
              x2={last}
              fill={ANOMALY_COLOR}
              fillOpacity={0.08}
              ifOverflow="extendDomain"
            />
          ) : null}
          <ReferenceLine
            y={Number(expected)}
            stroke={OTHER_COLOR}
            strokeDasharray="4 4"
            ifOverflow="extendDomain"
          />
          <ReferenceLine
            y={Number(bound)}
            stroke="var(--color-gray-500)"
            strokeDasharray="4 4"
            ifOverflow="extendDomain"
          />
          <Bar dataKey="amount" isAnimationActive={false}>
            {rows.map((row) => (
              <Cell key={row.day} fill={colors[row.kind as keyof typeof colors]} />
            ))}
          </Bar>
        </BarChart>
      </ChartContainer>
      {/* A table keeps its content width even under `sr-only`; the wrapper is the box that clips
       * it, so the hidden figures do not widen the page. */}
      <div className="sr-only">
        <table>
          <caption>
            Daily spend of the series in {currency}, eight weeks ending on the episode&apos;s last
            day
          </caption>
          <thead>
            <tr>
              <th scope="col">day</th>
              <th scope="col">amount</th>
              <th scope="col">role</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.day}>
                <th scope="row">{row.day}</th>
                <td>{formatUsd(row.amount)}</td>
                <td>{row.kind}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Swatch({ color }: { color: string }) {
  return (
    <span
      aria-hidden
      className="inline-block h-2.5 w-2.5 rounded-sm"
      style={{ backgroundColor: color }}
    />
  );
}
