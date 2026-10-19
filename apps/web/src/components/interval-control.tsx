"use client";

import { useTransition } from "react";

import { setViewAction } from "@/actions/view";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { QueryInterval } from "@/lib/time-range";

const OPTIONS: { value: QueryInterval; label: string }[] = [
  { value: "day", label: "Daily" },
  { value: "week", label: "Weekly" },
  { value: "month", label: "Monthly" },
];

export function IntervalControl({ interval }: { interval: QueryInterval }) {
  const [pending, startTransition] = useTransition();

  function change(value: string) {
    if (pending || value === interval) return;
    startTransition(() => setViewAction({ interval: value as QueryInterval }));
  }

  return (
    <Select value={interval} onValueChange={change}>
      <SelectTrigger
        aria-label="Interval"
        aria-busy={pending || undefined}
        aria-disabled={pending || undefined}
        className="w-24 sm:w-28"
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {OPTIONS.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
