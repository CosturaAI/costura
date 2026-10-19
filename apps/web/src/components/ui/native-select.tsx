import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * The native `<select>` with the input's border, focus ring, invalid and disabled states. Used
 * where a native control is the right one (forms that post, phone-width pickers); the Radix
 * `Select` stays for the scope bar.
 */
function NativeSelect({ className, ...props }: React.ComponentProps<"select">) {
  return (
    <select
      data-slot="native-select"
      className={cn(
        "h-9 rounded-lg border border-input bg-card px-2 text-sm text-foreground transition-colors outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-60 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20",
        className,
      )}
      {...props}
    />
  );
}

export { NativeSelect };
