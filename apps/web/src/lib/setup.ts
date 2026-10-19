import type { ProviderInfo, SchedulerRun, SchedulerRunStatus, Setup } from "@/lib/api";

/**
 * First-run flow helpers shared by `/`, the welcome page, the overview card and the settings
 * Sync now form. The state itself comes from `GET /orgs/{org}/setup`; this file only turns it
 * into addresses, labels and polling decisions.
 */

/** "YYYY-MM" of today in UTC; the fallback month when the organization has no cost lines. */
export function currentMonth(): string {
  return new Date().toISOString().slice(0, 7);
}

/** The welcome page of the active organization; the address names no organization. */
export function welcomeHref(): string {
  return "/welcome";
}

export function overviewHref(): string {
  return "/overview";
}

/** `/o/{slug}` writes the view cookie for `slug` and lands on `next`: the one address that
 * names an organization. */
export function openOrgHref(
  slug: string,
  next?: string,
  view: {
    month?: string | null;
    scope?: string | null;
    from?: string;
    to?: string;
    timeFrame?: string | null;
  } = {},
): string {
  const query = new URLSearchParams();
  if (view.scope) query.set("scope", view.scope);
  if (view.month) query.set("month", view.month);
  if (view.from && view.to) {
    query.set("from", view.from);
    query.set("to", view.to);
  }
  if (view.timeFrame) query.set("time_frame", view.timeFrame);
  if (next) query.set("next", next);
  const suffix = query.toString();
  return `/o/${encodeURIComponent(slug)}${suffix ? `?${suffix}` : ""}`;
}

type SetupAction = { href: string; label: string };

/** Empty-state link of a scope with a connected key: Sync now lives in the sync settings. */
export function syncAction(): SetupAction {
  return { href: "/settings/sync", label: "Sync now from settings" };
}

/** Empty-state link when the import already happened: the run history says what it covered. */
export function runsAction(): SetupAction {
  return { href: "/runs", label: "See what the last import covered" };
}

/**
 * Where `/` sends the browser: the welcome page while no provider has a key; the overview
 * once a key exists, with the sync banner following the first import until the month is in.
 */
export function landingHref(setup: Setup): string {
  if (setup.state === "connect" || setup.state === "needs_pricing" || setup.needs_pricing) {
    return welcomeHref();
  }
  return overviewHref();
}

type RunTone = "info" | "success" | "critical" | "neutral";

/** Status pill of a provider row in the sync banner. */
export function runStatusLabel(status: SchedulerRunStatus | null): string {
  switch (status) {
    case "queued":
      return "Queued";
    case "succeeded":
      return "Ready";
    case "failed":
      return "Failed";
    case "skipped":
      return "Skipped";
    default:
      return "Importing";
  }
}

export function runStatusTone(status: SchedulerRunStatus | null): RunTone {
  switch (status) {
    case "succeeded":
      return "success";
    case "failed":
      return "critical";
    case "skipped":
      return "neutral";
    default:
      return "info";
  }
}

/** Latest run of one provider from the `setup.runs` list, or null before its first run. */
export function runFor(runs: SchedulerRun[], provider: string): SchedulerRun | null {
  return runs.find((run) => run.provider === provider) ?? null;
}

export function anyRunning(runs: SchedulerRun[]): boolean {
  return runs.some((run) => run.status === "queued" || run.status === "running");
}

/** Connected providers whose first run has not been recorded yet (the PUT enqueued it). */
export function awaitingFirstRun(setup: Setup): ProviderInfo[] {
  return setup.providers.filter((p) => p.connected && runFor(setup.runs, p.provider) === null);
}

/**
 * Whether the banner keeps asking for `setup`: only while something can still change on its
 * own, that is a run in progress or a connected provider whose run has not appeared yet,
 * whatever the state (a second provider added to a ready organization is followed too). A
 * failed run stops the polling; Retry starts it again.
 */
export function shouldPoll(setup: Setup): boolean {
  return anyRunning(setup.runs) || awaitingFirstRun(setup).length > 0;
}

/** Whether any import has landed: a succeeded run, or a month with cost lines already. */
export function firstImportComplete(setup: Setup): boolean {
  return setup.state === "ready" || setup.runs.some((run) => run.status === "succeeded");
}

/**
 * Whether the sync banner has something to say on first render: a run to follow, or a
 * failed or skipped latest run while no month has cost lines yet (the Retry lives there).
 */
export function showSyncBanner(setup: Setup): boolean {
  if (shouldPoll(setup)) return true;
  if (setup.state === "ready") return false;
  return setup.runs.some((run) => run.status === "failed" || run.status === "skipped");
}

const WORKER_STALE_MS = 60_000;
const QUEUE_WAIT_MS = 20_000;

function workerAbsent(seenAt: string | null | undefined, queuedAt: string): boolean {
  const queuedFor = Date.now() - Date.parse(queuedAt);
  if (!Number.isFinite(queuedFor) || queuedFor < QUEUE_WAIT_MS) return false;
  if (!seenAt) return true;
  const seen = Date.parse(seenAt);
  return !Number.isFinite(seen) || Date.now() - seen > WORKER_STALE_MS;
}

