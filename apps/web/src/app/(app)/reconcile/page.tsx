import { Metadata } from "next";
import { AreaNav, DATA_HEALTH } from "@/components/area-nav";
import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { QueryChips } from "@/components/query-chips";
import { Card, CardContent } from "@/components/ui/card";

import { BREAKDOWN_DIMENSIONS, api, type Invoice } from "@/lib/api";
import { formatUsd } from "@/lib/format";
import { periodPhrase, periodTitle, wholeMonth } from "@/lib/time-range";
import { isAll } from "@/lib/providers";
import { first, oneOf, positiveInt, type Search } from "@/lib/search";
import { syncAction } from "@/lib/setup";

import { requireView } from "@/lib/view";
import { CostReportCard } from "./cost-report-card";
import { InvoiceCheck } from "./invoice-check";
import { CheckRow, providerCards, providerTotalNote, type Verdict } from "./reconcile-parts";

export const metadata: Metadata = { title: "Reconciliation" };

export default async function ReconcilePage({ searchParams }: { searchParams: Promise<Search> }) {
  const { org, provider, period, timeFrame, organization } = await requireView();
  const query = await searchParams;
  const by = oneOf(first(query.by), BREAKDOWN_DIMENSIONS, "workspace");
  if (isAll(provider)) return providerCards(org, period, timeFrame, organization.is_demo);
  const inPeriod = periodPhrase(period.from, period.to);

  // `?account=` narrows the checks to one console of the provider; an id the provider does
  // not have falls back to every account together rather than a 404.
  const requested = positiveInt(first(query.account));
  const monthOfPeriod = wholeMonth(period.from, period.to);
  const invoicesRead = monthOfPeriod
    ? api.invoices(org, provider, monthOfPeriod).catch(() => null)
    : Promise.resolve(null);
  let report =
    requested === undefined
      ? await api.reconcile(org, provider, period, by)
      : await api.reconcile(org, provider, period, by, requested).catch(() => null);
  report ??= await api.reconcile(org, provider, period, by);
  const accountOptions =
    report.accounts.length > 1
      ? [
          { value: "", label: "All accounts" },
          ...report.accounts.map((a) => ({ value: String(a.id), label: a.label })),
        ]
      : null;
  const currency = report.currency ?? "USD";
  const hasCost = report.costura_total !== "0.00";
  const allocation = report.allocation;
  const providerCheck = report.provider_check;

  const providerVerdict: Verdict = providerCheck ? (providerCheck.ok ? "pass" : "fail") : "pending";
  const rawVerdict: Verdict = report.raw_check
    ? report.raw_check.ok
      ? "pass"
      : "fail"
    : "pending";
  const allocationVerdict: Verdict = allocation ? (allocation.ok ? "pass" : "fail") : "pending";
  const keyCheck = report.key_check;
  const keyVerdict: Verdict = keyCheck ? (keyCheck.ok ? "pass" : "fail") : "pending";
  const creditCheck = report.codex_credit_check;
  const creditVerdict: Verdict = creditCheck ? (creditCheck.ok ? "pass" : "fail") : "pending";
  const activityCoverage = report.activity_coverage;
  const month = wholeMonth(period.from, period.to);
  const formAccount =
    report.account_id ?? (report.accounts.length === 1 ? report.accounts[0]!.id : null);
  let invoice: Invoice | null = null;
  if (month && formAccount !== null) {
    const invoices = await invoicesRead;
    invoice = invoices?.items.find((item) => item.account_id === formAccount) ?? null;
  }
  const checkCount = ["Four", "Five", "Six", "Seven"][
    Number(report.key_check_supported) +
      Number(activityCoverage !== null) +
      Number(provider === "codex")
  ];
  const note = providerTotalNote(provider);

  return (
    <div className="space-y-5">
      <AreaNav label="Data health" items={DATA_HEALTH} current="/reconcile" />
      <PageHeader
        title={`Does ${periodTitle(period.from, period.to)} add up?`}
        description={`${checkCount} checks between the provider's own totals, what Costura stored, and what it attributed${report.account_label ? ` for the ${report.account_label} account` : accountOptions ? ", every account of the provider added up" : ""}. Every figure but the invoice total comes from the provider API.${note ? ` ${note}` : ""}`}
      />

      {accountOptions ? (
        <QueryChips
          name="account"
          value={report.account_id === null ? "" : String(report.account_id)}
          options={accountOptions}
          label="Account"
          size="sm"
        />
      ) : null}

      <Card>
        <CardContent className="py-1">
          <ul className="divide-y divide-border">
            <CheckRow title="Costura total matches the provider total" verdict={providerVerdict}>
              Costura has{" "}
              <span className="font-mono text-foreground">{formatUsd(report.costura_total)}</span>{" "}
              {currency} {inPeriod}
              {providerCheck ? (
                <>
                  {providerCheck.derived_seat_total !== "0.00" ? (
                    <>
                      , including{" "}
                      <span className="font-mono text-foreground">
                        {formatUsd(providerCheck.derived_seat_total)}
                      </span>{" "}
                      in derived seat costs
                    </>
                  ) : null}
                  ; {providerCheck.label} reports{" "}
                  <span className="font-mono text-foreground">
                    {formatUsd(providerCheck.provider_total)}
                  </span>
                  {providerCheck.ok ? (
                    <>
                      , the same usage figure to the cent
                      {providerCheck.derived_seat_total !== "0.00"
                        ? " after derived seats are excluded."
                        : "."}
                    </>
                  ) : (
                    <>
                      , a difference of{" "}
                      <span className="font-mono text-foreground">
                        {formatUsd(providerCheck.delta)}
                      </span>
                      . Tolerance is one cent.
                    </>
                  )}
                </>
              ) : (
                <>. No provider total for these days yet; it arrives with the next import.</>
              )}
            </CheckRow>
            <InvoiceCheck
              report={report}
              month={month}
              invoice={invoice}
              provider={provider}
              formAccount={formAccount}
              currency={currency}
              isDemo={organization.is_demo}
            />
            <CheckRow title="Stored rows match the provider report" verdict={rawVerdict}>
              {report.raw_check ? (
                <>
                  The last full cost sync returned{" "}
                  <span className="font-mono text-foreground">
                    {formatUsd(report.raw_check.raw_total)}
                  </span>{" "}
                  and the normalized rows sum to the same figure
                  {report.raw_check.ok ? "." : ` minus ${formatUsd(report.raw_check.delta)}.`}
                </>
              ) : (
                <>No import covers the whole period yet.</>
              )}
            </CheckRow>
            {provider === "codex" ? (
              <CheckRow title="Workspace credits match per-user credits" verdict={creditVerdict}>
                {creditCheck ? (
                  <>
                    Workspace usage reports{" "}
                    <span className="font-mono text-foreground">
                      {creditCheck.workspace_credits}
                    </span>{" "}
                    credits and user rows report{" "}
                    <span className="font-mono text-foreground">{creditCheck.user_credits}</span>.
                    {creditCheck.missing_price_days.length > 0
                      ? ` No credit price covers ${creditCheck.missing_price_days.join(", ")}.`
                      : " USD amounts are derived from the effective credit price schedule."}
                  </>
                ) : (
                  <>No Codex workspace and per-user imports cover the whole period yet.</>
                )}
              </CheckRow>
            ) : null}
            <CheckRow title="Attribution adds up to the cost" verdict={allocationVerdict}>
              {allocation ? (
                <>
                  <span className="font-mono text-foreground">
                    {formatUsd(allocation.allocated)}
                  </span>{" "}
                  attributed to keys and accounts plus{" "}
                  <span className="font-mono text-foreground">
                    {formatUsd(allocation.unallocated)}
                  </span>{" "}
                  not attributable
                  {Object.keys(allocation.by_reason).length > 0
                    ? ` (${Object.entries(allocation.by_reason)
                        .map(
                          ([reason, amount]) => `${reason.replace(/_/g, " ")} ${formatUsd(amount)}`,
                        )
                        .join(", ")})`
                    : ""}
                  {allocation.ok
                    ? " equals the cost total."
                    : ` leaves ${formatUsd(allocation.delta)} unexplained.`}
                </>
              ) : (
                <>No attribution for this period yet; it runs at the end of each import.</>
              )}
            </CheckRow>
            {report.key_check_supported ? (
              <CheckRow title="Provider per-key totals match the attribution" verdict={keyVerdict}>
                {keyCheck ? (
                  <>
                    The provider reports{" "}
                    <span className="font-mono text-foreground">
                      {formatUsd(keyCheck.provider_total)}
                    </span>{" "}
                    across {keyCheck.keys_compared} keys; Costura attributed{" "}
                    <span className="font-mono text-foreground">
                      {formatUsd(keyCheck.allocated_total)}
                    </span>
                    {keyCheck.ok ? (
                      <>, every key within one cent.</>
                    ) : (
                      <>
                        ; {keyCheck.keys_off.length} key{keyCheck.keys_off.length === 1 ? "" : "s"}{" "}
                        outside one cent:{" "}
                        {keyCheck.keys_off
                          .slice(0, 5)
                          .map((key) => `${key.label} ${formatUsd(key.delta)}`)
                          .join(", ")}
                        .
                      </>
                    )}
                  </>
                ) : (
                  <>
                    No per-key total and attribution cover this period yet; both arrive with the
                    next import.
                  </>
                )}
              </CheckRow>
            ) : null}
            {activityCoverage ? (
              <CheckRow
                title="Activity families cover the period"
                verdict={activityCoverage.complete ? "pass" : "pending"}
              >
                {activityCoverage.complete
                  ? `All ${activityCoverage.covered_families.length} OpenAI non-completions families have a covering import.`
                  : `${activityCoverage.covered_families.length} of ${
                      activityCoverage.covered_families.length +
                      activityCoverage.missing_families.length
                    } families have a covering import; waiting for ${activityCoverage.missing_families
                      .map((family) => family.replace(/_/g, " "))
                      .join(", ")}.`}
              </CheckRow>
            ) : null}
          </ul>
        </CardContent>
      </Card>

      {!hasCost ? (
        <EmptyState message={`No cost lines stored ${inPeriod}.`} action={syncAction()} />
      ) : (
        <CostReportCard by={by} report={report} currency={currency} />
      )}
    </div>
  );
}
