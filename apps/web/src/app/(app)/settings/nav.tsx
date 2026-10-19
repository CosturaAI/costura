"use client";

import Link from "next/link";
import { useRouter, useSelectedLayoutSegment } from "next/navigation";

import { cn } from "@/lib/utils";
import { NativeSelect } from "@/components/ui/native-select";

type SettingsSection =
  | "sample"
  | "organization"
  | "connections"
  | "sync"
  | "anomalies"
  | "members"
  | "teams"
  | "account"
  | "audit"
  | "advanced";

/** The two scopes a setting can belong to; the group is a label, never a route. */
type SettingsGroup = "Sample" | "Organization" | "You";

export type SettingsNavItem = {
  segment: SettingsSection;
  label: string;
  group: SettingsGroup;
  /** Something in that section needs a decision (a rejected key, a failed import). */
  attention?: boolean;
};

const GROUPS: SettingsGroup[] = ["Sample", "Organization", "You"];

/**
 * Section navigation of Settings: a native select below `lg` and a rail beside the content
 * from `lg`. One link per section, so the group labels are decoration that appears only where
 * the rail does. The dot marks a section holding a rejected key or a failed import, the state
 * a visitor would otherwise have to open every section to find.
 */
export function SettingsNav({ items }: { items: SettingsNavItem[] }) {
  const active = useSelectedLayoutSegment() ?? items[0]?.segment ?? "connections";
  const router = useRouter();
  return (
    <>
      <label className="grid gap-1 text-xs text-muted-foreground lg:hidden">
        Settings section
        <NativeSelect
          aria-label="Settings section"
          value={active}
          onChange={(event) => router.push(`/settings/${event.currentTarget.value}`)}
          className="h-10 w-full px-3"
        >
          {items.map((item) => (
            <option key={item.segment} value={item.segment}>
              {item.label}
              {item.attention ? " - needs attention" : ""}
            </option>
          ))}
        </NativeSelect>
      </label>
      <nav aria-label="Settings sections" className="hidden w-44 shrink-0 flex-col gap-5 lg:flex">
        {GROUPS.map((group) => {
          const own = items.filter((item) => item.group === group);
          if (own.length === 0) return null;
          return (
            <div key={group} className="flex flex-col gap-0.5">
              <p className="px-3 pb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">
                {group}
              </p>
              {own.map((item) => (
                <Link
                  key={item.segment}
                  href={`/settings/${item.segment}`}
                  aria-current={active === item.segment ? "page" : undefined}
                  // The dot is silent; the state it stands for belongs in the link's name.
                  aria-label={item.attention ? `${item.label}, needs attention` : undefined}
                  className={cn(
                    "flex items-center gap-2 rounded-md px-3 py-2 text-sm whitespace-nowrap",
                    active === item.segment
                      ? "bg-muted font-medium text-foreground"
                      : "text-secondary-foreground hover:bg-background hover:text-foreground",
                  )}
                >
                  {item.label}
                  {item.attention ? (
                    <span
                      aria-hidden
                      className="inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-severity-critical"
                    />
                  ) : null}
                </Link>
              ))}
            </div>
          );
        })}
      </nav>
    </>
  );
}
