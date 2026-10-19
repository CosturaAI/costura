import { QueryChips } from "@/components/query-chips";
import type { ExploreDisplay, QueryProjectionMode } from "@/lib/api";
import { withNumericOption } from "@/lib/explore-state";

const DISPLAY_OPTIONS = [
  { value: "total", label: "Total" },
  { value: "delta", label: "Delta" },
  { value: "daily_average", label: "Daily average" },
  { value: "daily_average_x30", label: "Daily average x 30" },
] as const;
const AXIS_OPTIONS = [
  { value: "time", label: "Time x-axis" },
  { value: "dimension", label: "Dimension x-axis" },
] as const;
const PROJECTION_OPTIONS = [
  { value: "none", label: "No projection" },
  { value: "linear", label: "Linear projection" },
] as const;
const LOOKBACK_OPTIONS = [4, 8, 12, 30].map((value) => ({
  value: String(value),
  label: `${value} buckets`,
}));
const HORIZON_OPTIONS = [4, 8, 12, 24].map((value) => ({
  value: String(value),
  label: `${value} buckets`,
}));

/** Rows, display, axis and projection of the Analyze view, folded unless one differs from
 * its default. Each choice is a query parameter, so the URL keeps the view. */
export function ViewOptions({
  top,
  topOptions,
  display,
  axis,
  projection,
  lookback,
  horizon,
}: {
  top: number;
  topOptions: readonly { value: string; label: string }[];
  display: ExploreDisplay;
  axis: "time" | "dimension";
  projection: QueryProjectionMode;
  lookback: number;
  horizon: number;
}) {
  return (
    <details
      className="rounded-md border border-border bg-background px-4 py-3 text-sm"
      open={display !== "total" || axis !== "time" || projection !== "none" || top !== 25}
    >
      <summary className="cursor-pointer font-medium text-secondary-foreground">
        View options
      </summary>
      <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-3">
        <QueryChips name="top" value={String(top)} options={topOptions} label="Rows" size="sm" />
        <QueryChips
          name="display"
          value={display}
          options={DISPLAY_OPTIONS}
          label="Display"
          size="sm"
        />
        <QueryChips name="axis" value={axis} options={AXIS_OPTIONS} label="Chart axis" size="sm" />
        <QueryChips
          name="projection"
          value={projection}
          options={PROJECTION_OPTIONS}
          label="Projection"
          size="sm"
        />
        {projection === "linear" ? (
          <>
            <QueryChips
              name="lookback"
              value={String(lookback)}
              options={withNumericOption(LOOKBACK_OPTIONS, lookback)}
              label="Projection lookback"
              size="sm"
            />
            <QueryChips
              name="horizon"
              value={String(horizon)}
              options={withNumericOption(HORIZON_OPTIONS, horizon)}
              label="Projection horizon"
              size="sm"
            />
          </>
        ) : null}
      </div>
    </details>
  );
}
