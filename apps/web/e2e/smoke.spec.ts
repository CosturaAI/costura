import { MOCK_API } from "./pages";
import { expect, test } from "@playwright/test";

type Page = import("@playwright/test").Page;

async function signInWithSession(page: Page) {
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

/**
 * Pages carry no organization, scope or month: `/o/{slug}` writes the view cookie
 * and lands on `next`. The specs open a view this way and then walk the fixed addresses.
 */
function openHref(slug: string, next: string, scope = "all", month = "2026-08"): string {
  const query = new URLSearchParams({ scope, month, next });
  return `/o/${slug}?${query.toString()}`;
}

async function open(page: Page, slug: string, next: string, scope = "all", month = "2026-08") {
  await page.goto(openHref(slug, next, scope, month));
  await page.waitForURL((url) => url.pathname + url.search === next);
}

test("renders the development sign-in page", async ({ page }) => {
  await page.goto("/sign-in");

  await expect(page).toHaveTitle(/Costura/);
  await expect(page.getByRole("heading", { name: "Sign in to Costura" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "E-mail" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue" })).toBeVisible();
});

test("downloads CSV through the signed-in same-origin export", async ({ page }) => {
  await signInWithSession(page);
  await open(page, "default", "/overview");
  await expect(page.evaluate(() => document.cookie)).resolves.not.toContain("costura_session");
  await expect(page.evaluate(() => document.cookie)).resolves.not.toContain("costura_view");
  // The link names the query it was rendered for; the organization is the view's.
  await page.setContent(
    '<a href="/api/exports/query?measure=billed_usd&dimensions=model&start=2026-08-01&end=2026-08-31&interval=day&top=10&provider=anthropic&unexpected=blocked">Export CSV</a>',
  );

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("link", { name: "Export CSV" }).click();
  const download = await downloadPromise;
  const stream = await download.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream) chunks.push(Buffer.from(chunk));

  expect(download.suggestedFilename()).toBe("costura-default-2026-08-01-2026-08-31-model.csv");
  expect(Buffer.concat(chunks).toString()).toBe("key,label,amount\nmodel-1,Claude,12.34\n");
});

test("recovers unknown static, organization and entity routes without persistent loading", async ({
  page,
}) => {
  await signInWithSession(page);
  await open(page, "default", "/overview", "anthropic");
  // An address this app does not serve ends on the 404 page. An unknown entity id is
  // answered by the lookup route.
  const cases = [
    { path: "/unknown-static", heading: "Nothing here", recovery: "Go to your organizations" },
    { path: "/o/missing", heading: "Nothing here", recovery: "Go to your organizations" },
    { path: "/keys/unknown", heading: "Not found", recovery: "Connect a provider" },
    { path: "/workspaces/unknown", heading: "Not found", recovery: "Connect a provider" },
  ];

  for (const current of cases) {
    await page.goto(current.path);
    await expect(page.getByRole("heading", { level: 1, name: current.heading })).toBeVisible();
    await expect(page.getByRole("link", { name: current.recovery })).toBeVisible();
    await expect(page.locator('meta[name="robots"]').first()).toHaveAttribute("content", /noindex/);
    await expect(page.locator(".skeleton")).toHaveCount(0);
  }
});

test("the overview names each provider's share and what changed since last month", async ({
  page,
}) => {
  await signInWithSession(page);
  await open(page, "default", "/overview");

  const main = page.getByRole("main");
  // The provider strip sits in the chart card, not in a card of its own.
  const strip = main.getByRole("list", { name: "Spend by provider" });
  await expect(strip).toContainText("Anthropic");
  await expect(strip).toContainText("576.55");
  await expect(strip).toContainText("82.36%");
  await expect(strip).toContainText("OpenRouter");
  await expect(main.getByRole("heading", { name: "By provider" })).toHaveCount(0);

  await main.getByText("More on this period").click();
  const changed = main
    .getByRole("heading", { name: "What changed" })
    .locator("xpath=ancestor::*[@data-slot='card']");
  await expect(changed).toContainText("Each API key's spend against July 2026.");
  const up = changed.getByText("Spending more").locator("xpath=..");
  await expect(up).toContainText("+576.55");
  await expect(up.getByText("new", { exact: true })).toBeVisible();
  await expect(changed.getByText("Spending less").locator("xpath=..")).toContainText("-176.55");
  const markers = main.getByRole("list", { name: "Chart markers" });
  await expect(markers).toContainText("3 open anomalies on 2 days");
  await expect(markers).not.toContainText("Spike anomaly");
});

test("pages with charts do not scroll sideways on a laptop viewport", async ({ page }) => {
  await signInWithSession(page);
  await page.setViewportSize({ width: 1200, height: 800 });

  // The anomaly page is read on the sample organization, which refuses the read mark, so this
  // check does not consume the unread count the bell spec asserts.
  for (const href of [
    openHref("default", "/overview"),
    openHref("demo", "/anomalies/7", "anthropic"),
  ]) {
    await page.goto(href);
    const path = new URL(page.url()).pathname;
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(overflow, `${path} scrolls sideways by ${overflow} px`).toBeLessThanOrEqual(0);
  }
});

test("the account menu and the provider select change the view by keyboard", async ({ page }) => {
  await signInWithSession(page);

  for (const width of [390, 768, 1024]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(openHref("default", "/runs?endpoint=allocation", "anthropic"));
    await expect(page).toHaveURL(/\/runs\?endpoint=allocation$/);
    await expect(page.getByRole("main")).toContainText("jobs for Anthropic");

    // Below the desktop breakpoint the provider select and the account menu sit in the sheet.
    const narrow = width < 1024;
    const sheet = page.getByRole("dialog", { name: "Navigation" });
    const shell = () => (narrow ? sheet : page);
    if (narrow) {
      await page.getByRole("button", { name: "Open navigation" }).focus();
      await page.keyboard.press("Enter");
      await expect(sheet).toBeVisible();
    } else {
      await expect(page.getByRole("button", { name: "Open navigation" })).toBeHidden();
    }
    await expect(shell().getByRole("combobox", { name: /^Provider/ })).toHaveText("Anthropic");

    // The footer menu names the signed-in address and lists the organizations; the active one
    // is checked. Choosing another opens it and keeps the page.
    const account = shell().getByRole("button", { name: /^Account menu/ });
    await expect(account).toContainText("Default organization");
    await account.focus();
    await page.keyboard.press("Enter");
    const menu = page.getByRole("menu");
    await expect(menu).toContainText("e2e@example.com");
    await expect(
      menu.getByRole("menuitem", { name: /Default organization/ }).getByLabel("Active"),
    ).toBeVisible();
    await menu.getByRole("menuitem", { name: /^Acme/ }).focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/runs$/);
    if (narrow) {
      await expect(sheet).toBeHidden();
      await page.getByRole("button", { name: "Open navigation" }).press("Enter");
      await expect(sheet).toBeVisible();
    }
    await expect(shell().getByRole("button", { name: /^Account menu/ })).toContainText("Acme");

    // The provider select writes the view cookie: the address does not change, the page does.
    const provider = shell().getByRole("combobox", { name: /^Provider/ });
    await provider.focus();
    await page.keyboard.press("Enter");
    await page.getByRole("option", { name: "OpenRouter" }).press("Enter");
    await expect(page).toHaveURL(/\/runs$/);
    if (narrow) await expect(sheet).toBeHidden();
    await expect(page.getByRole("main")).toContainText("jobs for OpenRouter");
    await page.reload();
    await expect(page.getByRole("main")).toContainText("jobs for OpenRouter");
  }
});

test("an owner renames the organization; the id stays", async ({ page, request }) => {
  await signInWithSession(page);
  const recordedUrl = `${MOCK_API}/__e2e/requests`;
  const start = ((await (await request.get(recordedUrl)).json()) as unknown[]).length;
  await open(page, "acme", "/settings/organization");

  await expect(page.getByRole("heading", { level: 2, name: "Organization ID" })).toBeVisible();
  await expect(page.locator("code", { hasText: "acme" })).toBeVisible();
  await page.getByLabel("Name").fill("Acme Corporation");
  await page.getByRole("button", { name: "Save name" }).click();
  await expect(page.getByRole("status")).toHaveText("Renamed to Acme Corporation.");
  const recorded = (
    (await (await request.get(recordedUrl)).json()) as { method: string; path: string }[]
  ).slice(start);
  expect(recorded).toContainEqual(
    expect.objectContaining({ method: "PATCH", path: "/api/v1/orgs/acme" }),
  );
});

test("the OpenRouter disconnect confirmation submits that account's form", async ({ page }) => {
  await signInWithSession(page);
  await open(page, "acme", "/settings/connections");

  // Anthropic has two accounts in `acme`: one row each, plus OpenRouter and OpenAI.
  const anthropic = page.getByRole("list", { name: "Anthropic accounts" });
  await expect(anthropic.getByRole("listitem")).toHaveCount(2);
  await expect(anthropic).toContainText("Research");
  await expect(page.getByRole("button", { name: "Add account" })).toHaveCount(4);

  const disconnects = page.getByRole("button", { name: "Remove key", exact: true });
  await expect(disconnects).toHaveCount(5);
  await expect(page.locator("#disconnect-form-openrouter-2 input[name=provider]")).toHaveValue(
    "openrouter",
  );

  await disconnects.nth(2).click();
  const dialog = page.getByRole("alertdialog");
  const confirm = dialog.getByRole("button", { name: "Remove key" });
  await expect(confirm).toHaveAttribute("form", "disconnect-form-openrouter-2");
  await confirm.click();

  // The mock accepts only this provider and never changes its stored connection fixture.
  await expect(page.getByRole("status")).toHaveText("Stored key removed.");
  await page.reload();
  await expect(page.getByRole("heading").filter({ hasText: "OpenRouter" })).toContainText(
    "connected",
  );
});

test("a Codex account requires, adds and deletes credit pricing", async ({ page, request }) => {
  await request.delete(`${MOCK_API}/__e2e/credit-prices`);
  await signInWithSession(page);
  await open(page, "codex", "/settings/connections", "codex");

  const schedule = page.getByRole("region", { name: "Codex credit price schedule" });
  await expect(schedule.getByRole("alert")).toContainText("Pricing required");
  await schedule.getByLabel("Effective from").fill("2026-09-18");
  await schedule.getByLabel("USD per credit").fill("0.08");
  await schedule.getByRole("button", { name: "Add rate" }).click();

  const rates = schedule.getByRole("list", { name: "Effective credit rates" });
  await expect(rates).toContainText("2026-09-18 - 0.08000000 USD");
  await schedule.getByRole("button", { name: "Delete the rate from 2026-09-18" }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText("rate from 2026-09-18?");
  await dialog.getByRole("button", { name: "Delete rate" }).click();
  await expect(schedule.getByRole("alert")).toContainText("Pricing required");

  const recorded = (await (await request.get(`${MOCK_API}/__e2e/requests`)).json()) as {
    method: string;
    path: string;
  }[];
  expect(recorded).toContainEqual({
    method: "POST",
    path: "/api/v1/orgs/codex/accounts/7/credit-prices",
  });
  expect(recorded).toContainEqual({
    method: "DELETE",
    path: "/api/v1/orgs/codex/accounts/7/credit-prices/1",
  });
});

test("the settings sub-navigation walks the sections on a narrow viewport", async ({ page }) => {
  await signInWithSession(page);
  await page.setViewportSize({ width: 390, height: 780 });
  // The section-less address belongs to the first section.
  await page.goto(openHref("acme", "/settings"));
  await expect(page).toHaveURL(/\/settings\/connections$/);

  const section = page.getByLabel("Settings section", { exact: true });
  await expect(section).toHaveValue("connections");
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();

  await section.selectOption("sync");
  await page.getByRole("button", { name: "Open", exact: true }).click();
  await expect(page).toHaveURL(/\/settings\/sync$/, { timeout: 15_000 });
  await expect(page.getByRole("button", { name: "Sync now" })).toBeVisible();
  // A working key is not asked for again: the field waits behind the button.
  await expect(page.getByLabel("New admin key")).toHaveCount(0);

  await section.selectOption("members");
  await page.getByRole("button", { name: "Open", exact: true }).click();
  await expect(page.getByRole("table", { name: "Members" })).toBeVisible();

  await section.selectOption("account");
  await page.getByRole("button", { name: "Open", exact: true }).click();
  await expect(page.getByRole("heading", { level: 2, name: "Your sessions" })).toBeVisible();

  await section.selectOption("advanced");
  await page.getByRole("button", { name: "Open", exact: true }).click();
  await expect(page.getByRole("button", { name: "Reset onboarding" })).toBeVisible();
});

test("a zero-token Explore row keeps its attributed amount on the API-key page", async ({
  page,
}) => {
  await signInWithSession(page);
  await open(page, "default", "/explore?by=api_key", "anthropic");

  const table = page.getByRole("table", {
    name: "Spend by api key, 2026-08-01 to 2026-08-31",
  });
  const keyLink = table.getByRole("link", { name: "zero-token-key" });
  const row = table.getByRole("row", { name: /zero-token-key/ });
  await expect(row).toContainText("123.45");
  await expect(row.getByRole("cell").last()).toHaveText(/tokens\s*0$/);
  // A row of the provider's default account carries no badge; a row of a named account names
  // it after the provider.
  await expect(row).not.toContainText("Anthropic");
  const researchRow = table
    .getByRole("link", { name: "batch-ingest" })
    .locator("xpath=ancestor::tr");
  await expect(researchRow).toContainText("Anthropic - Research");

  await keyLink.click();
  await expect(page).toHaveURL(/\/keys\/key-zero-tokens$/);
  await expect(page.getByRole("heading", { level: 1, name: "zero-token-key" })).toBeVisible();

  const figures = page.getByRole("region", { name: "Headline figures" });
  await expect(
    figures.getByText("Spend in August 2026", { exact: true }).locator(".."),
  ).toContainText("123.45");
  await page.getByText("Details").click();
  await expect(page.getByText("Tokens", { exact: true }).locator("..")).toContainText("0");
});

test("Explore builds, exports and removes operator filters", async ({ page }) => {
  await signInWithSession(page);
  await open(page, "default", "/explore?by=model", "anthropic");

  await page.getByText("Add filter", { exact: true }).first().click();
  await expect(page.getByRole("heading", { name: "Add filter" })).toBeVisible();
  await page.getByLabel("Operator").selectOption("is_not");
  await page.getByRole("combobox", { name: "Value" }).fill("claude-sonnet-4");
  await page.getByRole("button", { name: "Add filter" }).click();

  await expect(page).toHaveURL(/f=model%3Ais_not%3Aclaude-sonnet-4/);
  const chip = page.getByRole("link", { name: /Model is not claude-sonnet-4/ });
  await expect(chip).toBeVisible();
  await expect(page.getByRole("link", { name: "Export CSV" })).toHaveAttribute(
    "href",
    /f=model%3Ais_not%3Aclaude-sonnet-4/,
  );
  await expect(page.getByRole("status").getByText("No spend matches these filters.")).toBeVisible();

  await chip.click();
  await expect(page).toHaveURL(/\/explore\?by=model$/);
  await expect(page.getByRole("link", { name: /Model is not/ })).toHaveCount(0);
});

test("rapid Explore chip changes compose in one query", async ({ page }) => {
  await signInWithSession(page);
  await open(page, "default", "/explore?by=api_key", "anthropic");

  await page.getByText("View options").click();
  await page.getByRole("link", { name: "Delta", exact: true }).click({ noWaitAfter: true });
  await page.getByRole("link", { name: "Top 10", exact: true }).click({ noWaitAfter: true });

  await expect(page).toHaveURL(/display=delta/);
  await expect(page).toHaveURL(/top=10/);
  await expect(page.getByRole("link", { name: "Delta", exact: true })).toHaveAttribute(
    "aria-current",
    "true",
  );
  await expect(page.getByRole("link", { name: "Top 10", exact: true })).toHaveAttribute(
    "aria-current",
    "true",
  );
});

test("Explore changes display, projection, axis and table orientation", async ({ page }) => {
  await signInWithSession(page);
  await open(
    page,
    "default",
    "/explore?by=api_key&top=200&display=daily_average&axis=dimension&projection=linear&lookback=4&horizon=4",
    "anthropic",
  );

  await expect(page.getByRole("link", { name: "Top 200" })).toHaveAttribute("aria-current", "true");
  await expect(page.getByRole("link", { name: "Daily average", exact: true })).toHaveAttribute(
    "aria-current",
    "true",
  );
  await expect(page.getByRole("link", { name: "Linear projection" })).toHaveAttribute(
    "aria-current",
    "true",
  );
  await expect(page.getByRole("table", { name: /bucket columns/ })).toBeVisible();

  await page.getByRole("link", { name: "Time x-axis" }).click();
  await expect(page).toHaveURL(/axis=time/);
  await expect(page.getByRole("list", { name: "Legend" })).toContainText("projected");
});

test("an Explore person row opens the person page with one identity per provider", async ({
  page,
}) => {
  await signInWithSession(page);
  await open(page, "default", "/explore?by=person");

  const table = page.getByRole("table", {
    name: "Spend by person, 2026-08-01 to 2026-08-31",
  });
  const link = table.getByRole("link", { name: "ana@example.com" });
  await link.click();
  await expect(page).toHaveURL(/\/people\/ana%40example\.com$/);
  await expect(page.getByRole("heading", { level: 1, name: "ana@example.com" })).toBeVisible();
  await expect(page.getByText("Anthropic admin")).toBeVisible();
  await expect(page.getByText("OpenAI owner")).toBeVisible();
  await page.getByText("Details").click();
  await expect(page.getByRole("link", { name: "user-ana" })).toHaveAttribute(
    "href",
    "/accounts/user-ana",
  );
  await page.getByText("Further breakdowns").click();
  await expect(page.getByRole("heading", { name: /^By model$/ })).toBeVisible();

  const figures = page.getByRole("region", { name: "Headline figures" });
  await expect(
    figures.getByText("Spend in August 2026", { exact: true }).locator(".."),
  ).toContainText("700.00");
});

test("an anomaly opens to its owners and figures, and the bell walks opt-in to read", async ({
  page,
  request,
}) => {
  await request.delete(`${MOCK_API}/__e2e/requests`);
  await signInWithSession(page);
  await open(page, "default", "/anomalies");
  await expect(page.getByRole("region", { name: "Anomaly feed" })).toBeVisible();

  // Not opted in yet: the bell carries no count and offers the switch.
  const bell = page.getByRole("button", { name: /^Alerts/ });
  await expect(bell).toHaveAccessibleName("Alerts");
  await bell.click();
  const dialog = page.getByRole("dialog", { name: "Alerts" });
  await dialog.getByRole("button", { name: "Turn alerts on" }).click();
  // The panel reloads the inbox after the opt-in: every open anomaly and the budget alert
  // are unread.
  await expect(page.getByRole("button", { name: "Alerts, 4 unread" })).toBeVisible();
  await expect(dialog.getByText("4 unread: 3 anomalies, 1 budget")).toBeVisible();
  await page.keyboard.press("Escape");

  // The card title opens the anomaly; impact leads, the percentage is secondary.
  const main = page.getByRole("main");
  const feed = main.getByRole("region", { name: "Anomaly feed" });
  await expect(feed.getByText("+810.00 USD")).toBeVisible();
  await expect(feed.getByText("115.7% of the period's spend").first()).toBeVisible();
  await expect(feed.getByText("high severity").first()).toBeVisible();
  await expect(feed.getByText("medium severity")).toBeVisible();
  await feed.getByRole("link", { name: "zero-token-key" }).click();
  await expect(page).toHaveURL(/\/anomalies\/7$/);
  // The page names the provider the anomaly belongs to, since the address does not.
  await expect(
    page.getByRole("main").getByText("Anthropic", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("zero-token-key");
  await expect(page.getByRole("heading", { level: 2, name: "Who to contact" })).toBeVisible();
  await expect(main.getByRole("link", { name: "ana@example.com" })).toHaveAttribute(
    "href",
    "mailto:ana@example.com",
  );
  await expect(main.getByText("created the key", { exact: true })).toBeVisible();
  const figures = page.getByRole("region", { name: "Headline figures" });
  const impact = figures
    .getByText("Impact", { exact: true })
    .locator("xpath=ancestor::*[@data-slot='card']");
  await expect(impact).toContainText("+810.00");
  // The share of the month is the Impact hint, next to the money it qualifies.
  await expect(impact).toContainText("12.4% of its month's spend to date");
  await expect(
    figures.getByText("Severity", { exact: true }).locator("xpath=ancestor::*[@data-slot='card']"),
  ).toContainText("high");
  await expect(page.getByRole("heading", { name: "What normal looked like" })).toBeVisible();
  await page.getByText("Evidence").click();
  // The evidence: every check with its verdict, the baseline samples, the day's rows.
  await expect(
    main.getByText("8 of 8 checks hold; the margin came from the MAD multiple of the sensitivity."),
  ).toBeVisible();
  const checks = main.getByRole("table", { name: "Detection checks" });
  await expect(checks.getByText("holds")).toHaveCount(8);
  await expect(checks.getByRole("row", { name: /Above the upper bound/ })).toContainText("890.00");
  await expect(main.getByRole("table", { name: "Baseline samples" }).getByRole("row")).toHaveCount(
    9,
  );
  await expect(main.getByText("fixed the bound")).toBeVisible();
  await expect(
    main.getByRole("table", { name: /Spend on the anomaly day by Model/ }).getByRole("row"),
  ).toHaveCount(3);
  await expect(main.getByRole("link", { name: "Costs" })).toHaveAttribute(
    "href",
    "/runs?endpoint=cost_report",
  );
  await expect(main.getByRole("button", { name: "Acknowledge" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open the key" })).toHaveAttribute(
    "href",
    "/keys/key-zero-tokens",
  );

  // Opening the anomaly marks it read; the other open one stays unread and links from the bell.
  await expect
    .poll(async () => {
      const writes = await (await request.get(`${MOCK_API}/__e2e/requests`)).json();
      return writes.filter((w: { path: string }) => w.path.endsWith("/alerts/read")).length;
    })
    .toBeGreaterThan(0);
  await page.goto("/overview");
  await page.getByRole("button", { name: "Alerts, 3 unread" }).click();
  const list = page.getByRole("dialog", { name: "Alerts" });
  await expect(list.getByText("3 unread: 2 anomalies, 1 budget")).toBeVisible();
  const totals = list.getByRole("link", { name: "organization total" });
  await expect(totals.first()).toHaveAttribute("href", "/anomalies/8");
  await expect(totals.last()).toHaveAttribute("href", "/budgets");
  await expect(list.getByText("projected over the budget")).toBeVisible();
  // The inventory ties no contributor to a person: the bell says so instead of "Contact".
  await expect(list.getByText(/Nobody recorded in the provider inventory; fallback/)).toBeVisible();

  // Mark all read empties the badge; the settings card shows the opt-in and turns it off.
  await list.getByRole("button", { name: "Mark all read" }).click();
  await expect(page.getByRole("button", { name: "Alerts" })).toBeVisible();

  // An organization anomaly tables the day by principal, model and workspace; the tab
  // switches the table.
  await page.goto("/anomalies/8");
  await page.getByText("Evidence").click();
  await expect(page.getByText("fallback", { exact: true })).toBeVisible();
  await expect(
    page.getByText(/listed as a fallback; they are not the people behind the spend/),
  ).toBeVisible();
  await expect(
    page.getByRole("table", { name: /Spend on the anomaly day by API key/ }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Model" }).click();
  await expect(
    page.getByRole("table", { name: /Spend on the anomaly day by Model/ }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "API key" }).click();
  const keys = page.getByRole("table", { name: /Spend on the anomaly day by API key/ });
  await expect(keys.getByText("new", { exact: true })).toBeVisible();
  await expect(keys.getByRole("link", { name: "migration-script" })).toHaveAttribute(
    "href",
    "/keys/apikey_new",
  );

  await page.goto("/settings/account");
  const card = page
    .getByRole("heading", { level: 2, name: "Alerts" })
    .locator("xpath=ancestor::*[@data-slot='card']");
  await expect(card.getByRole("button", { name: "Turn alerts off" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await card.getByRole("button", { name: "Turn alerts off" }).click();
  await expect(page.getByRole("status")).toHaveText("Alerts are off for this organization.");
});

test("the anomaly list names a drop with its run", async ({ page }) => {
  await signInWithSession(page);
  await open(page, "default", "/anomalies");

  // A three-day drop is one row: the rule, the run and the money missing over it.
  const main = page.getByRole("main");
  const card = main
    .getByRole("region", { name: "Anomaly feed" })
    .getByRole("link", { name: "batch-ingest" })
    .locator("xpath=ancestor::*[@data-slot='card']");
  await expect(card.getByText("drop", { exact: true })).toBeVisible();
  await expect(card.getByText("-1,470.00 USD")).toBeVisible();
  await expect(card.getByText("ongoing, 3 days so far")).toBeVisible();
  await expect(card).toContainText("80.33% under the baseline");
});

test("the sample organization anomaly list exposes no mutation controls", async ({ page }) => {
  await signInWithSession(page);
  await open(page, "demo", "/anomalies", "anthropic");

  const main = page.getByRole("main");
  await expect(
    main.getByRole("heading", { level: 1, name: "Anomalies in August 2026" }),
  ).toBeVisible();
  await expect(
    main
      .getByRole("region", { name: "Anomaly feed" })
      .getByRole("link", { name: "zero-token-key" }),
  ).toBeVisible();
  await expect(main.getByRole("checkbox")).toHaveCount(0);
  await expect(main.getByRole("button", { name: "Acknowledge" })).toHaveCount(0);
  await expect(main.getByRole("button", { name: "Ignore" })).toHaveCount(0);
  await expect(main.getByRole("button", { name: "Reopen" })).toHaveCount(0);
  await expect(main.locator("form")).toHaveCount(0);
});

test("a visitor without a session reads the sample organization and is offered sign-in", async ({
  page,
}) => {
  await page.goto(openHref("demo", "/anomalies", "anthropic"));

  await expect(page).toHaveURL(/\/anomalies$/);
  const main = page.getByRole("main");
  await expect(
    main.getByRole("heading", { level: 1, name: "Anomalies in August 2026" }),
  ).toBeVisible();
  await expect(
    main
      .getByRole("region", { name: "Anomaly feed" })
      .getByRole("link", { name: "zero-token-key" }),
  ).toBeVisible();
  await expect(main.locator("form")).toHaveCount(0);
  const band = page.getByRole("region", { name: "Sample organization" });
  await expect(band).toContainText("is a fictional company");
  await expect(band.getByRole("link", { name: "Sign in to connect yours" })).toHaveAttribute(
    "href",
    "/sign-in",
  );
  const sidebar = page.getByRole("complementary", { name: "Sidebar" });
  await expect(sidebar.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/sign-in");
  await expect(sidebar.getByRole("button", { name: /^Account menu/ })).toHaveCount(0);

  // Opening an organization the visitor would have to be a member of asks for a session.
  await page.goto("/o/default");
  await expect(page).toHaveURL(/\/sign-in$/);
  await expect(page.getByRole("link", { name: "Explore the sample organization" })).toHaveAttribute(
    "href",
    "/o/demo",
  );
});

test("all-provider Reconcile retains disconnected providers with month data", async ({ page }) => {
  await signInWithSession(page);
  await open(page, "default", "/reconcile");

  const heading = page.getByRole("heading").filter({ hasText: "OpenRouter" });
  const card = heading.locator("xpath=ancestor::*[@data-slot='card']");
  await expect(heading).toContainText("disconnected");
  await expect(card).toContainText("This is historical data from a disconnected provider.");
  await expect(card).toContainText("456.78 USD");
  await expect(card.getByRole("link", { name: "See the checks" })).toHaveAttribute(
    "href",
    "/o/default?scope=openrouter&from=2026-08-01&to=2026-08-31&next=%2Freconcile",
  );
});

test("an owner invites an address and a second identity joins through the link", async ({
  page,
  request,
}) => {
  await request.delete(`${MOCK_API}/__e2e/invitations`);
  await signInWithSession(page);
  await open(page, "default", "/settings/members");

  // The invite card comes first, with what each role may do next to the picker.
  const invite = page
    .getByRole("heading", { name: "Invite someone" })
    .locator("xpath=ancestor::*[@data-slot='card']");
  await expect(invite).toContainText("Costura sends no e-mail");
  await invite.getByLabel("E-mail").fill("newcomer@example.com");
  await invite.getByLabel("Role").selectOption("member");
  await invite.getByRole("button", { name: "Invite" }).click();

  // The link is shown once, bound to the address, and copyable.
  await expect(invite).toContainText("only newcomer@example.com can use it");
  const link = await invite.locator("code").innerText();
  expect(link).toMatch(/\/join\/e2e-token-\d+$/);
  await expect(invite.getByRole("button", { name: "Copy the invitation link" })).toBeVisible();

  // It is listed as pending until somebody claims it.
  await page.reload();
  const pending = page.getByRole("table", { name: "Pending invitations" });
  const row = pending.getByRole("row").filter({ hasText: "newcomer@example.com" });
  await expect(row).toContainText("Member");
  await expect(row.getByRole("button", { name: "Revoke" })).toBeVisible();

  // The second identity opens the link and lands inside the organization.
  await page.context().clearCookies();
  const path = new URL(link).pathname;
  await page.goto(path);
  await expect(page).toHaveURL(`/sign-in?next=${path}`);
  await page.context().addCookies([
    {
      name: "costura_session",
      value: "e2e-invitee",
      url: new URL(page.url()).origin,
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  await page.goto(path);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Join Default organization");
  await page.getByRole("button", { name: "Accept invitation" }).click();
  await expect(page).toHaveURL(/\/overview$/);
  await expect(page.getByRole("button", { name: /^Account menu/ }).first()).toContainText(
    "Default organization",
  );

  // Nothing waits for them afterwards; the join page says so instead of showing a blank list.
  await page.goto("/join");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("No invitation waiting");
});

test("Copy link reproduces the Analyze view", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await signInWithSession(page);
  await open(page, "default", "/explore?by=workspace", "anthropic");
  await page.getByRole("button", { name: "Copy link" }).click();
  await expect(page.getByRole("button", { name: "Copied" })).toBeVisible();
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  const link = new URL(copied);
  expect(link.pathname).toBe("/o/default");
  expect(link.searchParams.get("scope")).toBe("anthropic");
  const view = new URL(link.searchParams.get("next") ?? "", link.origin);
  expect(view.pathname).toBe("/explore");
  expect(view.searchParams.get("by")).toBe("workspace");

  const second = await context.newPage();
  await second.goto(copied);
  await expect(
    second.getByRole("table", { name: /^Spend by workspace, 2026-08-01 to 2026-08-31$/ }),
  ).toBeVisible();
  await second.close();
});

test("the overview chart marks the days with an anomaly", async ({ page }) => {
  await signInWithSession(page);
  await open(page, "default", "/overview");
  await expect(page.getByRole("list", { name: "Chart markers" })).toContainText(
    /anomal(y|ies) on \d+ days?/,
  );
});

test("How detection works explains the baseline on the anomaly list", async ({ page }) => {
  await signInWithSession(page);
  await open(page, "default", "/anomalies");
  const explainer = page.getByText("How detection works");
  await explainer.click();
  await expect(page.getByText(/falls below its lower bound/)).toBeVisible();
});

test("a key with no person counts under Service key", async ({ page }) => {
  await signInWithSession(page);
  await open(page, "default", "/keys/key-zero-tokens", "anthropic");
  const term = page.getByText("Counts under", { exact: true });
  await expect(term.locator("..")).toContainText("Service key");
});

test("Unused in the month narrows the key list to keys without usage", async ({ page }) => {
  await signInWithSession(page);
  await open(page, "default", "/inventory", "anthropic");
  const toggle = page.getByRole("button", { name: /^Unused in / });
  const count = page.getByText(/^\d+ of \d+ /);
  const [before, total] = ((await count.textContent()) ?? "").match(/\d+/g)!.map(Number);
  expect(before).toBe(total);
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await expect(count).not.toHaveText(new RegExp(`^${total} of ${total} `));
});

test.describe("resource search", () => {
  for (const [size, viewport] of [
    ["desktop", { width: 1440, height: 900 }],
    ["mobile", { width: 390, height: 844 }],
  ] as const) {
    test(`opens from the ${size} keyboard and from touch, then each current resource`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      await signInWithSession(page);
      await open(page, "default", "/overview");

      await page.keyboard.press("Control+k");
      const dialog = page.getByRole("dialog", { name: "Search resources" });
      await expect(dialog).toBeVisible();
      await expect(dialog.getByRole("combobox", { name: "Search resources" })).toBeFocused();
      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();

      const button = page.getByRole("button", { name: "Search resources" });
      await button.click();
      await expect(dialog).toBeVisible();
      await page.keyboard.press("Meta+k");
      await expect(dialog).toBeHidden();

      const cases = [
        {
          query: "ana@",
          name: "ana@example.com",
          path: "/people/ana@example.com",
          account: null,
        },
        { query: "billing", name: "billing-bot", path: "/accounts/svc_billing", account: "1" },
        { query: "zero", name: "zero-token-key", path: "/keys/key-zero-tokens", account: "4" },
        { query: "platform", name: "Platform", path: "/workspaces/wrkspc_platform", account: "1" },
      ] as const;
      for (const item of cases) {
        await button.click();
        await dialog.getByRole("combobox", { name: "Search resources" }).fill(item.query);
        await dialog.getByRole("option", { name: item.name }).click();
        await expect
          .poll(() => {
            const url = new URL(page.url());
            return {
              path: decodeURIComponent(url.pathname),
              provider: url.searchParams.get("provider"),
              account: url.searchParams.get("provider_account"),
            };
          })
          .toEqual({
            path: item.path,
            provider: item.account === null ? null : "anthropic",
            account: item.account,
          });
        await expect(page.getByRole("heading", { level: 1 })).toContainText(item.name);
      }
    });
  }
});
