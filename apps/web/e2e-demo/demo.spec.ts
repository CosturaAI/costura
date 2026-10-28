import { expect, test, type Locator, type Page } from "@playwright/test";

// `scripts/demo-e2e.sh` builds the sample as of 2026-09-15: data runs through 2026-09-14.
const MONTH = "2026-09";
const API = process.env.COSTURA_DEMO_E2E_API ?? "http://127.0.0.1:18100";
const MUTATIONS =
  /^(Save|Delete|Remove|Acknowledge|Ignore|Reopen|Sync now|Connect|Add a budget|Add account|Invite|Dismiss|Replace key|Disconnect|Rename|Reset|Leave)/;

function sampleHref(next: string, scope = "all", month = MONTH): string {
  return `/o/demo?${new URLSearchParams({ scope, month, next }).toString()}`;
}

async function settle(page: Page) {
  await page.evaluate(() => document.fonts.ready);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
}

async function open(page: Page, next: string, scope = "all") {
  await page.goto(sampleHref(next, scope));
  const path = next.split("?")[0];
  await page.waitForURL((url) => url.pathname === path);
  await settle(page);
}

function guide(page: Page): Locator {
  return page.getByRole("region", { name: "Sample organization" });
}

async function expectReadOnly(page: Page) {
  await expect(page.getByRole("button", { name: MUTATIONS })).toHaveCount(0);
  await expect(page.locator("input[type=password]")).toHaveCount(0);
}

async function expectNoOverflow(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
}

/** What moves with the wall clock rather than the dataset: relative times and run instants. */
function volatile(page: Page): Locator[] {
  return [
    page.getByRole("button", { name: /^Data freshness:/ }),
    page.locator("time"),
    page.getByRole("listitem").filter({ hasText: "Last import" }),
  ];
}

async function shot(page: Page, name: string) {
  await expectNoOverflow(page);
  await expect(page).toHaveScreenshot(`${name}.png`, { mask: volatile(page) });
}

test.describe.configure({ mode: "serial" });

