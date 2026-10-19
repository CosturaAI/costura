import type { Metadata } from "next";

import { CardHeading } from "@/components/card-heading";
import { CopyButton } from "@/components/copy-button";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { loadReview, reviewSections, reviewTitle } from "@/lib/review";
import { openOrgHref } from "@/lib/setup";
import { requireView, resolveScope } from "@/lib/view";

export const metadata: Metadata = { title: "Month in review" };

const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;

/**
 * One month told in sentences: where the money went and against what, the largest moves,
 * the anomalies and what still needs a person. `?scope=` and `?month=` are in the URL, and
 * the share link goes through `/o/<org>` so the reader opens the same organization; the
 * Markdown export carries the same text.
 */
export default async function ReviewPage({
  searchParams,
}: {
  searchParams: Promise<{ scope?: string; month?: string }>;
}) {
  const query = await searchParams;
  const view = await requireView();
  const scope = resolveScope(query.scope ?? view.provider);
  const month = query.month && MONTH.test(query.month) ? query.month : view.month;
  const data = await loadReview(view.org, scope, month);
  const title = reviewTitle(view.organization.name, scope, month);
  const path = `/review?scope=${encodeURIComponent(scope)}&month=${month}`;
  const share = openOrgHref(view.org, path);
  const markdown = `/api/review?scope=${encodeURIComponent(scope)}&month=${month}`;
  return (
    <div className="space-y-5">
      <PageHeader title={title} description="Generated from the figures on the other pages." />
      <p className="flex flex-wrap items-center gap-3 text-sm print:hidden">
        <CopyButton value={share} label="Copy the link to this review" />
        <a href={markdown} className="text-primary hover:underline">
          Download as Markdown
        </a>
      </p>
      {reviewSections(data).map((section) => (
        <Card key={section.title} className="break-inside-avoid">
          <CardHeader>
            <CardHeading>{section.title}</CardHeading>
          </CardHeader>
          <CardContent>
            <ul className="list-disc space-y-1 pl-5 text-sm">
              {section.lines.map((line, index) => (
                <li key={index}>{line}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
