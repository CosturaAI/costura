"use client";

import { createContext, useContext, type ReactNode } from "react";

import { VIEWPORT_COOKIE } from "@/lib/viewport-cookie";

const ViewportWidth = createContext<number | null>(null);

export function ViewportProvider({
  width,
  children,
}: {
  width: number | null;
  children: ReactNode;
}) {
  return <ViewportWidth.Provider value={width}>{children}</ViewportWidth.Provider>;
}

/** The width the server rendered for, or null on a first visit (no cookie yet). */
export function useServerViewportWidth(): number | null {
  return useContext(ViewportWidth);
}

export function rememberViewportWidth(width: number): void {
  try {
    document.cookie = `${VIEWPORT_COOKIE}=${Math.round(width)}; path=/; max-age=31536000; samesite=lax`;
  } catch {
    // A browser that refuses cookies keeps the desktop-first paint.
  }
}
