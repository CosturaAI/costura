"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { openOrgHref } from "@/lib/setup";

/** The current address reopened under every provider: `/o/{org}` writes the scope and comes
 * back. */
export function AllProvidersLink({ org, className }: { org: string; className?: string }) {
  const pathname = usePathname();
  return (
    <Link
      prefetch={false}
      href={openOrgHref(org, pathname, { scope: "all" })}
      className={className}
    >
      Open under All providers
    </Link>
  );
}
