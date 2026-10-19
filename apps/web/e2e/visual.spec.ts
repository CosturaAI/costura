import { expect, test, type Page } from "@playwright/test";

import { APP_PAGES, openApp, openHref } from "./pages";

async function expectNoOverflow(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
}

async function shot(page: Page, name: string) {
  await expectNoOverflow(page);
  await expect(page.locator("#main")).toBeVisible();
  await expect(page).toHaveScreenshot(`${name}.png`, { fullPage: false });
}

for (const [width, height, size] of [
  [1440, 900, "desktop"],
  [390, 844, "mobile"],
] as const) {
  test.describe(`${size} light`, () => {
    test.use({ viewport: { width, height }, colorScheme: "light" });

    test("sign-in", async ({ page }) => {
      await page.goto("/sign-in");
      await page.evaluate(() => document.fonts.ready);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await shot(page, `${size}-sign-in`);
    });

    for (const [name, path] of APP_PAGES) {
      test(name, async ({ page }) => {
        await openApp(page, path);
        await expect(page.getByRole("combobox", { name: "Provider" }).first()).toBeVisible();
        if (size === "desktop") {
          await page.evaluate(() => window.scrollTo(0, 600));
          const top = await page
            .locator("header")
            .evaluate((node) => node.getBoundingClientRect().top);
          expect(top).toBeLessThanOrEqual(1);
          await page.evaluate(() => window.scrollTo(0, 0));
        }
        await shot(page, `${size}-${name}`);
      });
    }
  });
}

test.describe("dark", () => {
  test.use({ viewport: { width: 1440, height: 900 }, colorScheme: "dark" });

  for (const path of ["/overview", "/anomalies"] as const) {
    test(path, async ({ page }) => {
      await openApp(page, path);
      await page.evaluate(() => {
        document.documentElement.dataset.theme = "dark";
      });
      await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
      await shot(page, `dark-${path.replace("/", "")}`);
    });
  }
});

test("narrow inventory does not overflow", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await openApp(page, "/inventory?kind=api-keys");
  await shot(page, "narrow-inventory");
});

test("tablet overview", async ({ page }) => {
  await page.setViewportSize({ width: 834, height: 1112 });
  await openApp(page, "/overview");
  await shot(page, "tablet-overview");
});

test("sidebar switches at the lg breakpoint", async ({ page }) => {
  await openApp(page, "/overview");
  await page.setViewportSize({ width: 1023, height: 800 });
  await expect(page.getByRole("navigation", { name: "Quick sections" })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "Sidebar" })).toBeHidden();
  await page.setViewportSize({ width: 1024, height: 800 });
  await expect(page.getByRole("complementary", { name: "Sidebar" })).toBeVisible();
  await expectNoOverflow(page);
});

test("demo anomalies stay read-only", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(openHref("demo", "/anomalies"));
  await page.waitForURL((url) => url.pathname === "/anomalies");
  await expect(page.getByText(/sample/i).first()).toBeVisible();
  await shot(page, "desktop-demo-anomalies");
});
