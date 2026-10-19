import { expect, type Page } from "@playwright/test";

/** The signed-in pages the visual and accessibility suites both open. */
export const APP_PAGES = [
  ["overview", "/overview"],
  ["explore", "/explore?by=api_key"],
  ["inventory", "/inventory?kind=api-keys"],
  ["runs", "/runs"],
  ["budgets", "/budgets"],
  ["anomalies", "/anomalies"],
  ["anomaly", "/anomalies/7"],
  ["reconcile", "/reconcile"],
  ["connections", "/settings/connections"],
  ["key", "/keys/key-zero-tokens"],
] as const;

/** Every other signed-in page, checked by the accessibility suite only. */
export const MORE_APP_PAGES = [
  ["workspaces tab", "/inventory?kind=workspaces"],
  ["people tab", "/inventory?kind=users"],
  ["person", "/people/ana@example.com"],
  ["account", "/accounts/user-ana"],
  ["workspace", "/workspaces/wrkspc_platform"],
  ["model", "/models/claude-sonnet-4"],
  ["settings organization", "/settings/organization"],
  ["settings members", "/settings/members"],
  ["settings sync", "/settings/sync"],
  ["settings anomalies", "/settings/anomalies"],
  ["settings account", "/settings/account"],
  ["settings advanced", "/settings/advanced"],
  ["settings teams", "/settings/teams"],
  ["settings audit", "/settings/audit"],
  ["review", "/review?scope=all&month=2026-08"],
] as const;

/** Pages outside the app shell, opened without a view. */
export const PUBLIC_PAGES = [
  ["sign-in", "/sign-in"],
  ["join", "/join"],
  ["welcome", "/welcome"],
  ["new organization", "/new"],
] as const;

/** The mock API's port: Playwright starts it there, and specs that read its request log use it. */
export const MOCK_API_PORT = 3200;
export const MOCK_API = `http://127.0.0.1:${MOCK_API_PORT}`;

export function openHref(slug: string, next: string, scope = "all", month = "2026-08"): string {
  const query = new URLSearchParams({ scope, month, next });
  return `/o/${slug}?${query.toString()}`;
}

export async function signIn(page: Page) {
  await page.goto("/sign-in");
  await page.context().addCookies([
    {
      name: "costura_session",
      value: "e2e-session",
      url: new URL(page.url()).origin,
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
}

export async function openApp(page: Page, next: string, slug = "default") {
  await signIn(page);
  await page.goto(openHref(slug, next));
  await page.waitForURL((url) => url.pathname + url.search === next);
  await page.evaluate(() => document.fonts.ready);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
}
