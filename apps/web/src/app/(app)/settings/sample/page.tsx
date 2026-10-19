import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { CardHeading } from "@/components/card-heading";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { formatMinute, formatRelative } from "@/lib/format";
import { sampleProviders } from "@/lib/sample";
import { newestSchedule } from "@/lib/scope";
import { requireView } from "@/lib/view";

import { loadSettings } from "../data";

export const metadata: Metadata = { title: "Sample organization" };

/** What a reader can see in the sample, and where. Every case is part of every refresh. */
const CASES = [
  {
    href: "/anomalies",
    label: "Anomalies",
    text: "A key stuck in a retry loop, a Claude Code login running a large migration, and a gateway that loses most of its traffic for four days.",
  },
  {
    href: "/budgets",
    label: "Budgets",
    text: "One budget with room to spare, one projected near its limit and one already exceeded.",
  },
  {
    href: "/reconcile",
    label: "Reconciliation",
    text: "Each provider's own total against Costura's, with one provider reporting late usage.",
  },
  {
    href: "/runs",
    label: "Run history",
    text: "The first import and the daily imports since, with one failed import and one step that needed a retry.",
  },
  {
    href: "/inventory",
    label: "Resources",
    text: "Keys, workspaces and people, including expired, archived and disabled keys.",
  },
] as const;

/**
 * The sample organization's own Settings page: which providers it holds, where its data comes
 * from, when it was last refreshed and what it demonstrates. Other organizations answer 404,
 * since their configuration lives in the sections themselves.
 */
export default async function SampleSettingsPage() {
  const settings = await loadSettings();
  if (!settings.isDemo) notFound();
  const { organization, registry } = await requireView();
  const providers = sampleProviders(registry);
  const refreshed = newestSchedule(settings.scope)?.last_run_at ?? null;

  return (
    <>
      <Card>
        <CardHeader>
          <CardHeading>How this sample is configured</CardHeading>
          <CardDescription>
            {organization.name} is a fictional company. Its costs, usage and inventory are generated
            by Costura: no provider key is stored and no provider is called.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-x-8 gap-y-2 text-sm sm:grid-cols-[10rem_1fr]">
            <dt className="text-muted-foreground">Providers</dt>
            <dd>
              <ul className="space-y-1">
                {providers.map((info) => (
                  <li key={info.provider}>
                    <span className="font-medium text-foreground">{info.label}</span>
                    <span className="text-muted-foreground">
                      {" "}
                      {info.accounts.length === 1
                        ? `one account (${info.accounts[0]!.label})`
                        : `${info.accounts.length} accounts (${info.accounts.map((a) => a.label).join(", ")})`}
                    </span>
                  </li>
                ))}
              </ul>
            </dd>
            <dt className="text-muted-foreground">History</dt>
            <dd>Twelve whole months and the current month to date.</dd>
            <dt className="text-muted-foreground">Last refresh</dt>
            <dd>
              {refreshed ? (
                <time dateTime={refreshed}>
                  {formatRelative(refreshed)} ({formatMinute(refreshed)})
                </time>
              ) : (
                "unknown"
              )}
              ; the sample is regenerated through yesterday, so the latest episode stays recent.
            </dd>
            <dt className="text-muted-foreground">Changes</dt>
            <dd>None. Forms are hidden here and the API refuses every write to the sample.</dd>
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardHeading>What it demonstrates</CardHeading>
          <CardDescription>
            The same cases are in every refresh; the dates move with the calendar.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="divide-y divide-border text-sm">
            {CASES.map((item) => (
              <li key={item.href} className="py-2 first:pt-0 last:pb-0">
                <Link href={item.href} className="font-medium text-primary hover:underline">
                  {item.label}
                </Link>
                <p className="text-muted-foreground">{item.text}</p>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </>
  );
}
