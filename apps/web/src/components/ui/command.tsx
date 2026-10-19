"use client";

import { Command as CommandPrimitive } from "cmdk";
import { cn } from "@/lib/utils";
import { Search } from "lucide-react";
import * as React from "react";

function CommandDialog({
  title = "Search resources",
  description = "Search current people, services, API keys, and workspaces.",
  children,
  ...props
}: React.ComponentProps<typeof CommandPrimitive.Dialog> & {
  title?: string;
  description?: string;
}) {
  return (
    <CommandPrimitive.Dialog
      label={title}
      shouldFilter={false}
      vimBindings={false}
      overlayClassName="fixed inset-0 z-50 bg-black/10 supports-backdrop-filter:backdrop-blur-xs"
      contentClassName="fixed top-[15%] left-1/2 z-50 w-[min(32rem,calc(100vw-2rem))] -translate-x-1/2 overflow-hidden rounded-lg border border-border bg-popover text-popover-foreground shadow-lg outline-none"
      {...props}
    >
      <span className="sr-only">{description}</span>
      {children}
    </CommandPrimitive.Dialog>
  );
}

function CommandInput({
  className,
  ...props
}: React.ComponentProps<typeof CommandPrimitive.Input>) {
  return (
    <div className="flex items-center gap-2 border-b border-border px-3" cmdk-input-wrapper="">
      <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      <CommandPrimitive.Input
        data-slot="command-input"
        className={cn(
          "h-11 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground",
          className,
        )}
        {...props}
      />
    </div>
  );
}

function CommandList({ className, ...props }: React.ComponentProps<typeof CommandPrimitive.List>) {
  return (
    <CommandPrimitive.List
      data-slot="command-list"
      className={cn("max-h-80 overflow-y-auto p-1", className)}
      {...props}
    />
  );
}

function CommandGroup({
  className,
  ...props
}: React.ComponentProps<typeof CommandPrimitive.Group>) {
  return (
    <CommandPrimitive.Group
      data-slot="command-group"
      className={cn(
        "overflow-hidden p-1 text-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground",
        className,
      )}
      {...props}
    />
  );
}

function CommandItem({ className, ...props }: React.ComponentProps<typeof CommandPrimitive.Item>) {
  return (
    <CommandPrimitive.Item
      data-slot="command-item"
      className={cn(
        "flex cursor-default items-center gap-2 rounded-md px-2 py-2 text-sm outline-none select-none data-[disabled=true]:pointer-events-none data-[disabled=true]:opacity-50 data-[selected=true]:bg-muted data-[selected=true]:text-foreground",
        className,
      )}
      {...props}
    />
  );
}

export { CommandDialog, CommandGroup, CommandInput, CommandItem, CommandList };
