import { cn } from "@/lib/utils";

/**
 * Card title as a real heading. shadcn's `CardTitle` renders a `div`, which leaves card names
 * out of the heading outline screen readers navigate by; this keeps its look on an `h2`.
 */
export function CardHeading({
  as: Tag = "h2",
  className,
  ...props
}: React.ComponentProps<"h2"> & { as?: "h2" | "h3" }) {
  return (
    <Tag
      data-slot="card-title"
      className={cn("font-heading text-base leading-snug font-medium", className)}
      {...props}
    />
  );
}
