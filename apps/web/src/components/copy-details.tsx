"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";

/** What an error panel knows about its failure; every field but `message` is optional. */
export type ErrorDetails = {
  route?: string | null;
  job?: string | null;
  status?: number | string | null;
  code?: string | null;
  message: string;
  digest?: string | null;
};

/** The release `next.config.ts` reads from `package.json` at build time; undefined in tests. */
function appVersion(): string | undefined {
  return process.env.NEXT_PUBLIC_COSTURA_VERSION;
}

/** The Markdown an issue or a support thread needs: one list, the message in a fence. */
export function detailsMarkdown(details: ErrorDetails, now: Date = new Date()): string {
  const lines = ["## Costura error"];
  if (details.route) lines.push(`- Route: \`${details.route}\``);
  if (details.job) lines.push(`- Job: ${details.job}`);
  if (details.status !== undefined && details.status !== null) {
    lines.push(`- Status: ${details.status}`);
  }
  if (details.code) lines.push(`- Code: \`${details.code}\``);
  if (details.digest) lines.push(`- Digest: ${details.digest}`);
  const version = appVersion();
  if (version) lines.push(`- Version: ${version}`);
  lines.push(`- Time: ${now.toISOString()}`);
  return `${lines.join("\n")}\n\n\`\`\`\n${details.message}\n\`\`\`\n`;
}

type Feedback = "idle" | "copied" | "failed";

const FEEDBACK_LABEL: Record<Feedback, string> = {
  idle: "Copy details",
  copied: "Copied",
  failed: "Could not copy",
};

/** Writes `detailsMarkdown(details)` to the clipboard and confirms for two seconds. */
export function CopyDetails({ details, className }: { details: ErrorDetails; className?: string }) {
  const [feedback, setFeedback] = useState<Feedback>("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  async function copy() {
    let next: Feedback = "copied";
    try {
      await navigator.clipboard.writeText(detailsMarkdown(details));
    } catch {
      next = "failed";
    }
    setFeedback(next);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setFeedback("idle"), 2000);
  }

  return (
    <span className={className}>
      <Button type="button" variant="outline" size="sm" onClick={copy}>
        {FEEDBACK_LABEL[feedback]}
      </Button>
      <span role="status" aria-live="polite" className="sr-only">
        {feedback === "idle" ? "" : FEEDBACK_LABEL[feedback]}
      </span>
    </span>
  );
}
