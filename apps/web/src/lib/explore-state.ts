/**
 * Parse, defaults and serialization of the Explore page state. The page reads it from the URL
 * and writes it back through `exploreHref`.
 */

import type {
  ExploreDisplay,
  ExploreTimeFrame,
  QueryCompare,
  QueryInterval,
  QueryProjectionMode,
  UsageFilters,
} from "@/lib/api";
import { encodeFilterClause } from "@/lib/query-export";
import { presetRange, validRange, type TimeFramePreset } from "@/lib/time-range";

type ExploreAxis = "time" | "dimension";

type ExploreLinkState = {
  measure?: string;
  dimension: string | null;
  top: number | "all";
  filters: UsageFilters;
  time_frame?: ExploreTimeFrame;
  start: string | null;
  end: string | null;
  interval: QueryInterval;
  compare: QueryCompare;
  display: ExploreDisplay;
  axis?: ExploreAxis;
  projection?: QueryProjectionMode;
  lookback?: number;
  horizon?: number;
  rangePreset?: TimeFramePreset | null;
};

function filterParams(filters: UsageFilters): string[] {
  return Object.entries(filters).flatMap(([dimension, filter]) => {
    if (!filter) return [];
    const clause = typeof filter === "string" ? { op: "is" as const, values: [filter] } : filter;
    return [encodeFilterClause(dimension, clause)];
  });
}

function rangeFromView(
  view: ExploreLinkState,
  fallback: { from: string; to: string; interval: QueryInterval },
) {
  if (view.time_frame) return { ...presetRange(view.time_frame), interval: view.interval };
  if (validRange(view.start, view.end)) {
    return { from: view.start!, to: view.end!, interval: view.interval };
  }
  return fallback;
}

export function exploreHref(state: ExploreLinkState): string {
  const range = rangeFromView(state, {
    from: state.start ?? "",
    to: state.end ?? "",
    interval: state.interval,
  });
  const params = new URLSearchParams({
    by: state.dimension ?? "api_key",
    top: String(state.top),
  });
  if (state.measure && state.measure !== "billed_usd") params.set("measure", state.measure);
  filterParams(state.filters).forEach((filter) => params.append("f", filter));
  params.set("from", range.from);
  params.set("to", range.to);
  params.set("interval", range.interval);
  params.set("display", state.display);
  params.set("compare", state.compare);
  if (state.axis && state.axis !== "time") params.set("axis", state.axis);
  if (state.projection && state.projection !== "none") {
    params.set("projection", state.projection);
    params.set("lookback", String(state.lookback ?? 8));
    params.set("horizon", String(state.horizon ?? 4));
  }
  if (state.rangePreset?.startsWith("last_")) {
    params.set("time_frame", state.rangePreset);
    params.set("period", "last");
  } else if (state.rangePreset?.startsWith("rolling_")) {
    params.set("time_frame", `last_${state.rangePreset.slice("rolling_".length)}`);
    params.set("period", "rolling");
  }
  return `/explore?${params.toString()}`;
}

export function withNumericOption(
  options: readonly { value: string; label: string }[],
  value: number,
): readonly { value: string; label: string }[] {
  const current = String(value);
  return options.some((option) => option.value === current)
    ? options
    : [...options, { value: current, label: `${current} buckets` }].sort(
        (a, b) => Number(a.value) - Number(b.value),
      );
}

export function displayLabel(display: ExploreDisplay, interval: QueryInterval): string {
  if (display === "delta") return "Change from previous bucket";
  if (display === "daily_average") return "Daily average";
  if (display === "daily_average_x30") return "Daily average x 30";
  return interval === "day"
    ? "Daily total"
    : interval === "week"
      ? "Weekly total"
      : "Monthly total";
}
