"use client";

import { useMemo, useState } from "react";

import { useMinWidth } from "@/lib/use-min-width";
import Link from "next/link";
import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ReferenceDot,
  XAxis,
  YAxis,
} from "recharts";

import { Button } from "@/components/ui/button";
import { ChartContainer, ChartTooltip, type ChartConfig } from "@/components/ui/chart";
import type { DailySeries, QueryInterval } from "@/lib/api";
import type { DisplayProjection } from "@/lib/explore-display";
import { splitLabel } from "@/lib/dimensions";
import { formatCompactUsd, formatDayShort, formatUsd } from "@/lib/format";
import { intervalLabel } from "@/lib/time-range";
import type { Marker } from "@/lib/ui-types";
import { cn } from "@/lib/utils";

import { ANOMALY_COLOR, OTHER_COLOR, PROJECTION_COLOR, seriesColor } from "./palette";
import {
  OTHER_KEY,
  PROJECTION_BAND_KEY,
  PROJECTION_HIGH_KEY,
  PROJECTION_KEY,
  PROJECTION_LOW_KEY,
  bucketedAsDaily,
  buildRows,
  clipMarkers,
  dimensionTotals,
  markerDots as dotsFor,
  markerList,
  safeMarkerHref,
  summarizeMarkers,
  type BucketedSeriesData,
  type Mode,
  type Projection,
  type Row,
} from "./spend-rows";
import { MethodHint } from "@/components/method-hint";

const ANOMALY_LABEL = "anomaly";

type SpendChartProps = {
  data: DailySeries;
  currency?: string;
  projection?: Projection | null;
  markers?: Marker[];
  className?: string;
  height?: number;
  interval?: QueryInterval;
  futureProjection?: DisplayProjection | null;
  allowCumulative?: boolean;
  valueLabel?: string;
  legend?: "full" | "markers";
};

/** Time-range chart over day, week or month buckets, or one bar per dimension value. */
export function BucketedSpendChart({
  data,
  interval,
  future = null,
  axis = "time",
  valueLabel,
  markers = [],
  ...props
}: Omit<SpendChartProps, "data" | "futureProjection"> & {
  data: BucketedSeriesData;
  interval: QueryInterval;
  future?: DisplayProjection | null;
  axis?: "time" | "dimension";
  valueLabel?: string;
}) {
  if (axis === "dimension") {
    return (
      <DimensionSpendChart
        data={data}
        currency={props.currency}
        height={props.height}
        valueLabel={valueLabel}
      />
    );
  }
  const normalized = bucketedAsDaily(data, future?.buckets ?? []);
  return (
    <SpendChart
      data={normalized}
      interval={interval}
      futureProjection={future}
      valueLabel={valueLabel}
      markers={clipMarkers(markers, data.buckets)}
      {...props}
    />
  );
}

export function DailySpendChart(props: SpendChartProps) {
  return <SpendChart {...props} interval="day" />;
}

/**
 * Stacked bars per day, one stack segment per series, with a daily/cumulative toggle. When
 * `projection` is given (current month), the days after the last day with data render a dashed
 * bar at the projected amount with a lighter band up to the high estimate. `markers` place a dot
 * on top of the days that carry an open anomaly.
 */
