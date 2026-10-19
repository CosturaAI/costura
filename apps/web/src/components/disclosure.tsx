import { cn } from "@/lib/utils";

/** One collapsed explanation or control group. Closed content stays in the page, out of the first layer. */
export function Disclosure({
  title,
  children,
  open = false,
  className,
}: {
  title: string;
  children: React.ReactNode;
  open?: boolean;
  className?: string;
}) {
  return (
    <details
      open={open || undefined}
      className={cn("rounded-md border border-border bg-background px-4 py-3 text-sm", className)}
    >
      <summary className="cursor-pointer font-medium text-secondary-foreground">{title}</summary>
      <div className="mt-3 space-y-3">{children}</div>
    </details>
  );
}
