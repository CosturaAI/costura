"use server";

import { describeError, type ActionState } from "@/lib/action-errors";
import { api, type Setup } from "@/lib/api";
import { SETTINGS_PAGES, refresh } from "@/lib/mutations";

/**
 * Server actions the welcome flow and the settings Sync now form poll with. The api client
 * runs on the web server (COSTURA_API_URL stays there), so the browser asks these actions for
 * the setup state every two seconds while a run is in progress. Nothing throws to the browser.
 */

type SetupResult = { setup: Setup; error: null } | { setup: null; error: string };

export async function getSetupAction(org: string): Promise<SetupResult> {
  try {
    return { setup: await api.setup(org), error: null };
  } catch (error) {
    return { setup: null, error: describeError(error) };
  }
}

/** Retry after a failed first run: posts the sync again and lets the poller pick the run up. */
export async function startSyncAction(org: string, provider: string): Promise<ActionState> {
  try {
    const { results } = await api.syncNow(org, provider);
    refresh([...SETTINGS_PAGES, ["/welcome"], ["/runs"]]);
    const skipped = results.find((r) => r.status === "skipped");
    if (skipped) return { ok: false, message: skipped.error ?? "Nothing to sync." };
    return { ok: true, message: "Sync started." };
  } catch (error) {
    return { ok: false, message: describeError(error) };
  }
}