test("a visitor finds the sample from sign-in and lands on its story", async ({ page }) => {
  await page.goto("/sign-in");
  const entry = page.getByRole("region", { name: "No account yet?" });
  await expect(entry).toContainText("fictional company");
  await entry.getByRole("link", { name: "Explore the sample organization" }).click();
  await page.waitForURL((url) => url.pathname === "/overview");
  await settle(page);

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Spend in September 2026");
  await expect(guide(page)).toContainText("is a fictional company: every figure is synthetic");
  const signals = page.getByRole("list", { name: "Signals" });
  await expect(signals.getByRole("link", { name: "View budgets" })).toBeVisible();
  const queue = page.getByRole("list", { name: "Needs a person" });
  await expect(queue.locator('a[href^="/anomalies/"]').first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Account menu" })).toHaveCount(0);
  await expectReadOnly(page);
});

test("drill-downs open a key and an anomaly", async ({ page }) => {
  await open(page, "/overview");
  const keys = page.getByRole("region", { name: "Who spends" });
  const key = keys
    .getByRole("link")
    .filter({ hasNotText: /See all/ })
    .first();
  const name = (await key.textContent())?.trim() ?? "";
  await key.click();
  await page.waitForURL((url) => url.pathname.startsWith("/keys/"));
  await settle(page);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(name);
  await expectReadOnly(page);

  await open(page, "/anomalies");
  await expect(page.getByRole("region", { name: "Anomaly feed" })).toBeVisible();
  await page.locator('a[href^="/anomalies/"]').first().click();
  await page.waitForURL((url) => /^\/anomalies\/\d+$/.test(url.pathname));
  await settle(page);
  await expectReadOnly(page);
});

test("Explore exports CSV and copies a link that opens the sample anywhere", async ({
  page,
  context,
  browser,
}) => {
  await open(page, "/explore?by=provider");
  const href = await page.getByRole("link", { name: "Export CSV" }).getAttribute("href");
  expect(href).toBeTruthy();
  const csv = await page.request.get(href!);
  expect(csv.status()).toBe(200);
  expect(csv.headers()["content-type"]).toContain("text/csv");
  const body = await csv.text();
  expect(body.split("\n").length).toBeGreaterThan(2);
  expect(body).toMatch(/anthropic|Anthropic/);

  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.getByRole("button", { name: "Copy link" }).click();
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  const shared = new URL(copied, page.url());
  expect(shared.pathname).toBe("/o/demo");
  expect(shared.searchParams.get("next")).toMatch(/^\/explore\?/);

  const fresh = await browser.newContext();
  const stranger = await fresh.newPage();
  await stranger.goto(shared.toString());
  await stranger.waitForURL((url) => url.pathname === "/explore");
  await expect(stranger.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(stranger.getByRole("region", { name: "Sample organization" })).toBeVisible();
  await fresh.close();
});

test("Reconcile shows the one provider that does not add up", async ({ page }) => {
  await open(page, "/reconcile");
  await expect(page.getByRole("heading", { name: /^OpenRouter/ })).toContainText("fail");
  for (const provider of ["Anthropic", "OpenAI", "Cursor"]) {
    await expect(page.getByRole("heading", { name: new RegExp(`^${provider}`) })).toContainText(
      "pass",
    );
  }
  await expect(page.getByText("disconnected")).toHaveCount(0);
  await open(page, "/reconcile", "openrouter");
  await expectReadOnly(page);
});

test("Runs keep the failed import and the retried step", async ({ page }) => {
  await open(page, "/runs?limit=500", "openrouter");
  const rows = page.getByRole("row");
  await expect(rows.filter({ hasText: "failed" }).first()).toBeVisible();
  await expect(rows.filter({ hasText: "succeeded" }).first()).toBeVisible();
  await expectReadOnly(page);
});

test("Settings explain the sample and leave out what it does not have", async ({ page }) => {
  await open(page, "/overview");
  await page.goto("/settings");
  await page.waitForURL((url) => url.pathname === "/settings/sample");
  await expect(page.getByRole("heading", { name: "How this sample is configured" })).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Settings sections" });
  await expect(nav.getByRole("link")).toHaveText([
    "How it is configured",
    "Connections",
    "Sync",
    "Anomalies",
  ]);
  for (const section of ["connections", "sync", "anomalies"]) {
    await page.goto(`/settings/${section}`);
    await settle(page);
    await expect(page.getByText("not connected")).toHaveCount(0);
    await expectReadOnly(page);
  }
  for (const section of ["members", "organization", "account", "advanced"]) {
    // The settings shell streams first, so the status stays 200 and the body is the 404 page.
    await page.goto(`/settings/${section}`);
    await expect(
      page.getByRole("heading", { level: 1, name: "Section not available" }),
    ).toBeVisible();
  }
});

test("the API refuses every write to the sample", async ({ request }) => {
  const signed = await request.post(`${API}/api/v1/auth/dev-sign-in`, {
    data: { email: "visitor@example.com" },
  });
  expect(signed.ok()).toBeTruthy();
  const token = ((await signed.json()) as { token: string }).token;
  const headers = { Authorization: `Bearer ${token}` };
  const scope = `${API}/api/v1/orgs/demo/providers/anthropic`;
  const budget = await request.put(`${scope}/budgets/org/__org__`, {
    headers,
    data: { amount: "100" },
  });
  expect(budget.status()).toBe(403);
  const sync = await request.post(`${scope}/sync`, { headers });
  expect(sync.status()).toBe(403);
});

for (const [width, height, size] of [
  [1440, 900, "desktop"],
  [390, 844, "mobile"],
] as const) {
  for (const theme of ["light", "dark"] as const) {
    test.describe(`${size} ${theme}`, () => {
      test.use({ viewport: { width, height }, colorScheme: theme });

      async function themed(page: Page) {
        if (theme === "dark") {
          await page.evaluate(() => {
            document.documentElement.dataset.theme = "dark";
          });
          await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
        }
      }

      test("snapshots", async ({ page }) => {
        if (theme === "light") {
          await page.goto("/sign-in");
          await settle(page);
          await shot(page, `${size}-${theme}-sign-in`);
        }
        await open(page, "/overview");
        await themed(page);
        await shot(page, `${size}-${theme}-overview`);

        const anomaly = await page
          .getByRole("list", { name: "Needs a person" })
          .locator('a[href^="/anomalies/"]')
          .first()
          .getAttribute("href");
        await page.goto(anomaly!);
        await page.waitForURL((url) => url.pathname.startsWith("/anomalies/"));
        await settle(page);
        await themed(page);
        await shot(page, `${size}-${theme}-anomaly`);

        await open(page, "/reconcile");
        await themed(page);
        await shot(page, `${size}-${theme}-reconcile`);

        await open(page, "/settings/sample");
        await themed(page);
        await shot(page, `${size}-${theme}-settings`);
      });
    });
  }
}
