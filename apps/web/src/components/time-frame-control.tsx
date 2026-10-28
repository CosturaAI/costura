"use client";

import { useState, useTransition } from "react";
import { CalendarIcon, ChevronDownIcon } from "lucide-react";

import { setViewAction } from "@/actions/view";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  autoInterval,
  presetRange,
  rangeDays,
  shortRangeLabel,
  validDate,
  validRange,
  type TimeFramePreset,
} from "@/lib/time-range";

type Window = 7 | 30 | 90;

const CALENDAR: { value: TimeFramePreset; label: string }[] = [
  { value: "this_month", label: "This month" },
  { value: "last_month", label: "Last month" },
  { value: "quarter", label: "This quarter" },
  { value: "ytd", label: "Year to date" },
];

const WINDOWS: Window[] = [7, 30, 90];

const LAST: Record<Window, { complete: TimeFramePreset; rolling: TimeFramePreset }> = {
  7: { complete: "last_7_days", rolling: "rolling_7_days" },
  30: { complete: "last_30_days", rolling: "rolling_30_days" },
  90: { complete: "last_90_days", rolling: "rolling_90_days" },
};

const PRESETS: TimeFramePreset[] = [
  ...CALENDAR.map((preset) => preset.value),
  ...WINDOWS.flatMap((days) => [LAST[days].complete, LAST[days].rolling]),
];

const presetClass =
  "aria-pressed:border-primary aria-pressed:bg-primary/10 aria-pressed:text-foreground";

export function TimeFrameControl({ from, to }: { from: string; to: string }) {
  const [pending, startTransition] = useTransition();
  const [open, setOpen] = useState(false);
  const selected = matchingPreset(from, to);
  const [includeToday, setIncludeToday] = useState(isRolling(selected));
  const [draftFrom, setDraftFrom] = useState(from);
  const [draftTo, setDraftTo] = useState(to);
  const selectedWindow = windowOf(selected);
  const label = presetLabel(selected);
  const range = shortRangeLabel(from, to);
  const draftValid = validRange(draftFrom, draftTo);

  function openChange(next: boolean) {
    if (next) {
      setDraftFrom(from);
      setDraftTo(to);
      setIncludeToday(isRolling(selected));
    }
    setOpen(next);
  }

  function apply(preset: TimeFramePreset) {
    setOpen(false);
    const next = presetRange(preset);
    startTransition(() =>
      setViewAction({ ...next, interval: autoInterval(next.from, next.to), timeFrame: preset }),
    );
  }

  function chooseWindow(days: Window, rolling = includeToday) {
    apply(rolling ? LAST[days].rolling : LAST[days].complete);
  }

  function toggleToday(checked: boolean) {
    setIncludeToday(checked);
    if (selectedWindow) chooseWindow(selectedWindow, checked);
  }

  function applyCustom() {
    if (!draftValid) return;
    setOpen(false);
    startTransition(() =>
      setViewAction({
        from: draftFrom,
        to: draftTo,
        interval: autoInterval(draftFrom, draftTo),
        timeFrame: null,
      }),
    );
  }

  return (
    <Popover open={open} onOpenChange={openChange}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          aria-label={`Time frame: ${label} ${range}`}
          aria-busy={pending || undefined}
          aria-disabled={pending || undefined}
          onClick={(event) => {
            if (pending) event.preventDefault();
          }}
          className="max-w-full min-w-0 shrink justify-start font-normal"
        >
          <CalendarIcon className="text-muted-foreground" />
          <span className={selected === "custom" ? "sr-only sm:not-sr-only" : "truncate"}>
            {label}
          </span>{" "}
          <span
            className={
              selected === "custom" ? "truncate" : "hidden truncate text-muted-foreground sm:inline"
            }
          >
            {range}
          </span>
          <ChevronDownIcon className="text-muted-foreground" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        aria-label="Time frame options"
        className="flex w-[min(20rem,calc(100vw-2rem))] flex-col gap-4"
      >
        <CalendarPresets selected={selected} onPick={apply} />
        <LastWindows
          selectedWindow={selectedWindow}
          includeToday={includeToday}
          onWindow={chooseWindow}
          onToday={toggleToday}
        />
        <CustomRange
          from={draftFrom}
          to={draftTo}
          onFrom={setDraftFrom}
          onTo={setDraftTo}
          pending={pending}
          onApply={applyCustom}
        />
      </PopoverContent>
    </Popover>
  );
}