function SpendChart({
  data,
  currency = "USD",
  projection,
  markers = [],
  className,
  height = 280,
  interval = "day",
  futureProjection = null,
  allowCumulative = true,
  valueLabel,
  legend = "full",
}: SpendChartProps) {
  const [mode, setMode] = useState<Mode>("daily");

  const keys = useMemo(() => {
    const names = data.series.map((s, i) => ({
      key: `s${i}`,
      label: splitLabel(s.label).name,
      title: s.label,
      color: seriesColor(i),
    }));
    if (data.other)
      names.push({ key: OTHER_KEY, label: "other", title: "other", color: OTHER_COLOR });
    return names;
  }, [data]);

  const rows = useMemo(
    () => buildRows(data, mode, projection ?? null, markers, futureProjection),
    [data, mode, projection, markers, futureProjection],
  );

  const config = useMemo<ChartConfig>(() => {
    const entries = keys.map((k) => [k.key, { label: k.label, color: k.color }] as const);
    entries.push([PROJECTION_KEY, { label: "projected", color: PROJECTION_COLOR }]);
    return Object.fromEntries(entries);
  }, [keys]);

  const hasData = rows.some(
    (row) =>
      Number(row.total) !== 0 ||
      row[PROJECTION_KEY] !== undefined ||
      keys.some((key) => Number(row[key.key] ?? 0) !== 0),
  );
  const hasBand = Boolean(projection?.days?.length);
  const markerDots = dotsFor(rows);
  return (
    <div className={cn("space-y-3", className)}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <ul
          className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground"
          aria-label="Legend"
        >
          {legend === "full"
            ? keys.map((k) => (
                <li key={k.key} className="flex items-center gap-1.5">
                  <span
                    aria-hidden
                    className="inline-block h-2.5 w-2.5 rounded-sm"
                    style={{ backgroundColor: k.color }}
                  />
                  <span className="max-w-48 break-words" title={k.title}>
                    {k.label}
                  </span>
                </li>
              ))
            : null}
          {projection || futureProjection ? (
            <li className="flex items-center gap-1.5">
              <span
                aria-hidden
                className="inline-block h-2.5 w-2.5 rounded-sm border border-dashed"
                style={{ borderColor: PROJECTION_COLOR }}
              />
              <MethodHint
                text="projected"
                method={
                  hasBand
                    ? "Median of the same weekday over the last 4 weeks; band from the last 8"
                    : futureProjection
                      ? `Linear trend over ${futureProjection.lookback} buckets`
                      : "Daily average until the scheduler stores a projection"
                }
              />
            </li>
          ) : null}
          {markers.length > 0 ? (
            <li className="flex items-center gap-1.5">
              <span
                aria-hidden
                className="inline-block h-2.5 w-2.5 rounded-full"
                style={{ backgroundColor: ANOMALY_COLOR }}
              />
              {ANOMALY_LABEL}
            </li>
          ) : null}
        </ul>
        {allowCumulative ? (
          <div role="group" aria-label="Chart mode" className="flex gap-1">
            {(["daily", "cumulative"] as Mode[]).map((option) => (
              <Button
                key={option}
                type="button"
                size="sm"
                variant={mode === option ? "default" : "outline"}
                aria-pressed={mode === option}
                onClick={() => setMode(option)}
              >
                {option === "daily" ? intervalLabel(interval, { lower: true }) : option}
              </Button>
            ))}
          </div>
        ) : valueLabel ? (
          <p className="text-xs text-muted-foreground">{valueLabel}</p>
        ) : null}
      </div>

      {!hasData ? (
        <p className="py-10 text-center text-sm text-muted-foreground">
          No spend recorded for these days.
        </p>
      ) : (
        <ChartContainer
          config={config}
          className="aspect-auto w-full"
          style={{ height }}
          initialDimension={{ width: 800, height }}
        >
          <ComposedChart
            data={rows}
            margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
            barGap={0}
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
              content={
                <SpendTooltip
                  keys={keys}
                  currency={currency}
                  mode={mode}
                  showShare={valueLabel !== "Change from previous bucket"}
                />
              }
            />
            {keys.map((k) => (
              <Bar
                key={k.key}
                dataKey={k.key}
                stackId="spend"
                fill={k.color}
                isAnimationActive={false}
              />
            ))}
            {projection ? (
              <Bar
                dataKey={PROJECTION_KEY}
                stackId="projection"
                fill="transparent"
                stroke={PROJECTION_COLOR}
                strokeDasharray="3 3"
                isAnimationActive={false}
              />
            ) : null}
            {futureProjection ? (
              <Line
                dataKey={PROJECTION_KEY}
                type="linear"
                stroke={PROJECTION_COLOR}
                strokeWidth={2}
                strokeDasharray="5 4"
                dot={false}
                connectNulls
                isAnimationActive={false}
              />
            ) : null}
            {hasBand ? (
              <Bar
                dataKey={PROJECTION_BAND_KEY}
                stackId="projection"
                fill={PROJECTION_COLOR}
                fillOpacity={0.18}
                isAnimationActive={false}
              />
            ) : null}
            {markerDots.map((marker, index) => (
              <ReferenceDot
                key={`${marker.day}-${index}`}
                x={marker.day}
                y={marker.total}
                r={marker.radius}
                fill={ANOMALY_COLOR}
                fillOpacity={marker.emphasis === "secondary" ? 0.55 : 1}
                stroke="var(--color-surface-0)"
                strokeWidth={1.5}
              />
            ))}
          </ComposedChart>
        </ChartContainer>
      )}
      {hasData ? (
        /* A table keeps its content width even under `sr-only`; the wrapper is the box that clips
         * it, so the hidden figures do not widen the page. */
        <div className="sr-only">
          <table>
            <caption>
              Spend by {interval} in {currency}, {mode}
            </caption>
            <thead>
              <tr>
                <th scope="col">day</th>
                <th scope="col">total</th>
                {keys.map((k) => (
                  <th key={k.key} scope="col">
                    {k.label}
                  </th>
                ))}
                {projection || futureProjection ? (
                  <>
                    <th scope="col">projected expected</th>
                    <th scope="col">projected low</th>
                    <th scope="col">projected high</th>
                  </>
                ) : null}
                {markers.length > 0 ? <th scope="col">markers</th> : null}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={String(row.day)}>
                  <th scope="row">{String(row.day)}</th>
                  <td>{formatUsd(Number(row.total ?? 0))}</td>
                  {keys.map((k) => (
                    <td key={k.key}>{formatUsd(Number(row[k.key] ?? 0))}</td>
                  ))}
                  {projection || futureProjection ? (
                    <>
                      <td>
                        {row[PROJECTION_KEY] === undefined
                          ? "-"
                          : formatUsd(Number(row[PROJECTION_KEY]))}
                      </td>
                      <td>
                        {row[PROJECTION_LOW_KEY] === undefined
                          ? "-"
                          : formatUsd(Number(row[PROJECTION_LOW_KEY]))}
                      </td>
                      <td>
                        {row[PROJECTION_HIGH_KEY] === undefined
                          ? "-"
                          : formatUsd(Number(row[PROJECTION_HIGH_KEY]))}
                      </td>
                    </>
                  ) : null}
                  {markers.length > 0 ? (
                    <td>
                      {markerList(row)
                        .map((marker) => `${ANOMALY_LABEL}: ${marker.label}`)
                        .join("; ") || "-"}
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <MarkerSummaryLine markers={markers} currency={currency} />
    </div>
  );
}

function MarkerSummaryLine({ markers, currency }: { markers: Marker[]; currency: string }) {
  const summary = summarizeMarkers(markers);
  if (!summary) return null;
  const { count, days, openOnly, worst, worstCause } = summary;
  return (
    <ul aria-label="Chart markers" className="text-xs text-muted-foreground">
      <li>
        {count} {openOnly ? "open " : ""}
        {count === 1 ? "anomaly" : "anomalies"} on {days} {days === 1 ? "day" : "days"}; worst{" "}
        {formatDayShort(worst.day)}
        {worstCause ? `, ${worstCause}${worst.impact ? ` ${currency}` : ""}` : ""}
        {" - "}
        <Link href="/anomalies" className="text-primary hover:underline">
          All anomalies
        </Link>
      </li>
    </ul>
  );
}

function DimensionSpendChart({
  data,
  currency = "USD",
  height = 280,
  valueLabel = "Total across shown buckets",
}: {
  data: BucketedSeriesData;
  currency?: string;
  height?: number;
  valueLabel?: string;
}) {
  const wide = useMinWidth(640);
  const rows = dimensionTotals(data).map((row) => ({
    ...row,
    label: row.index === null ? row.label : splitLabel(row.label).name,
    title: row.label,
    color: row.index === null ? OTHER_COLOR : seriesColor(row.index),
  }));
  const config: ChartConfig = { value: { label: valueLabel, color: seriesColor(0) } };

  return (
    <div className="space-y-3">
      <p className="text-right text-xs text-muted-foreground">{valueLabel}</p>
      <ChartContainer
        config={config}
        className="aspect-auto w-full"
        style={{ height }}
        initialDimension={{ width: 800, height }}
      >
        <ComposedChart
          data={rows}
          layout={wide ? "horizontal" : "vertical"}
          margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
          accessibilityLayer={false}
          role="presentation"
          aria-hidden="true"
        >
          <CartesianGrid vertical={false} strokeDasharray="3 3" />
          {wide ? (
            <XAxis
              dataKey="label"
              tickLine={false}
              axisLine={false}
              interval="preserveStartEnd"
              tickFormatter={(value: string) =>
                value.length > 14 ? `${value.slice(0, 13)}...` : value
              }
            />
          ) : (
            <XAxis
              type="number"
              tickLine={false}
              axisLine={false}
              tickFormatter={(value: number) => formatCompactUsd(value)}
            />
          )}
          {wide ? (
            <YAxis
              tickLine={false}
              axisLine={false}
              width={48}
              tickFormatter={(value: number) => formatCompactUsd(value)}
            />
          ) : (
            <YAxis
              type="category"
              dataKey="label"
              tickLine={false}
              axisLine={false}
              width={108}
              tickFormatter={(value: string) =>
                value.length > 16 ? `${value.slice(0, 15)}...` : value
              }
            />
          )}
          <ChartTooltip
            cursor={{ fill: "var(--muted)" }}
            content={({ active, payload }) => {
              const row = payload?.[0]?.payload as (typeof rows)[number] | undefined;
              if (!active || !row) return null;
              return (
                <div className="rounded-lg border border-border bg-card p-3 text-xs shadow-card">
                  <p className="font-medium text-foreground">{row.title}</p>
                  <p className="font-mono text-secondary-foreground">
                    {formatUsd(row.value)} {currency}
                  </p>
                </div>
              );
            }}
          />
          <Bar dataKey="value" fill="var(--color-value)" isAnimationActive={false}>
            {rows.map((row) => (
              <Cell key={row.key} fill={row.color} />
            ))}
          </Bar>
        </ComposedChart>
      </ChartContainer>
      <div className="sr-only">
        <table>
          <caption>
            {valueLabel} by dimension in {currency}
          </caption>
          <thead>
            <tr>
              <th scope="col">dimension</th>
              <th scope="col">{valueLabel}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <th scope="row">{row.title}</th>
                <td>{formatUsd(row.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

type TooltipEntry = { dataKey?: string | number; value?: number | string; payload?: Row };

export function SpendTooltip({
  active,
  payload,
  keys,
  currency,
  mode,
  showShare,
}: {
  active?: boolean;
  payload?: TooltipEntry[];
  keys: { key: string; label: string; color: string }[];
  currency: string;
  mode: Mode;
  showShare: boolean;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const row = payload[0]?.payload;
  if (!row) return null;
  const total = Number(row.total ?? 0);
  const projected = row[PROJECTION_KEY];
  const low = row[PROJECTION_LOW_KEY];
  const high = row[PROJECTION_HIGH_KEY];
  const markers = markerList(row);
  const entries = keys
    .map((k) => ({ ...k, value: Number(row[k.key] ?? 0) }))
    .filter((k) => k.value !== 0)
    .sort((a, b) => b.value - a.value);
  return (
    <div className="min-w-56 rounded-lg border border-border bg-card p-3 text-xs shadow-card">
      <div className="flex items-baseline justify-between gap-4">
        <span className="font-medium text-foreground">{formatDayShort(String(row.day))}</span>
        <span className="font-mono text-foreground">
          {formatUsd(total)} {currency}
          {mode === "cumulative" ? <span className="text-muted-foreground"> to date</span> : null}
        </span>
      </div>
      {projected !== undefined ? (
        <p className="mt-1 text-muted-foreground">
          projected {formatUsd(Number(projected))} {currency}
          {low !== undefined && high !== undefined
            ? ` (${formatUsd(Number(low))} to ${formatUsd(Number(high))})`
            : null}
        </p>
      ) : null}
      {markers.length > 0 ? (
        <ul className="mt-2 space-y-1 border-t border-border pt-2">
          {markers.map((marker, index) => (
            <li key={`${marker.day}-${marker.label}-${index}`}>
              <p style={{ color: ANOMALY_COLOR }}>
                {ANOMALY_LABEL}: {marker.label}
              </p>
              {marker.endDay && marker.endDay !== marker.day ? (
                <p className="text-muted-foreground">
                  {formatDayShort(marker.day)} to {formatDayShort(marker.endDay)}
                </p>
              ) : null}
              {marker.note ? <p className="text-muted-foreground">{marker.note}</p> : null}
              {safeMarkerHref(marker.href) ? (
                <Link href={safeMarkerHref(marker.href)!} className="text-primary hover:underline">
                  Open details
                </Link>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {entries.length > 0 ? (
        <ul className="mt-2 space-y-1">
          {entries.map((entry) => (
            <li key={entry.key} className="flex items-center justify-between gap-3">
              <span className="flex min-w-0 items-center gap-1.5 text-muted-foreground">
                <span
                  aria-hidden
                  className="inline-block h-2 w-2 shrink-0 rounded-sm"
                  style={{ backgroundColor: entry.color }}
                />
                <span className="min-w-0 break-words">{entry.label}</span>
              </span>
              <span className="shrink-0 font-mono text-foreground">
                {formatUsd(entry.value)}
                {showShare ? (
                  <span className="ml-1 text-muted-foreground">
                    {total > 0 ? `${((entry.value / total) * 100).toFixed(0)}%` : ""}
                  </span>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
