import Link from "next/link";

import { cn } from "@/lib/utils";

const TONE_CLASS = {
  empty: "border-dashed border-border bg-background",
  warning: "border-severity-warning/30 bg-severity-warning-bg",
  error: "border-severity-critical/30 bg-severity-critical-bg",
  partial: "border-border bg-card",
} as const;

/**
 * Shared empty, warning, error and partial panel. Empty pages name what fills them, then the
 * one link that changes it. No command is ever printed here.
 */
export function StatePanel({
  tone = "empty",
  title,
  message,
  action,
  children,
}: {
  tone?: keyof typeof TONE_CLASS;
  title?: string;
  message?: string;
  action?: { href: string; label: string };
  children?: React.ReactNode;
}) {
  return (
    <div className={cn("rounded-lg border p-8 text-center", TONE_CLASS[tone])} role="status">
      {title ? <p className="text-sm font-medium text-foreground">{title}</p> : null}
      {message ? <p className="mt-1 text-sm text-muted-foreground">{message}</p> : null}
      {children}
      {action ? (
        <p className="mt-3 text-sm">
          <Link href={action.href} className="font-medium text-primary hover:underline">
            {action.label}
          </Link>
        </p>
      ) : null}
    </div>
  );
}

/**
 * Empty pages name what fills them: a sentence about the data, then the one link that changes
 * it (the welcome page when the organization has no connected key, Sync now in settings when it
 * has one, the run history when the import already happened). No command is ever printed here;
 * instance-level conditions are worded for the person in the browser.
 */
export function EmptyState({
  message,
  action,
}: {
  message: string;
  action?: { href: string; label: string };
}) {
  return <StatePanel message={message} action={action} />;
}
