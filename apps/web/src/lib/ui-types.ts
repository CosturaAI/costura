/** Shapes that `src/lib` decides and the components render. */

export type Tone = "success" | "warning" | "critical" | "info" | "neutral";

/** One headline signal: a figure, its context and where to act on it. */
export type SignalItem = {
  label: string;
  value: string;
  meta?: string;
  href: string;
  linkLabel: string;
};

/** A dated mark on a daily chart, such as an anomaly episode. */
export type Marker = {
  day: string;
  endDay?: string | null;
  kind?: string;
  label: string;
  note?: string | null;
  href?: string | null;
  impact?: string;
  radius?: number;
  emphasis?: "primary" | "secondary";
  count?: number;
};
