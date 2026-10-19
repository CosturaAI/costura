/** Series colors in assignment order; mirrors `--color-chart-*` in `globals.css`. */
const CHART_COLORS = [
  "var(--color-chart-1)",
  "var(--color-chart-2)",
  "var(--color-chart-3)",
  "var(--color-chart-4)",
  "var(--color-chart-5)",
  "var(--color-chart-6)",
  "var(--color-chart-7)",
  "var(--color-chart-8)",
] as const;

export const OTHER_COLOR = "var(--color-chart-other)";
export const PROJECTION_COLOR = "var(--color-chart-projection)";
export const ANOMALY_COLOR = "var(--color-severity-critical)";

export function seriesColor(index: number): string {
  return CHART_COLORS[index % CHART_COLORS.length] ?? CHART_COLORS[0]!;
}
