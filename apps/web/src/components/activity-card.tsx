import { CardHeading } from "@/components/card-heading";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import type { ActivityRow } from "@/lib/api";
import { formatInteger, formatQuantity, formatUnitCost, formatUsd } from "@/lib/format";

function label(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

const quantity = formatQuantity;
const unitCost = formatUnitCost;

export function ActivityCard({ rows }: { rows: ActivityRow[] }) {
  if (rows.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardHeading>Activity</CardHeading>
        <CardDescription>
          OpenAI non-completions usage matched to billed cost for the selected scope.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="divide-y divide-border text-sm">
          {rows.map((row) => (
            <li
              key={`${row.family}:${row.unit}`}
              className="grid gap-1 py-3 sm:grid-cols-[1.4fr_1fr_1fr_1fr]"
            >
              <span className="font-medium">{label(row.family)}</span>
              <span>
                {quantity(row.quantity)} {row.unit.replace("_", " ")}
              </span>
              <span>{formatInteger(row.requests)} requests</span>
              <span className="text-muted-foreground">
                {formatUsd(row.billed_usd)} USD
                {row.cost_per_unit ? ` (${unitCost(row.cost_per_unit)} per ${row.unit})` : ""}
              </span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
