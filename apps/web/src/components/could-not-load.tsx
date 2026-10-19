import { cn } from "@/lib/utils";

/** The note a card shows when its own read failed; the rest of the page still renders. */
export function CouldNotLoad({
  what,
  inline = false,
  className,
}: {
  what: string;
  inline?: boolean;
  className?: string;
}) {
  const Tag = inline ? "span" : "p";
  return (
    <Tag className={cn("text-sm text-severity-critical", className)}>
      Could not load {what}; reload to retry.
    </Tag>
  );
}
