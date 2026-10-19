import Link from "next/link";

import { Button } from "@/components/ui/button";

/**
 * The way into the public sample organization: a fictional company with thirteen months of
 * synthetic spend across four providers, open without an account and read-only.
 */
export function SampleEntry({
  href,
  title,
  description,
}: {
  href: string;
  title: string;
  description: string;
}) {
  return (
    <section
      aria-label={title}
      className="space-y-3 rounded-lg border border-border bg-muted/40 p-4"
    >
      <div className="space-y-1">
        <p className="text-sm font-semibold text-foreground">{title}</p>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      <Button asChild variant="outline">
        <Link prefetch={false} href={href}>
          Explore the sample organization
        </Link>
      </Button>
    </section>
  );
}
