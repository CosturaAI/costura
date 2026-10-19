"use client";

import { useEffect, useState } from "react";

import { rememberViewportWidth, useServerViewportWidth } from "@/lib/viewport";

/**
 * True when the viewport is at least `px` wide. The first render uses the width the browser
 * reported on an earlier visit (the `costura_vw` cookie), so the server paints the layout the
 * device will keep; without it (first visit, jsdom tests) the desktop presentation renders
 * first and a narrow viewport corrects it after mount. Structural switches that cost nothing
 * to render twice (chips against a select) use CSS breakpoints instead.
 */
export function useMinWidth(px: number): boolean {
  const known = useServerViewportWidth();
  const [matches, setMatches] = useState(known === null ? true : known >= px);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia(`(min-width: ${px}px)`);
    const update = () => {
      setMatches(query.matches);
      rememberViewportWidth(window.innerWidth);
    };
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, [px]);
  return matches;
}
