import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";

import { APP_PAGES, MORE_APP_PAGES, PUBLIC_PAGES, openApp, signIn } from "./pages";

/**
 * WCAG 2.2 A and AA rules from axe on every page, at desktop and phone widths and in both
 * themes, plus the overlays a page opens. Serious and critical findings fail the run; moderate
 * and minor ones are printed so they show in the CI log.
 */
async function audit(page: Page, label: string) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  const summarize = (impacts: string[]) =>
    results.violations
      .filter((violation) => impacts.includes(violation.impact ?? ""))
      .map((violation) => ({
        rule: violation.id,
        impact: violation.impact,
        nodes: violation.nodes.slice(0, 5).map((node) => node.target.join(" ")),
      }));
  const advisory = summarize(["moderate", "minor"]);
  if (advisory.length > 0) {
    console.log(`axe advisory on ${label}: ${JSON.stringify(advisory)}`);
  }
  expect(summarize(["serious", "critical"])).toEqual([]);
}

async function settled(overlay: Locator) {
  await expect(overlay).toBeVisible();
  await overlay.evaluate((element) =>
    Promise.all(
      element.ownerDocument
        .getAnimations()
        .filter((animation) => animation.effect?.getComputedTiming().iterations !== Infinity)
        .map((animation) => animation.finished.catch(() => {})),
    ),
  );
}

const SIGNED_IN = [...APP_PAGES, ...MORE_APP_PAGES];

for (const colorScheme of ["light", "dark"] as const) {
  for (const [width, height, size] of [
    [1440, 900, "desktop"],
    [390, 844, "mobile"],
  ] as const) {
    test.describe(`${size} ${colorScheme} accessibility`, () => {
      test.use({ viewport: { width, height }, colorScheme });

      for (const [name, path] of SIGNED_IN) {
        test(name, async ({ page }) => {
          await openApp(page, path);
          await audit(page, `${name} ${size} ${colorScheme}`);
        });
      }

      for (const [name, path] of PUBLIC_PAGES) {
        test(name, async ({ page }) => {
          if (name !== "sign-in") await signIn(page);
          await page.goto(path);
          await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
          await audit(page, `${name} ${size} ${colorScheme}`);
        });
      }
    });
  }
}

test.describe("overlays", () => {
  test.use({ viewport: { width: 1440, height: 900 }, colorScheme: "light" });

  test("search palette", async ({ page }) => {
    await openApp(page, "/overview");
    await page.keyboard.press("Control+k");
    await settled(page.getByRole("dialog"));
    await audit(page, "search palette");
  });

  test("budget sheet", async ({ page }) => {
    await openApp(page, "/budgets");
    await page
      .getByRole("button", { name: /budget/i })
      .first()
      .click();
    await settled(page.getByRole("dialog"));
    await audit(page, "budget sheet");
  });

  test("confirm dialog", async ({ page }) => {
    await openApp(page, "/settings/connections");
    await page
      .getByRole("button", { name: /^Disconnect/ })
      .first()
      .click();
    await settled(page.getByRole("alertdialog"));
    await audit(page, "confirm dialog");
  });
});
