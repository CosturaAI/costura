"use client";

import type { ComponentProps, MouseEvent } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * A submit button that stays focusable while its form posts. `disabled` would drop keyboard
 * focus to the page body mid-submission; `aria-disabled` keeps focus where it was and a click
 * during the post is ignored, so a second submit cannot start.
 */
export function SubmitButton({
  pending,
  onClick,
  className,
  ...props
}: Omit<ComponentProps<typeof Button>, "type" | "disabled"> & { pending: boolean }) {
  return (
    <Button
      type="submit"
      aria-disabled={pending || undefined}
      data-pending={pending || undefined}
      className={cn("aria-disabled:cursor-not-allowed aria-disabled:opacity-60", className)}
      onClick={(event: MouseEvent<HTMLButtonElement>) => {
        if (pending) {
          event.preventDefault();
          return;
        }
        onClick?.(event);
      }}
      {...props}
    />
  );
}
