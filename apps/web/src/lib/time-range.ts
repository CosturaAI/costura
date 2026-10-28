import { LOCALE } from "@/lib/format";

export type QueryInterval = "day" | "week" | "month";
export type TimeFramePreset =
  | "this_month"
  | "last_month"
  | "last_7_days"
  | "last_30_days"
  | "last_90_days"
  | "rolling_7_days"
  | "rolling_30_days"
  | "rolling_90_days"
  | "quarter"
  | "ytd"
  | "custom";

export type DateRange = { from: string; to: string };

const DATE = /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/;

export function validDate(value: string | null | undefined): value is string {
  if (!value || !DATE.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

/** The API's bounds (`apps/api/costura/api/deps.py`): 2000-2099, at most 3660 days, 400 on the
 * public sample. A range outside them would answer 422, so the view never holds one. */
export const MAX_RANGE_DAYS = 3660;
export const SAMPLE_MAX_RANGE_DAYS = 400;
const FIRST_DAY = "2000-01-01";
const LAST_DAY = "2099-12-31";

export function validRange(
  from: string | null | undefined,
  to: string | null | undefined,
  longest: number = MAX_RANGE_DAYS,
): boolean {
  if (!validDate(from) || !validDate(to) || from > to) return false;
  if (from < FIRST_DAY || to > LAST_DAY) return false;
  const days = (Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000 + 1;
  return days <= longest;
}

export function monthRange(month: string): DateRange {
  const [year = 0, monthNumber = 1] = month.split("-").map(Number);
  const from = `${year}-${String(monthNumber).padStart(2, "0")}-01`;
  const to = isoDate(new Date(Date.UTC(year, monthNumber, 0)));
  return { from, to };
}

export function autoInterval(from: string, to: string): QueryInterval {
  const days = differenceInDays(from, to) + 1;
  if (days <= 62) return "day";
  if (days <= 365) return "week";
  return "month";
}

export function presetRange(preset: TimeFramePreset, today = new Date()): DateRange {
  const day = utcDay(today);
  if (preset === "this_month") {
    return {
      from: isoDate(new Date(Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), 1))),
      to: isoDate(day),
    };
  }
  if (preset === "last_month") {
    const from = new Date(Date.UTC(day.getUTCFullYear(), day.getUTCMonth() - 1, 1));
    const to = new Date(Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), 0));
    return { from: isoDate(from), to: isoDate(to) };
  }
  if (preset === "quarter") {
    const quarterMonth = Math.floor(day.getUTCMonth() / 3) * 3;
    return {
      from: isoDate(new Date(Date.UTC(day.getUTCFullYear(), quarterMonth, 1))),
      to: isoDate(day),
    };
  }
  if (preset === "ytd") {
    return { from: `${day.getUTCFullYear()}-01-01`, to: isoDate(day) };
  }
  const length = preset.endsWith("7_days") ? 7 : preset.endsWith("30_days") ? 30 : 90;
  const rolling = preset.startsWith("rolling_");
  const to = new Date(day);
  if (!rolling) to.setUTCDate(to.getUTCDate() - 1);
  const from = new Date(to);
  from.setUTCDate(from.getUTCDate() - length + 1);
  return { from: isoDate(from), to: isoDate(to) };
}

export function rangeLabel(from: string, to: string): string {
  return from === to ? from : `${from} to ${to}`;
}

const MONTH_YEAR = new Intl.DateTimeFormat(LOCALE, {
  month: "long",
  year: "numeric",
  timeZone: "UTC",
});
const SHORT_DATE = new Intl.DateTimeFormat(LOCALE, {
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});
const SHORT_DATE_YEAR = new Intl.DateTimeFormat(LOCALE, {
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
});

