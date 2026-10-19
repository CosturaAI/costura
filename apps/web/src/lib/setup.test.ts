import { describe, expect, it } from "vitest";

import {
  awaitingFirstRun,
  firstImportComplete,
  gettingStartedItems,
  keyHint,
  landingHref,
  openOrgHref,
  runStatusLabel,
  runStatusText,
  runStatusTone,
  runsAction,
  shouldPoll,
  showSyncBanner,
  syncAction,
} from "@/lib/setup";
import * as fx from "@/test/fixtures";

describe("landingHref", () => {
  it("keeps a fresh organization on the welcome page", () => {
    expect(landingHref(fx.setupConnect)).toBe("/welcome");
  });

  it("opens the overview once a key exists; the view cookie picks the month", () => {
    expect(landingHref(fx.setupSyncing)).toBe("/overview");
    expect(landingHref(fx.setupSyncingFailed)).toBe("/overview");
    expect(landingHref(fx.setupReady)).toBe("/overview");
  });
});

describe("openOrgHref", () => {
  it("names the organization once, with the view hints and the page to land on", () => {
    expect(openOrgHref("default")).toBe("/o/default");
    expect(openOrgHref("default", "/welcome")).toBe("/o/default?next=%2Fwelcome");
    expect(openOrgHref("acme", "/reconcile", { scope: "openai", month: "2026-08" })).toBe(
      "/o/acme?scope=openai&month=2026-08&next=%2Freconcile",
    );
    expect(openOrgHref("acme", undefined, { scope: null, month: null })).toBe("/o/acme");
  });
});

describe("empty-state actions", () => {
  it("sends Sync now to the sync section of settings", () => {
    expect(syncAction()).toEqual({ href: "/settings/sync", label: "Sync now from settings" });
  });

  it("sends the import question to the run history", () => {
    expect(runsAction()).toEqual({ href: "/runs", label: "See what the last import covered" });
  });
});

describe("run status pill", () => {
  it("words and colours each run status", () => {
    expect(runStatusLabel("queued")).toBe("Queued");
    expect(runStatusLabel("running")).toBe("Importing");
    expect(runStatusLabel(null)).toBe("Importing");
    expect(runStatusLabel("succeeded")).toBe("Ready");
    expect(runStatusLabel("failed")).toBe("Failed");
    expect(runStatusLabel("skipped")).toBe("Skipped");
    expect(runStatusTone("running")).toBe("info");
    expect(runStatusTone("queued")).toBe("info");
    expect(runStatusTone("succeeded")).toBe("success");
    expect(runStatusTone("failed")).toBe("critical");
    expect(runStatusTone("skipped")).toBe("neutral");
  });
});

describe("shouldPoll", () => {
  it("polls while a run is in progress or a connected provider has no run yet", () => {
    expect(shouldPoll(fx.setupSyncing)).toBe(true);
    expect(shouldPoll({ ...fx.setupSyncing, runs: [{ ...fx.runningRun, status: "queued" }] })).toBe(
      true,
    );
    const enqueued = { ...fx.setupSyncing, runs: [] };
    expect(awaitingFirstRun(enqueued).map((p) => p.provider)).toEqual(["anthropic"]);
    expect(shouldPoll(enqueued)).toBe(true);
  });

  it("stops on a failed first run, before any key and once ready and idle", () => {
    expect(shouldPoll(fx.setupSyncingFailed)).toBe(false);
    expect(shouldPoll(fx.setupConnect)).toBe(false);
    expect(shouldPoll(fx.setupReady)).toBe(false);
  });

  it("keeps polling a ready organization while a run is in progress", () => {
    const secondProvider = {
      ...fx.setupReady,
      runs: [fx.succeededRun, { ...fx.runningRun, id: 40, provider: "openrouter" }],
    };
    expect(shouldPoll(secondProvider)).toBe(true);
    // A provider whose key was just accepted and has no run row yet counts too.
    expect(shouldPoll({ ...fx.setupReady, runs: [fx.succeededRun] })).toBe(true);
  });
});

