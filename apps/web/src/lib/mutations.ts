/**
 * The shape every server action shares: call the API, refresh the pages the write changed,
 * and turn a failure into the sentence the form shows. Actions that redirect or name a field
 * keep their own catch and use `describeError` directly.
 *
 * A write names the routes it changes. Only writes that change the shell itself (the view
 * cookie, the organization, a connection the scope bar lists) refresh every page.
 */

import { revalidatePath } from "next/cache";

import { describeError, type ActionState } from "@/lib/action-errors";

/** A route file pattern and how much of it to refresh; dynamic segments need a type. */
type Route = readonly [path: string, type?: "page" | "layout"];

/** Every page under the root layout. */
export const EVERY_PAGE: readonly Route[] = [["/", "layout"]];

/** Pages that show one entity's spend and anomalies. */
const ENTITY_PAGES: readonly Route[] = [
  ["/keys/[id]", "page"],
  ["/accounts/[id]", "page"],
  ["/workspaces/[id]", "page"],
  ["/models/[id]", "page"],
  ["/people/[email]", "page"],
];

export const BUDGET_PAGES: readonly Route[] = [
  ["/budgets"],
  ["/overview"],
  ["/workspaces/[id]", "page"],
];

export const ANOMALY_PAGES: readonly Route[] = [
  ["/anomalies"],
  ["/anomalies/[id]", "page"],
  ["/overview"],
  ...ENTITY_PAGES,
];

export const PERSON_PAGES: readonly Route[] = [
  ["/overview"],
  ["/explore"],
  ["/budgets"],
  ...ENTITY_PAGES,
];

export const RECONCILE_PAGES: readonly Route[] = [["/reconcile"]];

export const SETTINGS_PAGES: readonly Route[] = [["/settings", "layout"]];

export function refresh(routes: readonly Route[]): void {
  for (const [path, type] of routes) {
    if (type) revalidatePath(path, type);
    else revalidatePath(path);
  }
}

export async function runMutation(
  work: () => Promise<string>,
  routes: readonly Route[] = EVERY_PAGE,
): Promise<ActionState> {
  try {
    const message = await work();
    refresh(routes);
    return { ok: true, message };
  } catch (error) {
    return { ok: false, message: describeError(error) };
  }
}