/** One line under a provider's status pill while its import runs, fails or lands. */
export function runStatusText(
  run: SchedulerRun | null,
  setup?: { worker_seen_at?: string | null } | null,
): string {
  if (run === null) return "Key accepted; the first import is starting.";
  switch (run.status) {
    case "queued":
      if (setup && workerAbsent(setup.worker_seen_at, run.started_at)) {
        return "No worker has picked up this import. Start the worker; see docs/operations/install.md.";
      }
      return "Waiting for the worker. Another import may hold the organization lock.";
    case "running":
      return "Importing costs, usage and inventory for recent months.";
    case "failed":
      return "The import failed; the failed steps are listed under Show steps.";
    case "skipped":
      return run.error ?? "The import was skipped.";
    default:
      return "Imported; the overview is ready.";
  }
}

/** Two lines telling where the key is created; the registry gives the console name and link. */
const KEY_HINTS: Record<string, [string, string]> = {
  anthropic: [
    "Anthropic Console -> Settings -> Admin keys.",
    "Create an admin key; it starts with sk-ant-admin.",
  ],
  openrouter: [
    "OpenRouter -> Settings -> Management keys.",
    "Create a management key, not a regular API key; it starts with sk-or-v1-.",
  ],
  openai: [
    "OpenAI platform -> Organization settings -> Admin keys.",
    "Create an admin key with read access to usage and to the organization; it starts with sk-admin-.",
  ],
  cursor: [
    "Cursor dashboard -> Settings -> Advanced -> Admin API keys.",
    "Create a team API key; it starts with key_.",
  ],
  claude_ai: [
    "claude.ai -> Organization settings -> API, as the primary owner.",
    "Create an Analytics API key with only read:analytics; it starts with sk-ant-api01-.",
  ],
  copilot: [
    "GitHub -> Settings -> Developer settings -> Personal access tokens (classic), as an organization owner or billing manager.",
    "Create a token with read:org only; it starts with ghp_.",
  ],
  codex: [
    "ChatGPT workspace -> Analytics -> Admin keys.",
    "Create an admin key (sk-admin-), then set a credit price. seat prices, when the provider charges per seat, are a separate amount in USD.",
  ],
};

/**
 * What each key must be allowed to read for spend, for the inventory, and for key posture,
 * and what it can do if it leaks. Source: docs/security/provider-keys.md.
 */
type KeyAccess = { spend: string; inventory: string; posture: string; risk: string };

const KEY_ACCESS: Record<string, KeyAccess> = {
  anthropic: {
    spend: "Admin API: cost report and usage report.",
    inventory: "Admin API: workspaces, members, users, API keys.",
    posture: "Admin API: API keys (owner, status, last use).",
    risk: "Console admin keys have no scopes: a leaked key can manage members and disable API keys.",
  },
  claude_ai: {
    spend: "read:analytics: cost and per-user cost reports.",
    inventory: "read:analytics: users.",
    posture: "Not used.",
    risk: "Read-only: a leaked key reads per-user usage, not conversations.",
  },
  openai: {
    spend: "Admin key: costs and completion usage.",
    inventory: "Admin key: projects, project users and keys, organization users.",
    posture: "Admin key: project API keys.",
    risk: "A leaked admin key can manage users, invites, projects and keys.",
  },
  codex: {
    spend: "Codex analytics API: read, for one workspace.",
    inventory: "Not used.",
    posture: "Not used.",
    risk: "Read-only for one workspace when created with only that permission.",
  },
  openrouter: {
    spend: "Management key: analytics query.",
    inventory: "Management key: keys, workspaces, members.",
    posture: "Management key: keys (limits, creator, last use).",
    risk: "Management keys are unscoped: a leaked key can create keys and spend credits. Use a dedicated one.",
  },
  cursor: {
    spend: "Admin API key: usage events, daily usage, spend.",
    inventory: "Admin API key: team members.",
    posture: "Not used.",
    risk: "Admin API keys carry admin:*; a leaked key can change spend limits and members.",
  },
  copilot: {
    spend: "read:org as an owner or billing manager: billing usage, AI credits, budgets.",
    inventory: "read:org: Copilot seats.",
    posture: "Not used.",
    risk: "A classic token reaches every organization of its owner; leave out manage_billing:copilot.",
  },
};

export function keyAccess(provider: string): KeyAccess | null {
  return KEY_ACCESS[provider] ?? null;
}

export function keyHint(info: ProviderInfo): [string, string] {
  const known = KEY_HINTS[info.provider];
  if (known) return known;
  return [
    `${info.console_label} -> Settings.`,
    info.key_prefix
      ? `Create a ${info.key_label}; it starts with ${info.key_prefix}.`
      : `Create a ${info.key_label}.`,
  ];
}

export type GettingStartedItem = {
  id: "first-import" | "second-provider" | "budget" | "anomalies";
  label: string;
  done: boolean;
  href: string;
};

/**
 * Checklist of the overview card, four items at most. The first import ticks itself as the
 * banner watches it land; the anomalies item appears only once the detector has flagged
 * something, so a fresh organization sees three items.
 */
export function gettingStartedItems(
  setup: Setup,
  facts: { budgets: number; anomalies: number },
): GettingStartedItem[] {
  const connected = setup.providers.filter((p) => p.connected).length;
  const items: GettingStartedItem[] = [
    {
      id: "first-import",
      label: "First import complete",
      done: firstImportComplete(setup),
      href: "/runs",
    },
    {
      id: "second-provider",
      label: "Connect a second provider",
      done: connected >= 2,
      href: welcomeHref(),
    },
    {
      id: "budget",
      label: "Set a monthly budget",
      done: facts.budgets > 0,
      href: "/budgets",
    },
  ];
  if (facts.anomalies > 0) {
    items.push({
      id: "anomalies",
      label: "Review the first anomalies",
      done: false,
      href: "/anomalies",
    });
  }
  return items;
}