function CalendarPresets({
  selected,
  onPick,
}: {
  selected: TimeFramePreset;
  onPick: (preset: TimeFramePreset) => void;
}) {
  return (
    <section aria-labelledby="time-frame-calendar" className="flex flex-col gap-1.5">
      <h3 id="time-frame-calendar" className="text-xs font-medium text-muted-foreground">
        Calendar
      </h3>
      <div className="grid grid-cols-2 gap-1.5">
        {CALENDAR.map((preset) => {
          const presetDates = presetRange(preset.value);
          return (
            <Button
              key={preset.value}
              type="button"
              variant="outline"
              aria-pressed={selected === preset.value}
              onClick={() => onPick(preset.value)}
              className={`h-auto flex-col items-start gap-0 py-1.5 ${presetClass}`}
            >
              <span>{preset.label}</span>
              <span className="text-xs font-normal text-muted-foreground">
                {shortRangeLabel(presetDates.from, presetDates.to)}
              </span>
            </Button>
          );
        })}
      </div>
    </section>
  );
}

function LastWindows({
  selectedWindow,
  includeToday,
  onWindow,
  onToday,
}: {
  selectedWindow: Window | null;
  includeToday: boolean;
  onWindow: (days: Window) => void;
  onToday: (checked: boolean) => void;
}) {
  const today = presetRange("rolling_7_days").to;
  const yesterday = presetRange("last_7_days").to;
  return (
    <section aria-labelledby="time-frame-last" className="flex flex-col gap-1.5">
      <h3 id="time-frame-last" className="text-xs font-medium text-muted-foreground">
        Last
      </h3>
      <div className="grid grid-cols-3 gap-1.5">
        {WINDOWS.map((days) => (
          <Button
            key={days}
            type="button"
            variant="outline"
            aria-pressed={selectedWindow === days}
            onClick={() => onWindow(days)}
            className={presetClass}
          >
            {days} days
          </Button>
        ))}
      </div>
      <label className="mt-1 flex items-center gap-2 text-sm">
        <Checkbox checked={includeToday} onCheckedChange={(checked) => onToday(checked === true)} />
        Include today
      </label>
      <p className="text-xs text-muted-foreground">
        {includeToday
          ? `Ends today, ${shortRangeLabel(today, today)}. Today's costs are still arriving.`
          : `Ends yesterday, ${shortRangeLabel(yesterday, yesterday)}. Complete days only.`}
      </p>
    </section>
  );
}

function CustomRange({
  from,
  to,
  onFrom,
  onTo,
  pending,
  onApply,
}: {
  from: string;
  to: string;
  onFrom: (value: string) => void;
  onTo: (value: string) => void;
  pending: boolean;
  onApply: () => void;
}) {
  const draftValid = validRange(from, to);
  const draftReversed = validDate(from) && validDate(to) && from > to;
  return (
    <section aria-labelledby="time-frame-custom" className="flex flex-col gap-1.5">
      <h3 id="time-frame-custom" className="text-xs font-medium text-muted-foreground">
        Custom range
      </h3>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(8.5rem,1fr))] gap-2">
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          From
          <Input
            type="date"
            value={from}
            max={validDate(to) ? to : undefined}
            aria-invalid={draftReversed || undefined}
            onChange={(event) => onFrom(event.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          To
          <Input
            type="date"
            value={to}
            min={validDate(from) ? from : undefined}
            aria-invalid={draftReversed || undefined}
            onChange={(event) => onTo(event.target.value)}
          />
        </label>
      </div>
      <p className="text-xs text-muted-foreground" aria-live="polite">
        {draftReversed
          ? "The start date is after the end date."
          : draftValid
            ? `${rangeDays(from, to)} days`
            : "Pick a start and an end date."}
      </p>
      <Button
        type="button"
        onClick={pending ? undefined : onApply}
        aria-disabled={pending || undefined}
        disabled={!draftValid}
        className="w-full"
      >
        Apply
      </Button>
    </section>
  );
}

function matchingPreset(from: string, to: string): TimeFramePreset {
  for (const preset of PRESETS) {
    const range = presetRange(preset);
    if (range.from === from && range.to === to) return preset;
  }
  return "custom";
}

function isRolling(preset: TimeFramePreset): boolean {
  return preset.startsWith("rolling_");
}

function windowOf(preset: TimeFramePreset): Window | null {
  for (const days of WINDOWS) {
    if (LAST[days].complete === preset || LAST[days].rolling === preset) return days;
  }
  return null;
}

function presetLabel(preset: TimeFramePreset): string {
  const calendar = CALENDAR.find((item) => item.value === preset);
  if (calendar) return calendar.label;
  const days = windowOf(preset);
  if (days) return isRolling(preset) ? `Last ${days} days + today` : `Last ${days} days`;
  return "Custom";
}
