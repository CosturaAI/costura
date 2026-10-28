"use client";

import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import {
  CommandDialog,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import type { InventorySearchItem } from "@/lib/api";
import {
  RESOURCE_GROUPS,
  resourceDetail,
  resourceHref,
  resourceValue,
} from "@/lib/resource-search";

const MIN_QUERY = 2;
const WAIT_MS = 200;

export type ResourceSearchFn = (
  query: string,
  signal: AbortSignal,
) => Promise<InventorySearchItem[]>;

async function searchResources(query: string, signal: AbortSignal): Promise<InventorySearchItem[]> {
  const response = await fetch(`/api/inventory/search?${new URLSearchParams({ q: query })}`, {
    signal,
    headers: { accept: "application/json" },
  });
  const body = (await response.json().catch(() => null)) as {
    detail?: string;
    items?: InventorySearchItem[];
  } | null;
  if (!response.ok) throw new Error(body?.detail ?? "Search failed");
  return body?.items ?? [];
}

/**
 * Global locator for the current organization and provider. Ctrl+K and Cmd+K open it;
 * the search itself runs through the same-origin proxy after two characters.
 */
export function ResourceSearch({
  search = searchResources,
  delay = WAIT_MS,
}: {
  search?: ResourceSearchFn;
  delay?: number;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const openRef = useRef(false);
  const returnFocus = useRef<HTMLElement | null>(null);
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<InventorySearchItem[]>([]);
  const [resultsFor, setResultsFor] = useState("");
  const [error, setError] = useState<string | null>(null);

  function setOpenState(next: boolean) {
    openRef.current = next;
    setOpen(next);
  }

  function rememberFocus(target: HTMLElement | null) {
    if (target && target !== document.body) returnFocus.current = target;
  }

  function restoreFocus() {
    const opener = returnFocus.current;
    requestAnimationFrame(() => opener?.focus());
  }

  function openSearch(opener: HTMLElement | null) {
    rememberFocus(opener);
    setOpenState(true);
  }

  function closeSearch() {
    setOpenState(false);
    restoreFocus();
  }

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.isComposing || event.key === "Process") return;
      if ((event.key !== "k" && event.key !== "K") || event.altKey || event.shiftKey) return;
      if (!event.metaKey && !event.ctrlKey) return;
      event.preventDefault();
      if (openRef.current) {
        openRef.current = false;
        setOpen(false);
        const opener = returnFocus.current;
        requestAnimationFrame(() => opener?.focus());
        return;
      }
      const current = document.activeElement;
      if (current instanceof HTMLElement && current !== document.body)
        returnFocus.current = current;
      openRef.current = true;
      setOpen(true);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    const trimmed = query.trim();
    if (!open || trimmed.length < MIN_QUERY) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      search(trimmed, controller.signal)
        .then((next) => {
          if (controller.signal.aborted) return;
          setItems(next);
          setError(null);
          setResultsFor(trimmed);
        })
        .catch((caught: unknown) => {
          if (controller.signal.aborted) return;
          setItems([]);
          setError(caught instanceof Error ? caught.message : "Search failed");
          setResultsFor(trimmed);
        });
    }, delay);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [delay, open, query, search]);

  const trimmed = query.trim();
  const current = open && trimmed.length >= MIN_QUERY && resultsFor === trimmed;
  const shown = current && !error ? items : [];
  const status =
    trimmed.length < MIN_QUERY
      ? "Type at least two characters."
      : !current
        ? "Searching…"
        : error
          ? error
          : "No current resources match.";

  return (
    <>
      <span className="relative inline-flex">
        <button
          type="button"
          aria-label="Search resources"
          aria-keyshortcuts="Control+K Meta+K"
          aria-expanded={open}
          aria-haspopup="dialog"
          onClick={(event) => openSearch(event.currentTarget)}
          className="peer inline-flex h-9 items-center gap-2 rounded-lg border border-border bg-card px-2.5 text-sm text-muted-foreground hover:text-foreground sm:pr-16"
        >
          <Search className="size-4" aria-hidden />
          <span className="hidden sm:inline">Search</span>
        </button>
        <kbd
          aria-hidden
          className="pointer-events-none absolute top-1/2 right-2.5 hidden -translate-y-1/2 font-mono text-xs text-muted-foreground peer-hover:text-foreground sm:inline"
        >
          Ctrl K
        </kbd>
      </span>
      <CommandDialog
        open={open}
        onOpenChange={(next) => (next ? openSearch(null) : closeSearch())}
        title="Search resources"
        description="Search current people, services, API keys, and workspaces."
      >
        <CommandInput
          placeholder="People, services, API keys, workspaces"
          aria-label="Search resources"
          value={query}
          onValueChange={setQuery}
        />
        <p
          role="status"
          aria-live="polite"
          className={
            shown.length === 0
              ? "px-3 pt-6 pb-2 text-center text-sm text-muted-foreground"
              : "sr-only"
          }
        >
          {shown.length === 0 ? status : `${shown.length} results`}
        </p>
        <CommandList>
          {RESOURCE_GROUPS.map((group) => {
            const rows = shown.filter((item) => item.kind === group.kind);
            if (rows.length === 0) return null;
            return (
              <CommandGroup key={group.kind} heading={group.label}>
                {rows.map((item) => (
                  <CommandItem
                    key={resourceValue(item)}
                    value={resourceValue(item)}
                    onSelect={() => {
                      closeSearch();
                      router.push(resourceHref(item));
                    }}
                  >
                    <span className="min-w-0 flex-1 truncate">{item.label}</span>
                    <span className="max-w-[14rem] truncate text-xs text-muted-foreground">
                      {resourceDetail(item)}
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
            );
          })}
          {shown.length === 0 ? (
            <CommandGroup heading="Browse">
              <CommandItem
                value="all-resources"
                onSelect={() => {
                  closeSearch();
                  router.push("/inventory");
                }}
              >
                All resources, including missing rows
              </CommandItem>
            </CommandGroup>
          ) : null}
        </CommandList>
      </CommandDialog>
    </>
  );
}
