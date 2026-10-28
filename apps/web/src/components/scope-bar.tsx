"use client";

import { usePathname } from "next/navigation";
import { useTransition } from "react";

import { setViewAction } from "@/actions/view";
import { IntervalControl } from "@/components/interval-control";
import { TimeFrameControl } from "@/components/time-frame-control";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ALL, PROVIDERS, providerLabel } from "@/lib/providers";
import type { QueryInterval } from "@/lib/time-range";
import { cn } from "@/lib/utils";

/**
 * The scope bar: provider, time frame and bucket interval. None is in the URL:
 * each control writes the view cookie through a server action and the router re-renders the
 * same page.
 */
export type ScopeSelectorProps = {
  provider: string;
  providers?: string[];
};

/** Provider control shared by the desktop scope bar and the mobile sheet. */
export function ScopeSelectors({
  provider,
  providers = PROVIDERS,
  stacked = false,
  onNavigate,
}: ScopeSelectorProps & { stacked?: boolean; onNavigate?: () => void }) {
  const [pending, startTransition] = useTransition();
  const known = providers.includes(provider) || provider === ALL;
  const providerOptions = [ALL, ...(known ? providers : [provider, ...providers])];

  function go(nextProvider: string) {
    if (pending || nextProvider === provider) return;
    startTransition(async () => {
      await setViewAction({ scope: nextProvider });
      onNavigate?.();
    });
  }

  return (
    <div
      className={cn(
        "flex shrink-0 items-center gap-1.5",
        stacked && "flex-col items-stretch gap-3",
      )}
    >
      <label className={cn(stacked && "space-y-1")}>
        <span
          className={cn("sr-only", stacked && "not-sr-only block text-xs text-muted-foreground")}
        >
          Provider
        </span>
        <Select value={provider} onValueChange={go}>
          <SelectTrigger
            aria-label={`Provider: ${providerLabel(provider)}`}
            aria-busy={pending || undefined}
            aria-disabled={pending || undefined}
            className={cn(
              "h-9 max-w-36 border-transparent bg-transparent font-medium text-foreground shadow-none hover:bg-muted sm:max-w-none",
              stacked && "w-full border-border bg-card",
            )}
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {providerOptions.map((slug) => (
              <SelectItem key={slug} value={slug}>
                {providerLabel(slug)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </label>
    </div>
  );
}

export function ScopeBreadcrumb({
  provider,
  providers = PROVIDERS,
  from,
  to,
  interval,
}: {
  provider: string;
  /** Concrete providers to offer after "All providers"; defaults to every registered one. */
  providers?: string[];
  from: string;
  to: string;
  interval: QueryInterval;
}) {
  const path = usePathname() ?? "";
  // Runs, settings and one anomaly ignore the range. The bucket interval is only read by
  // Overview and Analyze.
  const showTime =
    !path.startsWith("/settings") && !path.startsWith("/runs") && !/^\/anomalies\/[^/]+/.test(path);
  const showInterval = path.startsWith("/overview") || path.startsWith("/explore");
  return (
    <nav aria-label="Scope" className="flex min-w-0 flex-1 items-center gap-1.5 sm:flex-wrap">
      <ScopeSelectors provider={provider} providers={providers} />
      {showTime ? (
        <>
          <span aria-hidden="true" className="text-faint-foreground">
            /
          </span>
          <TimeFrameControl from={from} to={to} />
        </>
      ) : null}
      {showInterval ? <IntervalControl interval={interval} /> : null}
    </nav>
  );
}
