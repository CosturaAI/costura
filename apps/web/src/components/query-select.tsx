"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

/** Writes one query parameter (`?by=`, `?include_missing=`) and lets the server page re-render. */
export function QuerySelect({
  name,
  value,
  options,
  label,
  emptyValue,
}: {
  name: string;
  value: string;
  options: readonly { value: string; label: string }[];
  label: string;
  /** Selecting this value removes the parameter instead of writing it. */
  emptyValue?: string;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  function onChange(next: string | null) {
    if (!next || next === value) return;
    const params = new URLSearchParams(searchParams.toString());
    if (emptyValue !== undefined && next === emptyValue) params.delete(name);
    else params.set(name, next);
    const query = params.toString();
    router.push(query ? `${pathname}?${query}` : pathname);
  }

  return (
    <label className="flex items-center gap-2 text-sm text-muted-foreground">
      {label}
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger aria-label={label} className="w-40">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </label>
  );
}
