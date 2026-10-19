// Captures the product screens that docs/product/screens.md shows, from the sample
// organization on a running local stack (`just dev`). Each screen is 1280x800 CSS pixels,
// rendered at 2x and saved to docs/assets/screens/<name>.png.
//
//   just web::screens            # http://127.0.0.1:3000
//   just web::screens http://host:port
//
// The list below is the contract between this script and the document: a screen added
// here gets a section there, and a screen removed here loses it.

import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { chromium } from "@playwright/test";

const base = process.argv[2] ?? "http://127.0.0.1:3000";
const out = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../docs/assets/screens",
);
await mkdir(out, { recursive: true });

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1280, height: 800 },
  deviceScaleFactor: 2,
  colorScheme: "light",
});
// The Next.js development overlay is not part of the product.
await context.addInitScript(() => {
  const style = document.createElement("style");
  style.textContent = "nextjs-portal, [data-nextjs-toast] { display: none !important; }";
  const add = () => document.head.appendChild(style);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", add);
  else add();
});
const page = await context.newPage();

const shot = async (name) => {
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${out}/${name}.png` });
  console.log(name);
};
const open = async (route) => {
  await page.goto(`${base}${route}`, { waitUntil: "networkidle" });
  await page.waitForSelector("h1", { timeout: 20000 });
  await page.waitForTimeout(600);
};
const scope = async (provider, next) => {
  await page.goto(`${base}/o/demo?scope=${provider}&month=2026-09&next=${next}`, {
    waitUntil: "networkidle",
  });
  await page.waitForSelector("h1", { timeout: 20000 });
  await page.waitForTimeout(600);
};

await scope("all", "/overview");
await shot("overview");
await page.mouse.wheel(0, 560);
await shot("overview-chart");
await page.mouse.wheel(0, 700);
await shot("overview-people");

await open("/explore?by=person");
await shot("analyze-person");
await page.mouse.wheel(0, 520);
await shot("analyze-table");
await open("/explore?by=model&f=provider%3Ais%3Aanthropic");
await shot("analyze-filter");

await open("/overview");
await page
  .getByRole("button", { name: /Search/ })
  .first()
  .click();
await page.keyboard.type("bruno", { delay: 60 });
await page.waitForTimeout(1200);
await shot("search");
await page.getByRole("dialog").getByText("bruno@sample.example").click();
await page.waitForURL(/\/people\//, { timeout: 20000 });
await page.waitForSelector("h1");
await page.waitForTimeout(900);
await shot("person");
await page.mouse.wheel(0, 420);
await shot("person-chart");

await open("/keys/key_demo_search_indexer?provider=openai");
await page.getByText("Details").first().click();
await page.waitForTimeout(300);
await shot("key-details");

await open("/budgets");
await shot("budgets");
await open("/anomalies");
await shot("anomalies");
await page.locator('a[href*="/anomalies/"]').first().click();
await page.waitForSelector("h1");
await page.waitForTimeout(800);
await shot("anomaly");
await page.mouse.wheel(0, 520);
await shot("anomaly-evidence");

await open("/reconcile");
await shot("reconcile");
await scope("anthropic", "/reconcile");
await shot("reconcile-checks");
await open("/runs");
await shot("runs");
await open("/inventory");
await shot("inventory");
await open("/settings/connections");
await shot("settings-connections");

await browser.close();
