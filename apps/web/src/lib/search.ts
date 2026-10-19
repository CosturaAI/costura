import type { FilterClause, FilterOperator, UsageFilters } from "@/lib/api";

export type Search = Record<string, string | string[] | undefined>;
const FILTER_KEYS = [
  "api_key",
  "account",
  "creator",
  "workspace",
  "model",
  "provider",
  "origin",
  "person",
  "provider_account",
  "model_brand",
  "model_family",
  "model_name",
  "model_channel",
  "model_lifecycle",
  "token_type",
] as const;
const FILTER_OPERATORS = new Set<FilterOperator>([
  "is",
  "is_not",
  "one_of",
  "not_one_of",
  "contains",
  "not_contains",
  "exists",
  "not_exists",
]);

export function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** Picks `value` when it is one of `allowed`, else `fallback`. */
export function oneOf<T extends string>(
  value: string | undefined,
  allowed: readonly T[],
  fallback: T,
): T {
  return (allowed as readonly string[]).includes(value ?? "") ? (value as T) : fallback;
}

export function positiveInt(value: string | undefined, max = Number.MAX_SAFE_INTEGER) {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isInteger(parsed) && parsed > 0 && parsed <= max ? parsed : undefined;
}

export function parseFilterParam(raw: string): { dimension: string; clause: FilterClause } | null {
  const parts = raw.split(":");
  const opIndex = 1;
  if (parts.length <= opIndex + 1) return null;
  const dimension = parts[0]!;
  const op = parts[opIndex] as FilterOperator;
  if (
    !FILTER_OPERATORS.has(op) ||
    !FILTER_KEYS.includes(dimension as (typeof FILTER_KEYS)[number])
  ) {
    return null;
  }
  const rawValues = parts.slice(opIndex + 1).join(":");
  const values = op === "exists" || op === "not_exists" ? [] : rawValues.split(",");
  if (
    ((op === "exists" || op === "not_exists") && rawValues !== "") ||
    (!(op === "exists" || op === "not_exists") && values.some((value) => !value))
  ) {
    return null;
  }
  return { dimension, clause: { op, values } };
}

/** Drill-down filters present in the query string as repeatable `f` clauses. */
export function filtersFrom(query: Search): UsageFilters {
  const filters: UsageFilters = {};
  const clauses = query.f === undefined ? [] : Array.isArray(query.f) ? query.f : [query.f];
  for (const raw of clauses) {
    const parsed = parseFilterParam(raw);
    if (parsed) filters[parsed.dimension as keyof UsageFilters] = parsed.clause;
  }
  return filters;
}
