"use client";

import { useEffect } from "react";

import { markReadAction } from "../actions";

/**
 * Marks the anomaly read in the visitor's inbox once the page has rendered. A client effect
 * rather than a call during render so the read-only render of the page stays free of writes
 * and the API's 403 outside a local stack never breaks the page.
 */
export function MarkRead({ org, id }: { org: string; id: number }) {
  useEffect(() => {
    void markReadAction([id]);
  }, [org, id]);
  return null;
}
