"use client";

import { Info } from "lucide-react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

/**
 * A short clause with the method behind it one click or one key press away. The method is a
 * real popover on a button, so mouse, keyboard and touch users can read it, not only screen
 * readers.
 */
export function MethodHint({ text, method }: { text: string; method: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      {text}
      <Popover>
        <PopoverTrigger
          type="button"
          aria-label="How this is computed"
          className="inline-flex rounded-sm text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          <Info className="h-3 w-3" aria-hidden="true" />
        </PopoverTrigger>
        <PopoverContent className="max-w-xs text-xs">{method}</PopoverContent>
      </Popover>
    </span>
  );
}
