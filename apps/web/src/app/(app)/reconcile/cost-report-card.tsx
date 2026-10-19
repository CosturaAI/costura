import { BreakdownTable } from "@/components/breakdown-table";
import { CardHeading } from "@/components/card-heading";
import { QueryChips } from "@/components/query-chips";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { BREAKDOWN_DIMENSIONS, type Reconcile } from "@/lib/api";

const DIMENSION_OPTIONS = BREAKDOWN_DIMENSIONS.map((value) => ({
  value,
  label: value.replace("_", " "),
}));

/** The provider's own cost report for the period, by the chosen dimension, before any
 * attribution: the figures the checks above compare against. */
export function CostReportCard({
  by,
  report,
  currency,
}: {
  by: string;
  report: Reconcile;
  currency: string;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div>
          <CardHeading>Cost report by {by.replace("_", " ")}</CardHeading>
          <CardDescription>
            Straight from the provider cost report, before any attribution.
          </CardDescription>
        </div>
        <QueryChips name="by" value={by} options={DIMENSION_OPTIONS} label="Dimension" size="sm" />
      </CardHeader>
      <CardContent className="p-0">
        <BreakdownTable
          rows={report.breakdown}
          dimension={by}
          total={report.costura_total}
          currency={currency}
        />
      </CardContent>
    </Card>
  );
}
