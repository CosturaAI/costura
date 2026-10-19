import { moverSentence } from "@/components/what-changed";
import {
  api,
  type Anomalies,
  type BudgetStatuses,
  type Movers,
  type Projections,
  type Signals,
  type Summary,
} from "@/lib/api";
import { formatDelta, formatMonth, formatUsd } from "@/lib/format";
import { settledRecord, settledValue } from "@/lib/loaders";
import { coverageNote, scopeBudget, scopeProjection } from "@/lib/overview";
import { providerLabel } from "@/lib/providers";
import { SIGNAL_KIND_LABELS } from "@/lib/signals";
import { periodTitle } from "@/lib/time-range";

const TOP = 3;

export type ReviewData = {
  scope: string;
  month: string;
  summary: Summary;
  projections: Projections | null;
  budgets: BudgetStatuses | null;
  movers: Movers | null;
  anomalies: Anomalies | null;
  signals: Signals | null;
};

type ReviewSection = { title: string; lines: string[] };

/** Every read of one month review, started together; only the summary is required. */
export async function loadReview(org: string, scope: string, month: string): Promise<ReviewData> {
  const reads = await settledRecord({
    summary: api.summary(org, scope, month),
    projections: api.projection(org, scope, month, "org"),
    budgets: api.budgetStatuses(org, scope, month),
    movers: api.movers(org, scope, month, scope === "cursor" ? "person" : "api_key"),
    anomalies: api.anomalies(org, scope, month),
    signals: api.signals(org, scope),
  });
  const summary = settledValue(reads.summary);
  if (summary === null) throw new Error("the month summary could not be loaded");
  return {
    scope,
    month,
    summary,
    projections: settledValue(reads.projections),
    budgets: settledValue(reads.budgets),
    movers: settledValue(reads.movers),
    anomalies: settledValue(reads.anomalies),
    signals: settledValue(reads.signals),
  };
}

/** The review as sentences, the same for the page and the Markdown export. */
export function reviewSections(data: ReviewData): ReviewSection[] {
  const { summary } = data;
  const currency = summary.currency ?? "USD";
  const sections: ReviewSection[] = [];

  const spend = [`Spend: ${formatUsd(summary.total)} ${currency}.`];
  if (summary.previous_total) {
    const compared =
      summary.comparison_basis === "month_to_date"
        ? periodTitle(summary.previous_start, summary.previous_end)
        : formatMonth(summary.previous_month);
    spend.push(
      `${formatDelta(summary.change_percent) ?? "-"} against ${compared} (${formatUsd(summary.previous_total)} ${currency}).`,
    );
  }
  const note = coverageNote(summary);
  if (note) spend.push(note);
  sections.push({ title: "Where the money went", lines: spend });

  const plan: string[] = [];
  const projection = scopeProjection(data.projections?.projections ?? []);
  if (summary.is_current_month && projection) {
    plan.push(
      `Projected month end: ${formatUsd(projection.projected_total)} ${currency} (${formatUsd(projection.low)} to ${formatUsd(projection.high)}).`,
    );
  }
  const budget = scopeBudget(data.budgets?.statuses ?? [], data.scope);
  if (budget) {
    plan.push(
      `Budget: ${formatUsd(budget.spent)} of ${formatUsd(budget.budget.amount)} ${currency} (${budget.percent}%)${budget.projected_percent ? `, projected ${budget.projected_percent}%` : ""}.`,
    );
  } else {
    plan.push("No budget covers this scope.");
  }
  sections.push({ title: "Against the plan", lines: plan });

  const movers = data.movers;
  if (movers?.allocated && movers.rows.length > 0) {
    const previous = periodTitle(movers.previous_start, movers.previous_end);
    const rows = [...movers.rows]
      .sort((a, b) => Math.abs(Number(b.delta)) - Math.abs(Number(a.delta)))
      .slice(0, TOP);
    sections.push({
      title: "Largest moves",
      lines: rows.map((row) => `${row.label} ${moverSentence(row, previous, currency)}`),
    });
  }

  const anomalies = data.anomalies?.anomalies ?? [];
  const open = anomalies.filter((a) => a.status === "open");
  const closed = anomalies.length - open.length;
  sections.push({
    title: "Anomalies",
    lines: [
      `${anomalies.length} detected this month: ${open.length} open, ${closed} acknowledged or ignored.`,
      ...open
        .slice(0, TOP)
        .map((a) => a.explanation || `${a.label}: ${formatUsd(a.impact)} ${a.currency}.`),
    ],
  });

  const signals = (data.signals?.items ?? []).filter((s) => s.kind !== "anomaly");
  sections.push({
    title: "Needs a person",
    lines:
      signals.length === 0
        ? ["Nothing besides the anomalies."]
        : [
            `${signals.length} open besides the anomalies, most money first:`,
            ...signals
              .slice(0, TOP)
              .map(
                (s) =>
                  `${SIGNAL_KIND_LABELS[s.kind]}: ${s.label} (${s.detail}), ${formatUsd(s.dollars_at_risk)} ${s.currency}.`,
              ),
          ],
  });
  return sections;
}

export function reviewTitle(orgName: string, scope: string, month: string): string {
  const where = scope === "all" ? "all providers" : providerLabel(scope);
  return `${orgName}: ${formatMonth(month)} in review, ${where}`;
}

/** The review as Markdown: a title, then one heading per section and a bullet per line. */
export function reviewMarkdown(title: string, sections: ReviewSection[]): string {
  const body = sections
    .map((s) => [`## ${s.title}`, "", ...s.lines.map((line) => `- ${line}`)].join("\n"))
    .join("\n\n");
  return `# ${title}\n\n${body}\n`;
}
