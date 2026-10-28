"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useMemo, useState } from "react";

import { CardHeading } from "@/components/card-heading";
import { FieldError } from "@/components/form-feedback";
import { FILTER_OPERATOR_LABELS } from "@/components/query-chips";
import { NativeSelect } from "@/components/ui/native-select";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { FilterClause, FilterOperator } from "@/lib/api";
import { encodeFilterClause } from "@/lib/query-export";
import { parseFilterParam } from "@/lib/search";

const OPERATORS = Object.keys(FILTER_OPERATOR_LABELS) as FilterOperator[];

export type FilterValueOption = { value: string; label: string };

const POSITIVE: readonly FilterOperator[] = ["is", "one_of"];
const NEGATIVE: readonly FilterOperator[] = ["is_not", "not_one_of"];

/**
 * The clause a new filter leaves on its dimension. A dimension holds one clause, so a value
 * added with the same polarity as the existing clause joins it (`one_of` / `not_one_of`);
 * any other combination replaces it.
 */
export function mergeClause(existing: FilterClause | null, added: FilterClause): FilterClause {
  if (existing === null) return added;
  for (const [group, op] of [
    [POSITIVE, "one_of"],
    [NEGATIVE, "not_one_of"],
  ] as const) {
    if (group.includes(existing.op) && group.includes(added.op)) {
      const values = [...new Set([...existing.values, ...added.values])];
      return { op: values.length === 1 ? existing.op : op, values };
    }
  }
  return added;
}

/**
 * `valueOptions` lists the known values per dimension; a typed name resolves to its id. For a
 * dimension in `exhaustive` the list holds every value of the period, so a name that matches
 * none is refused instead of becoming a filter that matches nothing.
 */
export function FilterEditor({
  dimensions,
  defaultDimension,
  valueOptions,
  exhaustive = [],
}: {
  dimensions: readonly { value: string; label: string }[];
  defaultDimension: string;
  valueOptions: Record<string, FilterValueOption[]>;
  exhaustive?: readonly string[];
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [dimension, setDimension] = useState(defaultDimension);
  const [operator, setOperator] = useState<FilterOperator>("is");
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const takesValues = operator !== "exists" && operator !== "not_exists";
  const takesMultipleValues = operator === "one_of" || operator === "not_one_of";
  const suggestions = useMemo(() => valueOptions[dimension] ?? [], [dimension, valueOptions]);

  const matchesValues = operator !== "contains" && operator !== "not_contains";
  const dimensionLabel =
    dimensions.find((item) => item.value === dimension)?.label.toLocaleLowerCase() ?? dimension;

  function resolveValue(raw: string): string | null {
    const trimmed = raw.trim();
    const normalized = trimmed.toLocaleLowerCase();
    const match =
      suggestions.find((item) => item.label.trim().toLocaleLowerCase() === normalized) ??
      suggestions.find((item) => item.value === trimmed);
    if (match) return match.value;
    return matchesValues && exhaustive.includes(dimension) ? null : trimmed;
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const raws = !takesValues
      ? []
      : (takesMultipleValues ? value.split(",") : [value]).filter((raw) => raw.trim());
    const unknown = raws.find((raw) => resolveValue(raw) === null);
    if (unknown !== undefined) {
      setError(`No ${dimensionLabel} named ${unknown.trim()} in this period.`);
      return;
    }
    const values = raws.map((raw) => resolveValue(raw)!);
    if (takesValues && values.length === 0) return;
    setError(null);
    const params = new URLSearchParams(searchParams.toString());
    const others: string[] = [];
    let existing: FilterClause | null = null;
    for (const raw of params.getAll("f")) {
      const parsed = parseFilterParam(raw);
      if (parsed?.dimension === dimension) existing = parsed.clause;
      else others.push(raw);
    }
    params.delete("f");
    others.forEach((raw) => params.append("f", raw));
    params.append(
      "f",
      encodeFilterClause(dimension, mergeClause(existing, { op: operator, values })),
    );
    router.push(`${pathname}?${params.toString()}`);
  }

  return (
    <Card>
      <CardHeader>
        <CardHeading>Add filter</CardHeading>
        <CardDescription>
          Match a dimension with an operator. Separate multiple values with commas. A value added to
          a dimension with a filter of the same kind (is, is not) joins it; any other filter on that
          dimension is replaced.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form className="flex flex-wrap items-end gap-3" onSubmit={submit}>
          <label
            htmlFor="explore-filter-dimension"
            className="grid gap-1 text-xs text-muted-foreground"
          >
            Dimension
            <NativeSelect
              id="explore-filter-dimension"
              value={dimension}
              onChange={(event) => {
                setDimension(event.target.value);
                setValue("");
                setError(null);
              }}
              className="min-w-44"
            >
              {dimensions.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </NativeSelect>
          </label>
          <label
            htmlFor="explore-filter-operator"
            className="grid gap-1 text-xs text-muted-foreground"
          >
            Operator
            <NativeSelect
              id="explore-filter-operator"
              value={operator}
              onChange={(event) => {
                setOperator(event.target.value as FilterOperator);
                setError(null);
              }}
              className="min-w-40"
            >
              {OPERATORS.map((item) => (
                <option key={item} value={item}>
                  {FILTER_OPERATOR_LABELS[item]}
                </option>
              ))}
            </NativeSelect>
          </label>
          <div className="min-w-56 flex-1">
            <label
              htmlFor="explore-filter-value"
              className="grid gap-1 text-xs text-muted-foreground"
            >
              Value
              <Input
                id="explore-filter-value"
                value={value}
                onChange={(event) => {
                  setValue(event.target.value);
                  setError(null);
                }}
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? "explore-filter-value_error" : undefined}
                placeholder={takesMultipleValues ? "value-a, value-b" : "Filter value"}
                list={suggestions.length > 0 ? "explore-filter-values" : undefined}
                required={takesValues}
                disabled={!takesValues}
                pattern={takesValues && !takesMultipleValues ? "[^,]+" : undefined}
                title={
                  takesValues && !takesMultipleValues
                    ? "Use one value without a comma for this operator."
                    : undefined
                }
                maxLength={takesMultipleValues ? 4019 : 200}
                className="h-9"
              />
              {suggestions.length > 0 ? (
                <datalist id="explore-filter-values">
                  {suggestions.map((item) => (
                    <option key={item.value} value={item.label} label={item.value} />
                  ))}
                </datalist>
              ) : null}
            </label>
            <FieldError
              state={{ ok: false, field: "value", message: error }}
              field="value"
              id="explore-filter-value_error"
            />
          </div>
          <Button type="submit">Add filter</Button>
        </form>
      </CardContent>
    </Card>
  );
}
