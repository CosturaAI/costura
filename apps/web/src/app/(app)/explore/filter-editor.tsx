"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useMemo, useState } from "react";

import { CardHeading } from "@/components/card-heading";
import { FILTER_OPERATOR_LABELS } from "@/components/query-chips";
import { NativeSelect } from "@/components/ui/native-select";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { FilterOperator } from "@/lib/api";
import { encodeFilterClause } from "@/lib/query-export";
import { parseFilterParam } from "@/lib/search";

const OPERATORS = Object.keys(FILTER_OPERATOR_LABELS) as FilterOperator[];

export type FilterValueOption = { value: string; label: string };

export function FilterEditor({
  dimensions,
  defaultDimension,
  valueOptions,
}: {
  dimensions: readonly { value: string; label: string }[];
  defaultDimension: string;
  valueOptions: Record<string, FilterValueOption[]>;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [dimension, setDimension] = useState(defaultDimension);
  const [operator, setOperator] = useState<FilterOperator>("is");
  const [value, setValue] = useState("");
  const takesValues = operator !== "exists" && operator !== "not_exists";
  const takesMultipleValues = operator === "one_of" || operator === "not_one_of";
  const suggestions = useMemo(() => valueOptions[dimension] ?? [], [dimension, valueOptions]);

  function resolveValue(raw: string): string {
    const normalized = raw.trim().toLocaleLowerCase();
    return (
      suggestions.find((item) => item.label.trim().toLocaleLowerCase() === normalized)?.value ??
      raw.trim()
    );
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = !takesValues
      ? []
      : takesMultipleValues
        ? value.split(",").map(resolveValue).filter(Boolean)
        : [resolveValue(value)].filter(Boolean);
    if (takesValues && values.length === 0) return;
    const clause = encodeFilterClause(dimension, { op: operator, values });
    const params = new URLSearchParams(searchParams.toString());
    const preserved = params
      .getAll("f")
      .filter((raw) => parseFilterParam(raw)?.dimension !== dimension);
    params.delete("f");
    preserved.forEach((raw) => params.append("f", raw));
    params.append("f", clause);
    router.push(`${pathname}?${params.toString()}`);
  }

  return (
    <Card>
      <CardHeader>
        <CardHeading>Add filter</CardHeading>
        <CardDescription>
          Match a dimension with an operator. Separate multiple values with commas.
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
              onChange={(event) => setOperator(event.target.value as FilterOperator)}
              className="min-w-40"
            >
              {OPERATORS.map((item) => (
                <option key={item} value={item}>
                  {FILTER_OPERATOR_LABELS[item]}
                </option>
              ))}
            </NativeSelect>
          </label>
          <label
            htmlFor="explore-filter-value"
            className="grid min-w-56 flex-1 gap-1 text-xs text-muted-foreground"
          >
            Value
            <Input
              id="explore-filter-value"
              value={value}
              onChange={(event) => setValue(event.target.value)}
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
          <Button type="submit">Add filter</Button>
        </form>
      </CardContent>
    </Card>
  );
}
