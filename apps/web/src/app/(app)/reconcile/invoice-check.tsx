import { InvoiceForm } from "@/components/invoice-form";
import type { Invoice, Reconcile } from "@/lib/api";
import { formatUsd } from "@/lib/format";

import { CheckRow, type Verdict } from "./reconcile-parts";

/** Costura's month total against the invoice total an owner typed in, with the form to enter
 * or change it. Invoices cover calendar months, so another range only explains that. */
export function InvoiceCheck({
  report,
  month,
  invoice,
  provider,
  formAccount,
  currency,
  isDemo,
}: {
  report: Reconcile;
  month: string | null;
  invoice: Invoice | null;
  provider: string;
  formAccount: number | null;
  currency: string;
  isDemo: boolean;
}) {
  const fromInvoice = report.reported_source === "invoice";
  const invoiceVerdict: Verdict = fromInvoice ? (report.matches ? "pass" : "fail") : "pending";
  return (
    <CheckRow title="Costura total matches the invoice" verdict={invoiceVerdict}>
      {!month ? (
        <>Invoices cover calendar months; pick one month to compare with its invoice.</>
      ) : fromInvoice ? (
        <>
          The {month} invoice says{" "}
          <span className="font-mono text-foreground">{formatUsd(report.reported_total)}</span>{" "}
          {currency}
          {report.matches ? (
            <>, the same as Costura to the cent.</>
          ) : (
            <>
              ; Costura differs by{" "}
              <span className="font-mono text-foreground">{formatUsd(report.delta)}</span>
              {report.delta_percent ? ` (${report.delta_percent}%)` : ""}. Tax, credits and the
              provider restating the last days of the month explain most differences.
            </>
          )}
          {invoice?.note ? ` Note: ${invoice.note}.` : ""}
        </>
      ) : (
        <>
          No invoice total for {month} yet. The provider API reports usage, not the bill; an owner
          types the total in from the invoice
          {report.accounts.length > 1 ? ", one per account" : ""}.
        </>
      )}
      {month && !isDemo ? (
        formAccount !== null ? (
          <InvoiceForm
            provider={provider}
            accountId={formAccount}
            month={month}
            current={invoice}
          />
        ) : (
          <span className="mt-2 block">Choose an account above to enter its invoice.</span>
        )
      ) : null}
    </CheckRow>
  );
}
