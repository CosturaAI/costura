"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { type MouseEvent, useEffect, useOptimistic, useTransition } from "react";

import type { FilterClause, FilterOperator } from "@/lib/api";
import { parseFilterParam } from "@/lib/search";
import { cn } from "@/lib/utils";
import { NativeSelect } from "@/components/ui/native-select";

function withParam(
  pathname: string,
  current: URLSearchParams,
  name: string,
  value: string | null,
): string {
  const params = new URLSearchParams(current.toString());
  if (value === null) params.delete(name);
  else params.set(name, value);
  const query = params.toString();
  return query ? `${pathname}?${query}` : pathname;
}

function withoutFilter(pathname: string, current: URLSearchParams, name: string): string {
  const params = new URLSearchParams(current.toString());
  const clauses = params.getAll("f").filter((raw) => parseFilterParam(raw)?.dimension !== name);
  params.delete("f");
  clauses.forEach((clause) => params.append("f", clause));
  const query = params.toString();
  return query ? `${pathname}?${query}` : pathname;
}

/** Drops every filter parameter and keeps view parameters such as `by` and `top`. */
function withoutFilters(pathname: string, current: URLSearchParams): string {
  const params = new URLSearchParams(current.toString());
  params.delete("f");
  const query = params.toString();
  return query ? `${pathname}?${query}` : pathname;
}

/**
 * The query of a navigation that has started but not committed. Two controls clicked before
 * the first navigation lands must compose (`?by=model` then `&top=25`), so they build on this
 * instead of `window.location`, which only changes on commit. Writing it to the history entry
 * instead would leave a duplicate entry behind the pushed one.
 */
let pendingSearch: string | null = null;

function remember(href: string): string {
  const index = href.indexOf("?");
  pendingSearch = index === -1 ? "" : href.slice(index);
  return href;
}

function currentParams(fallback: URLSearchParams): URLSearchParams {
  if (typeof window === "undefined") return new URLSearchParams(fallback.toString());
  return new URLSearchParams(pendingSearch ?? window.location.search);
}

/** Forget the pending query once the URL the router renders has caught up. */
function useCommittedSearch(searchParams: URLSearchParams) {
  useEffect(() => {
    pendingSearch = null;
  }, [searchParams]);
}

function isPlainClick(event: MouseEvent<HTMLAnchorElement>): boolean {
  return event.button === 0 && !event.altKey && !event.ctrlKey && !event.metaKey && !event.shiftKey;
}

export const FILTER_OPERATOR_LABELS: Record<FilterOperator, string> = {
  is: "is",
  is_not: "is not",
  one_of: "is one of",
  not_one_of: "is not one of",
  contains: "contains",
  not_contains: "does not contain",
  exists: "exists",
  not_exists: "does not exist",
};

/** Segmented control that writes one query parameter (`?by=`); the server page re-renders. */
export function QueryChips({
  name,
  value,
  options,
  label,
  size = "md",
}: {
  name: string;
  value: string;
  options: readonly { value: string; label: string }[];
  label: string;
  size?: "sm" | "md";
}) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [optimisticValue, setOptimisticValue] = useOptimistic(value);
  const [isPending, startTransition] = useTransition();

  useCommittedSearch(searchParams);

  function go(next: string) {
    const href = remember(withParam(pathname, currentParams(searchParams), name, next || null));
    startTransition(() => {
      setOptimisticValue(next);
      router.push(href);
    });
  }

  function select(event: MouseEvent<HTMLAnchorElement>, next: string) {
    if (!isPlainClick(event)) return;
    event.preventDefault();
    go(next);
  }

  // Both presentations render; CSS picks one at the breakpoint, so the server's first paint
  // already matches the viewport and nothing swaps after hydration.
  return (
    <>
      <label className={cn("sm:hidden", isPending && "opacity-75")}>
        <span className="sr-only">{label}</span>
        <NativeSelect
          aria-label={label}
          className="max-w-full"
          value={optimisticValue}
          onChange={(event) => go(event.target.value)}
        >
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </NativeSelect>
      </label>
      <QueryChipLinks
        name={name}
        label={label}
        size={size}
        options={options}
        value={optimisticValue}
        pending={isPending}
        onSelect={select}
      />
    </>
  );
}

function QueryChipLinks({
  name,
  label,
  size,
  options,
  value,
  pending,
  onSelect,
}: {
  name: string;
  label: string;
  size: "sm" | "md";
  options: readonly { value: string; label: string }[];
  value: string;
  pending: boolean;
  onSelect: (event: MouseEvent<HTMLAnchorElement>, next: string) => void;
}) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const optimisticValue = value;
  return (
    <div
      role="group"
      aria-label={label}
      aria-busy={pending}
      className={cn("hidden flex-wrap items-center gap-1 sm:flex", pending && "opacity-75")}
    >
      {options.map((option) => {
        const active = option.value === optimisticValue;
        return (
          <Link
            key={option.value}
            href={withParam(pathname, searchParams, name, option.value || null)}
            onClick={(event) => onSelect(event, option.value)}
            aria-current={active ? "true" : undefined}
            className={cn(
              "inline-flex items-center rounded-full border font-medium transition-colors",
              size === "sm" ? "min-h-7 px-2.5 text-xs" : "min-h-9 px-3 text-sm",
              active
                ? "border-primary bg-primary text-on-solid"
                : "border-border bg-card text-muted-foreground hover:border-primary hover:text-foreground",
            )}
          >
            {option.label}
          </Link>
        );
      })}
    </div>
  );
}

/** Active drill-down filters as removable chips; removing one drops its query parameter. */
export function FilterChips({
  filters,
  labels,
}: {
  filters: { name: string; clause: FilterClause; label: string }[];
  labels: Record<string, string>;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [isPending, startTransition] = useTransition();
  useCommittedSearch(searchParams);
  if (filters.length === 0) return null;

  function remove(event: MouseEvent<HTMLAnchorElement>, name: string) {
    if (!isPlainClick(event)) return;
    event.preventDefault();
    const href = remember(withoutFilter(pathname, currentParams(searchParams), name));
    startTransition(() => router.push(href));
  }

  function clear(event: MouseEvent<HTMLAnchorElement>) {
    if (!isPlainClick(event)) return;
    event.preventDefault();
    const href = remember(withoutFilters(pathname, currentParams(searchParams)));
    startTransition(() => router.push(href));
  }

  return (
    <div
      className={cn("flex flex-wrap items-center gap-1.5", isPending && "opacity-75")}
      aria-label="Active filters"
      aria-busy={isPending}
    >
      {filters.map((filter) => (
        <Link
          key={`${filter.name}:${filter.clause.op}:${filter.clause.values.join(",")}`}
          href={withoutFilter(pathname, searchParams, filter.name)}
          onClick={(event) => remove(event, filter.name)}
          className="inline-flex min-h-7 items-center gap-1.5 rounded-full border border-primary bg-accent px-2.5 text-xs text-primary hover:bg-accent"
          title={`Remove filter ${labels[filter.name] ?? filter.name}`}
        >
          <span className="max-w-80 truncate">
            <span className="text-primary">{labels[filter.name] ?? filter.name}</span>
            {` ${FILTER_OPERATOR_LABELS[filter.clause.op]}${filter.label ? ` ${filter.label}` : ""}`}
          </span>
          <span aria-hidden className="text-primary">
            x
          </span>
        </Link>
      ))}
      <Link
        href={withoutFilters(pathname, searchParams)}
        onClick={clear}
        className="text-xs text-muted-foreground hover:text-foreground hover:underline"
      >
        clear all
      </Link>
    </div>
  );
}