export function shortRangeLabel(from: string, to: string, today = new Date()): string {
  const sameYear = from.slice(0, 4) === to.slice(0, 4);
  const currentYear = sameYear && to.slice(0, 4) === String(today.getUTCFullYear());
  const format = (value: string, withYear: boolean) =>
    (withYear ? SHORT_DATE_YEAR : SHORT_DATE).format(new Date(`${value}T00:00:00Z`));
  if (from === to) return format(from, !currentYear);
  return `${format(from, !sameYear)} - ${format(to, !currentYear)}`;
}

export function wholeMonth(from: string, to: string): string | null {
  const month = from.slice(0, 7);
  if (!from.endsWith("-01") || to.slice(0, 7) !== month) return null;
  return monthRange(month).to === to ? month : null;
}

/** The month of a range that runs from its 1st to today: the month so far, which the overview
 * reads as the month view (month-to-date comparison) rather than as a free range. */
export function monthToDate(from: string, to: string, today = new Date()): string | null {
  const month = from.slice(0, 7);
  if (!from.endsWith("-01") || to.slice(0, 7) !== month) return null;
  return to === isoDate(utcDay(today)) ? month : null;
}

export function monthsIn(from: string, to: string): string[] {
  const months: string[] = [];
  let [year, month] = to.slice(0, 7).split("-").map(Number);
  const first = from.slice(0, 7);
  for (;;) {
    const value = `${year}-${String(month).padStart(2, "0")}`;
    if (value < first) break;
    months.push(value);
    month! -= 1;
    if (month === 0) {
      month = 12;
      year! -= 1;
    }
  }
  return months;
}

export function periodPhrase(from: string, to: string, today = new Date()): string {
  const month = wholeMonth(from, to);
  if (month) return `in ${MONTH_YEAR.format(new Date(`${month}-01T00:00:00Z`))}`;
  if (from === to) return `on ${shortRangeLabel(from, to, today)}`;
  const [start, end] = shortRangeLabel(from, to, today).split(" - ");
  return `from ${start} to ${end}`;
}

export function periodTitle(from: string, to: string, today = new Date()): string {
  const month = wholeMonth(from, to);
  if (month) return MONTH_YEAR.format(new Date(`${month}-01T00:00:00Z`));
  return shortRangeLabel(from, to, today);
}

export function rangeDays(from: string, to: string): number {
  return differenceInDays(from, to) + 1;
}

/** The period the API compares `period` with (`previous_window` in `spend/window.py`): the
 * previous calendar month for a whole month, otherwise the same number of days right before.
 * A month in progress compares fewer days; `summary` returns them. */
export function previousPeriod(period: DateRange): DateRange {
  const month = wholeMonth(period.from, period.to);
  if (month) {
    const [year, number] = month.split("-").map(Number);
    const prior =
      number === 1 ? `${year! - 1}-12` : `${year}-${String(number! - 1).padStart(2, "0")}`;
    return monthRange(prior);
  }
  const days = rangeDays(period.from, period.to);
  const start = new Date(`${period.from}T00:00:00Z`);
  const to = isoDate(new Date(start.getTime() - 86_400_000));
  const from = isoDate(new Date(start.getTime() - days * 86_400_000));
  return { from, to };
}

/** "Daily", "Weekly", "Monthly"; lowercase with `{ lower: true }`. */
export function intervalLabel(interval: QueryInterval, options: { lower?: boolean } = {}): string {
  const label = interval === "day" ? "Daily" : interval === "week" ? "Weekly" : "Monthly";
  return options.lower ? label.toLowerCase() : label;
}

function differenceInDays(from: string, to: string): number {
  return Math.round(
    (new Date(`${to}T00:00:00Z`).getTime() - new Date(`${from}T00:00:00Z`).getTime()) / 86_400_000,
  );
}

function utcDay(value: Date): Date {
  return new Date(Date.UTC(value.getUTCFullYear(), value.getUTCMonth(), value.getUTCDate()));
}

function isoDate(value: Date): string {
  return value.toISOString().slice(0, 10);
}
