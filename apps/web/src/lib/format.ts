/** The one locale every figure renders in; a locale switch is this constant. */
export const LOCALE = "en-US";

const usd = new Intl.NumberFormat(LOCALE, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const integer = new Intl.NumberFormat(LOCALE);
const compact = new Intl.NumberFormat(LOCALE, { notation: "compact" });
const quantityFormat = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 2 });
const measureFormat = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 4 });
const unitCostFormat = new Intl.NumberFormat(LOCALE, {
  minimumFractionDigits: 2,
  maximumFractionDigits: 8,
});

/** A whole count with grouping: requests, tokens, rows. */
export function formatInteger(value: number | string): string {
  return integer.format(Number(value));
}

/** "2.2B", "980K": large counts where the order of magnitude is the point. */
export function formatCompact(value: number): string {
  return compact.format(value);
}

/** A usage quantity with up to two decimals (activity families). */
export function formatQuantity(value: number | string): string {
  return quantityFormat.format(Number(value));
}

/** A non-money measure with up to four decimals (anomaly values in tokens or requests). */
export function formatMeasure(value: number | string): string {
  return measureFormat.format(Number(value));
}

/** A unit price with up to eight decimals (cost per token). */
export function formatUnitCost(value: number | string): string {
  return unitCostFormat.format(Number(value));
}

/** API money strings are already rounded to cents; this only adds grouping. */
export function formatUsd(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "-";
  const parsed = typeof value === "number" ? value : Number.parseFloat(value);
  if (Number.isNaN(parsed)) return "-";
  return usd.format(parsed);
}

export function formatTokens(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return integer.format(value);
}

export function formatPercent(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "-";
  const parsed = typeof value === "number" ? value : Number.parseFloat(value);
  if (Number.isNaN(parsed)) return "-";
  return `${usd.format(parsed)}%`;
}

/** "2026-09-15T06:00:03Z" -> "2026-09-15 06:00:03 UTC"; every timestamp ends in " UTC". */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return `${date.toISOString().replace("T", " ").slice(0, 19)} UTC`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  return value.slice(0, 10);
}

/** "2026-09-15T06:00:00Z" -> "2026-09-15 06:00 UTC": a point in time to the minute. */
export function formatMinute(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return `${date.toISOString().replace("T", " ").slice(0, 16)} UTC`;
}

const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

function plural(count: number, unit: string): string {
  return `${count} ${unit}${count === 1 ? "" : "s"}`;
}

/**
 * How long ago something happened, for the Settings rows where the exact second carries no
 * decision ("2 hours ago"); the absolute value belongs in a `title` next to it. Older than 30
 * days reads as the date, so a stale connection does not turn into "412 days ago". Future
 * instants (the next scheduled run) read "in ...".
 */
export function formatRelative(value: string | null | undefined, now: Date = new Date()): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  const seconds = Math.round((now.getTime() - date.getTime()) / 1000);
  const ahead = seconds < 0;
  const distance = Math.abs(seconds);
  if (distance < MINUTE) return "just now";
  let span: string;
  if (distance < HOUR) span = plural(Math.floor(distance / MINUTE), "minute");
  else if (distance < DAY) span = plural(Math.floor(distance / HOUR), "hour");
  else if (distance < 30 * DAY) span = plural(Math.floor(distance / DAY), "day");
  else return formatDate(date.toISOString());
  return ahead ? `in ${span}` : `${span} ago`;
}

const compactMoney = new Intl.NumberFormat(LOCALE, {
  notation: "compact",
  maximumFractionDigits: 1,
});

/** Axis and tooltip labels: 56056.12 -> "$56.1K", 950 -> "$950". */
export function formatCompactUsd(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "-";
  const parsed = typeof value === "number" ? value : Number.parseFloat(value);
  if (Number.isNaN(parsed)) return "-";
  const sign = parsed < 0 ? "-" : "";
  const size = Math.abs(parsed);
  if (size < 1000) {
    return `${sign}$${Number.isInteger(size) ? integer.format(size) : usd.format(size)}`;
  }
  return `${sign}$${compactMoney.format(size)}`;
}

/** Percent change between two amounts, two decimals; null when there is no non-zero base. */
export function changePercent(
  current: string | number | null,
  previous: string | number | null,
): string | null {
  if (current === null || previous === null || previous === "") return null;
  const base = typeof previous === "number" ? previous : Number.parseFloat(previous);
  const value = typeof current === "number" ? current : Number.parseFloat(current);
  if (!Number.isFinite(base) || base === 0 || !Number.isFinite(value)) return null;
  return (((value - base) / base) * 100).toFixed(2);
}

export function formatSignedUsd(value: string | number | null | undefined): string {
  const text = formatUsd(value);
  if (text === "-") return text;
  const parsed = typeof value === "number" ? value : Number.parseFloat(value ?? "");
  return parsed > 0 ? `+${text}` : text;
}

export function formatDelta(percent: string | number | null | undefined): string | null {
  if (percent === null || percent === undefined || percent === "") return null;
  const parsed = typeof percent === "number" ? percent : Number.parseFloat(percent);
  if (Number.isNaN(parsed)) return null;
  const sign = parsed > 0 ? "+" : "";
  return `${sign}${usd.format(parsed)}%`;
}

const MONTH_NAME = new Intl.DateTimeFormat(LOCALE, {
  month: "long",
  year: "numeric",
  timeZone: "UTC",
});
const DAY_SHORT = new Intl.DateTimeFormat(LOCALE, {
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});

/** "2026-08" -> "August 2026"; unknown input is returned unchanged. */
export function formatMonth(month: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(month);
  if (!match) return month;
  const index = Number.parseInt(match[2] ?? "", 10) - 1;
  if (index < 0 || index > 11) return month;
  return MONTH_NAME.format(Date.UTC(Number(match[1]), index, 1));
}

/** "2026-08-14" -> "Aug 14". */
export function formatDayShort(day: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  if (!match) return day;
  const date = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return Number.isNaN(date) ? day : DAY_SHORT.format(date);
}

/** "2026-08-01", "2026-08-14" -> "Aug 1 to Aug 14". */
export function formatDayRange(start: string, end: string): string {
  return start === end
    ? formatDayShort(start)
    : `${formatDayShort(start)} to ${formatDayShort(end)}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "-";
  if (seconds < 59.95) return `${seconds.toFixed(1)}s`;
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}m ${total % 60}s`;
}