describe("sync banner helpers", () => {
  it("shows the banner while polling or after a failed run without data", () => {
    expect(showSyncBanner(fx.setupSyncing)).toBe(true);
    expect(showSyncBanner(fx.setupSyncingFailed)).toBe(true);
    expect(
      showSyncBanner({ ...fx.setupSyncing, runs: [{ ...fx.failedRun, status: "skipped" }] }),
    ).toBe(true);
  });

  it("hides the banner before any key and once ready and idle", () => {
    expect(showSyncBanner(fx.setupConnect)).toBe(false);
    expect(showSyncBanner(fx.setupReady)).toBe(false);
    // A failed later run on a ready organization is the freshness pill's business.
    expect(showSyncBanner({ ...fx.setupReady, runs: [fx.failedRun, fx.setupReady.runs[1]!] })).toBe(
      false,
    );
  });

  it("marks the first import complete on a succeeded run or a ready state", () => {
    expect(firstImportComplete(fx.setupConnect)).toBe(false);
    expect(firstImportComplete(fx.setupSyncing)).toBe(false);
    expect(firstImportComplete(fx.setupSyncingFailed)).toBe(false);
    expect(firstImportComplete({ ...fx.setupSyncing, runs: [fx.succeededRun] })).toBe(true);
    expect(firstImportComplete(fx.setupReady)).toBe(true);
  });

  it("words the status line per run state", () => {
    expect(runStatusText(null)).toBe("Key accepted; the first import is starting.");
    expect(runStatusText({ ...fx.runningRun, status: "queued" })).toMatch(/^Waiting for/);
    expect(runStatusText(fx.runningRun)).toMatch(/^Importing costs, usage and inventory/);
    expect(runStatusText(fx.failedRun)).toMatch(/^The import failed/);
    expect(
      runStatusText({ ...fx.failedRun, status: "skipped", error: "scheduler lock held" }),
    ).toBe("scheduler lock held");
    expect(runStatusText(fx.succeededRun)).toBe("Imported; the overview is ready.");
  });
});

describe("keyHint", () => {
  it("names the console path for the registered providers", () => {
    expect(keyHint(fx.anthropicInfo)[0]).toBe("Anthropic Console -> Settings -> Admin keys.");
    expect(keyHint(fx.openRouterInfo)[1]).toMatch(/not a regular API key/);
    expect(keyHint({ ...fx.anthropicInfo, provider: "openai" })[0]).toBe(
      "OpenAI platform -> Organization settings -> Admin keys.",
    );
    expect(keyHint({ ...fx.anthropicInfo, provider: "openai" })[1]).toMatch(/sk-admin-/);
  });

  it("builds a generic hint from the registry facts for an unknown provider", () => {
    const [where, how] = keyHint({
      ...fx.anthropicInfo,
      provider: "acme",
      console_label: "Acme console",
      key_label: "org key",
      key_prefix: "ak-",
    });
    expect(where).toBe("Acme console -> Settings.");
    expect(how).toBe("Create a org key; it starts with ak-.");
  });
});

describe("gettingStartedItems", () => {
  it("lists three items while the first import runs, none done", () => {
    const items = gettingStartedItems(fx.setupSyncing, { budgets: 0, anomalies: 0 });
    expect(items.map((i) => [i.label, i.done, i.href])).toEqual([
      ["First import complete", false, "/runs"],
      ["Connect a second provider", false, "/welcome"],
      ["Set a monthly budget", false, "/budgets"],
    ]);
  });

  it("ticks the first import once a run succeeded or the state is ready", () => {
    const items = gettingStartedItems(
      { ...fx.setupReady, providers: fx.providersOneConnected },
      { budgets: 0, anomalies: 0 },
    );
    expect(items.map((i) => [i.id, i.done])).toEqual([
      ["first-import", true],
      ["second-provider", false],
      ["budget", false],
    ]);
  });

  it("ticks the items and adds the anomalies one once something was flagged", () => {
    const items = gettingStartedItems(fx.setupReady, { budgets: 2, anomalies: 3 });
    expect(items.map((i) => [i.id, i.done])).toEqual([
      ["first-import", true],
      ["second-provider", true],
      ["budget", true],
      ["anomalies", false],
    ]);
    expect(items).toHaveLength(4);
    expect(items[3]!.href).toBe("/anomalies");
  });
});
