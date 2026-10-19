"use client";

import { useEffect, useRef } from "react";

import type { ActionState } from "@/lib/action-errors";

/**
 * Runs `callback` once per successful action result: the forms that open behind a button
 * (budget sheet, invoice total, personal key, contact, connection) close themselves on save.
 * A repeated render of the same result does not run it twice.
 */
export function useOnSuccess(state: ActionState, callback: (() => void) | undefined): void {
  const handled = useRef<ActionState | null>(null);
  useEffect(() => {
    if (state.ok && handled.current !== state) {
      handled.current = state;
      callback?.();
    }
  }, [state, callback]);
}
