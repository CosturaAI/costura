/** Entity pages: keys, workspaces, accounts, models and people. */

import { describe, expect, it, onTestFinished, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import * as fx from "@/test/fixtures";
import { ApiError } from "@/lib/api";
import AccountPage from "./(app)/accounts/[id]/page";
import KeyPage, { generateMetadata as keyMetadata } from "./(app)/keys/[id]/page";
import ModelPage from "./(app)/models/[id]/page";
import PersonPage from "./(app)/people/[email]/page";
import EntityNotFound from "./(app)/not-found";
import WorkspacePage from "./(app)/workspaces/[id]/page";
import { page, withPageDefaults, type MockedApi } from "@/test/page-harness";

vi.mock("next/navigation", () => import("@/test/page-harness").then((h) => h.navigationModule()));
vi.mock("@/lib/session-cookie", () =>
  import("@/test/page-harness").then((h) => h.sessionCookieModule()),
);
vi.mock("@/lib/view-cookie", () => import("@/test/page-harness").then((h) => h.viewCookieModule()));
vi.mock("@/lib/api", () => import("@/test/page-harness").then((h) => h.apiModule()));
vi.mock("./(app)/settings/connection-actions", () =>
  import("@/test/page-harness").then((h) =>
    h.stubs(
      "addCreditPriceAction",
      "connectAction",
      "deleteCreditPriceAction",
      "disconnectAction",
      "renameAccountAction",
      "removeAccountAction",
      "resetSetupAction",
      "syncNowAction",
    ),
  ),
);
vi.mock("./(app)/settings/member-actions", () =>
  import("@/test/page-harness").then((h) =>
    h.stubs("inviteAction", "revokeInvitationAction", "setMemberRoleAction", "removeMemberAction"),
  ),
);
vi.mock("./(app)/settings/organization-actions", () =>
  import("@/test/page-harness").then((h) =>
    h.stubs("leaveOrganizationAction", "renameOrganizationAction"),
  ),
);
vi.mock("./(app)/budgets/actions", () =>
  import("@/test/page-harness").then((h) => h.stubs("setBudgetAction", "deleteBudgetAction")),
);
vi.mock("./(app)/anomalies/actions", () =>
  import("@/test/page-harness").then((h) => h.anomalyActionsModule()),
);
vi.mock("./(app)/overview/actions", () =>
  import("@/test/page-harness").then((h) => h.stubs("dismissSetupAction")),
);
vi.mock("@/actions/view", () => import("@/test/page-harness").then((h) => h.viewActionsModule()));
vi.mock("@/actions/welcome", () =>
  import("@/test/page-harness").then((h) => h.stubs("getSetupAction", "startSyncAction")),
);

const { api } = await import("@/lib/api");
const mocked = api as unknown as MockedApi;
withPageDefaults(mocked);

describe("entity pages", () => {
  it("filters OpenAI activity for project and key pages", async () => {
    page.view = { ...page.view!, scope: "openai" };
    mocked.activity.mockResolvedValue(fx.activity);

    render(await WorkspacePage({ params: withId("wrkspc_redacted_a") }));
    expect(mocked.activity).toHaveBeenCalledWith("default", {
      since: "2026-08-01",
      until: "2026-08-31",
      workspace: "wrkspc_redacted_a",
    });
    fireEvent.click(screen.getByText("Details"));
    expect(screen.getByRole("heading", { name: "Activity" })).toBeInTheDocument();
    cleanup();

    render(await KeyPage({ params: withId("apikey_redacted_2") }));
    expect(mocked.activity).toHaveBeenCalledWith("default", {
      since: "2026-08-01",
      until: "2026-08-31",
      api_key: "apikey_redacted_2",
    });
  });
  const withId = (id: string) => Promise.resolve({ id });

  it("titles the tab with the entity's name, or its kind when the read fails", async () => {
    await expect(keyMetadata({ params: withId("apikey_redacted_2") })).resolves.toEqual({
      title: "batch-ingest - API key",
    });
    mocked.entityLookup.mockRejectedValueOnce(new Error("down"));
    await expect(keyMetadata({ params: withId("other") })).resolves.toEqual({ title: "API key" });
  });

  it("renders a key with its facts, KPIs, chart, models table and Explore link", async () => {
    mocked.anomalies.mockResolvedValue(fx.anomalies);
    render(await KeyPage({ params: withId("apikey_redacted_2") }));

    expect(mocked.apiKey).toHaveBeenCalledWith("default", "anthropic", "apikey_redacted_2");
    const filter = { api_key: "apikey_redacted_2" };
    expect(mocked.usage).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "api_key",
      1,
      filter,
    );
    expect(mocked.usage).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-07-01", to: "2026-07-31" },
      "api_key",
      1,
      filter,
    );
    expect(mocked.usage).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "model",
      25,
      filter,
    );
    expect(mocked.series).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "model",
      8,
      filter,
    );
    expect(mocked.anomalies).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      undefined,
      {
        kind: "api_key",
        id: "apikey_redacted_2",
      },
    );
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("batch-ingest");
    expect(screen.getByText("API key")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy id" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open in Analyze" })).toHaveAttribute(
      "href",
      `/o/default?${new URLSearchParams({ scope: "anthropic", next: "/explore?by=model&f=api_key%3Ais%3Aapikey_redacted_2" })}`,
    );
    // Facts from the inventory: the workspace links to its own page.
    fireEvent.click(screen.getByText("Details"));
    expect(screen.getByRole("link", { name: "Platform" })).toHaveAttribute(
      "href",
      "/workspaces/wrkspc_redacted_a",
    );
    expect(screen.getByText("bob@example.com")).toBeInTheDocument();
    expect(screen.getByText("Counts under")).toBeInTheDocument();
    expect(screen.getByText("Service key")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Mark as one person's key" })).toBeInTheDocument();
    expect(screen.getByText("Spend in August 2026")).toBeInTheDocument();
    expect(screen.getAllByText("40,000.00").length).toBeGreaterThan(0);
    // The share KPI divides by the organization total from `summary` (40,000 / 56,056.12), not by
    // the filtered report's own total, which would always read 100%.
    expect(mocked.summary).toHaveBeenCalledWith("default", "anthropic", {
      from: "2026-08-01",
      to: "2026-08-31",
    });
    expect(screen.getByText("Share of Anthropic spend")).toBeInTheDocument();
    expect(screen.getByText("of the period's Anthropic spend")).toBeInTheDocument();
    expect(screen.getByText("71.36%")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Legend" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: /batch-ingest by model/ })).toBeInTheDocument();
  });

  it("compares a key in a month in progress with the days the summary compares", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-08-20T12:00:00Z"));
    onTestFinished(() => {
      vi.useRealTimers();
    });
    mocked.summary.mockResolvedValue({
      ...fx.summary,
      is_current_month: true,
      comparison_basis: "month_to_date",
      previous_start: "2026-07-01",
      previous_end: "2026-07-19",
    });
    render(await KeyPage({ params: withId("apikey_redacted_2") }));

    const filter = { api_key: "apikey_redacted_2" };
    expect(mocked.usage).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-07-01", to: "2026-07-19" },
      "api_key",
      1,
      filter,
    );
    expect(mocked.usage).not.toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-07-01", to: "2026-07-31" },
      "api_key",
      1,
      filter,
    );
  });

  it("names the person a marked key counts under and offers to change or remove the mark", async () => {
    mocked.apiKey.mockResolvedValue({
      ...fx.apiKeys[0],
      person: "ana@example.com",
      person_source: "marked",
    });
    render(await KeyPage({ params: withId("apikey_redacted_2") }));
    fireEvent.click(screen.getByText("Details"));
    expect(screen.getByRole("link", { name: "ana@example.com" })).toHaveAttribute(
      "href",
      expect.stringContaining("ana%40example.com"),
    );
    expect(screen.getByText("marked in Costura")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change the person" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove mark" })).toBeInTheDocument();
  });

  it("adds a BYOK figure to a key whose traffic ran on the customer's own provider keys", async () => {
    mocked.apiKey.mockResolvedValue({ ...fx.openRouterKey, external_id: "orkey_hash_2" });
    mocked.usage.mockImplementation((_org: string, _provider: string, _month: string, by: string) =>
      Promise.resolve(by === "api_key" ? { ...fx.usage, rows: [fx.byokKeyRow] } : fx.usage),
    );
    page.view = { ...page.view!, scope: "openrouter" };
    render(await KeyPage({ params: withId("orkey_hash_2") }));
    fireEvent.click(screen.getByText("Details"));
    expect(screen.getByText("Routed on your own provider keys")).toBeInTheDocument();
    expect(screen.getByText("5,400.50")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Routed through OpenRouter on your own provider keys; billed by the providers.",
      ),
    ).toBeInTheDocument();
    cleanup();

    mocked.usage.mockResolvedValue(fx.usage);
    render(await KeyPage({ params: withId("apikey_redacted_2") }));
    expect(screen.queryByText("Routed on your own provider keys")).not.toBeInTheDocument();
  });

  it("answers 404 when the inventory does not know the key", async () => {
    mocked.apiKey.mockRejectedValue(new ApiError(404, "/x", "api key not found"));
    await expect(KeyPage({ params: withId("nope") })).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("resolves the provider of an id through the lookup route, whatever the view shows", async () => {
    // Under `all` the page still renders: the id says which provider it belongs to.
    page.view = { ...page.view!, scope: "all" };
    const params = withId("apikey_redacted_2");
    render(await KeyPage({ params }));
    expect(mocked.entityLookup).toHaveBeenCalledWith("default", "key", "apikey_redacted_2", "all");
    expect(mocked.apiKey).toHaveBeenCalledWith("default", "anthropic", "apikey_redacted_2");
    expect(mocked.usage).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "api_key",
      1,
      {
        api_key: "apikey_redacted_2",
      },
    );
    expect(screen.getByText("Anthropic")).toBeInTheDocument();
    cleanup();

    // An id of another provider than the view's opens under its own provider.
    page.view = { ...page.view!, scope: "anthropic" };
    mocked.entityLookup.mockResolvedValue({ provider: "openrouter", provider_account_id: null });
    render(await WorkspacePage({ params }));
    expect(mocked.workspace).toHaveBeenCalledWith("default", "openrouter", "apikey_redacted_2");
    expect(screen.getByText("OpenRouter")).toBeInTheDocument();
    cleanup();

    // A search result names the provider and the provider account, so a repeated external id
    // opens that console and its spend is not mixed with the other one.
    mocked.entityLookup.mockImplementation(
      (_org: string, _kind: string, _id: string, scope?: string, account?: number) =>
        Promise.resolve({
          provider: scope && scope !== "all" ? scope : "anthropic",
          provider_account_id: account ?? null,
        }),
    );
    render(
      await KeyPage({
        params: withId("shared-key"),
        searchParams: Promise.resolve({ provider: "anthropic", provider_account: "42" }),
      }),
    );
    expect(mocked.entityLookup).toHaveBeenCalledWith(
      "default",
      "key",
      "shared-key",
      "anthropic",
      42,
    );
    expect(mocked.apiKey).toHaveBeenCalledWith("default", "anthropic", "shared-key", 42);
    expect(mocked.usage).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "api_key",
      1,
      {
        api_key: "shared-key",
        provider_account: "42",
      },
    );
    cleanup();
    mocked.entityLookup.mockImplementation(
      (_org: string, _kind: string, _id: string, scope?: string) =>
        Promise.resolve({
          provider: scope && scope !== "all" ? scope : "anthropic",
          provider_account_id: null,
        }),
    );

    // An id nobody has is not found before any inventory call.
    vi.clearAllMocks();
    mocked.entityLookup.mockRejectedValue(new ApiError(404, "/x", "unknown key"));
    await expect(KeyPage({ params })).rejects.toThrow("NEXT_NOT_FOUND");
    await expect(AccountPage({ params })).rejects.toThrow("NEXT_NOT_FOUND");
    await expect(ModelPage({ params })).rejects.toThrow("NEXT_NOT_FOUND");
    expect(mocked.apiKey).not.toHaveBeenCalled();
    expect(mocked.usage).not.toHaveBeenCalled();

    page.pathname = "/keys/nope";
    render(await EntityNotFound());
    expect(screen.getByText(/Search the inventory for the name instead/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Search resources" })).toHaveAttribute(
      "href",
      "/inventory",
    );
    expect(screen.getByRole("link", { name: "Open under All providers" })).toHaveAttribute(
      "href",
      "/o/default?scope=all&next=%2Fkeys%2Fnope",
    );
    expect(screen.getByRole("link", { name: "Connect a provider" })).toHaveAttribute(
      "href",
      "/welcome",
    );
  });

  it("links the empty state to the run history of the entity's own scope", async () => {
    mocked.usage.mockResolvedValue({ ...fx.usage, by: "model", rows: [] });
    page.view = { ...page.view!, scope: "openrouter" };
    render(await ModelPage({ params: withId("gpt-5") }));
    expect(screen.getByRole("link", { name: "See what the last import covered" })).toHaveAttribute(
      "href",
      "/runs",
    );
  });

  it("shows the budget bar on a workspace and the account and model variants", async () => {
    mocked.budgetStatuses.mockResolvedValue(fx.budgetStatuses);
    mocked.usage.mockImplementation(
      (_org: string, _provider: string, _month: string, by: string, top?: number) =>
        Promise.resolve(
          by === "person" && top === 25
            ? {
                ...fx.usage,
                dimension: "person",
                rows: [{ ...fx.usageRows[0], person: "alice@example.com" }],
              }
            : fx.usage,
        ),
    );
    render(await WorkspacePage({ params: withId("wrkspc_redacted_a") }));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Platform");
    fireEvent.click(screen.getByText("Details"));
    expect(screen.getByRole("meter", { name: "Platform budget" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open in Analyze" })).toHaveAttribute(
      "href",
      `/o/default?${new URLSearchParams({ scope: "anthropic", next: "/explore?by=person&f=workspace%3Ais%3Awrkspc_redacted_a" })}`,
    );
    expect(mocked.series).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "person",
      8,
      {
        workspace: "wrkspc_redacted_a",
      },
    );
    expect(mocked.usage).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "person",
      25,
      {
        workspace: "wrkspc_redacted_a",
      },
    );
    expect(mocked.usage).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "api_key",
      25,
      {
        workspace: "wrkspc_redacted_a",
      },
    );
    expect(screen.getByRole("heading", { name: "By person" })).toBeInTheDocument();
    fireEvent.click(screen.getByText("Further breakdowns"));
    expect(screen.getByRole("heading", { name: /^By api key$/i })).toBeInTheDocument();
    cleanup();

    mocked.usage.mockResolvedValue(fx.usage);
    render(await AccountPage({ params: withId("user_alice") }));
    expect(mocked.user).toHaveBeenCalledWith("default", "anthropic", "user_alice");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("alice@example.com");
    cleanup();

    mocked.usage.mockImplementation(
      (_org: string, _provider: string, _month: string, by: string, top?: number) => {
        if (by === "person" && top === 25) {
          return Promise.resolve({
            ...fx.usage,
            dimension: "person",
            rows: [{ ...fx.usageRows[0], person: "alice@example.com" }],
          });
        }
        if (by === "model") {
          return Promise.resolve({
            ...fx.usage,
            dimension: "model",
            rows: [
              { ...fx.usageRows[0], key: "claude-sonnet-4", label: "claude-sonnet-4", details: {} },
            ],
          });
        }
        return Promise.resolve(fx.usage);
      },
    );
    render(await ModelPage({ params: withId("claude-sonnet-4") }));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("claude-sonnet-4");
    expect(screen.getByRole("link", { name: "Open in Analyze" })).toHaveAttribute(
      "href",
      `/o/default?${new URLSearchParams({ scope: "anthropic", next: "/explore?by=person&f=model%3Ais%3Aclaude-sonnet-4" })}`,
    );
    expect(mocked.usage).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "api_key",
      25,
      {
        model: "claude-sonnet-4",
      },
    );
  });

  it("leads with API keys when a workspace has service spend but no person", async () => {
    const serviceRow = {
      ...fx.usageRows[0],
      key: null,
      label: "(api key request)",
      person: null,
    };
    const keyRow = {
      ...fx.usageRows[0],
      key: "apikey_redacted_2",
      label: "batch-ingest (apikey_redacted_2)",
      person: null,
    };
    mocked.usage.mockImplementation(
      (_org: string, _provider: string, _month: string, by: string, top?: number) => {
        if (by === "person" && top === 25) {
          return Promise.resolve({ ...fx.usage, dimension: "person", rows: [serviceRow] });
        }
        if (by === "api_key" && top === 25) {
          return Promise.resolve({ ...fx.usage, dimension: "api_key", rows: [keyRow] });
        }
        return Promise.resolve(fx.usage);
      },
    );

    render(await WorkspacePage({ params: withId("wrkspc_redacted_a") }));

    expect(screen.getByRole("heading", { name: "By api key" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "By person" })).not.toBeInTheDocument();
    expect(mocked.series).toHaveBeenCalledWith(
      "default",
      "anthropic",
      { from: "2026-08-01", to: "2026-08-31" },
      "api_key",
      8,
      {
        workspace: "wrkspc_redacted_a",
      },
    );
    expect(screen.getByRole("link", { name: "Open in Analyze" })).toHaveAttribute(
      "href",
      `/o/default?${new URLSearchParams({ scope: "anthropic", next: "/explore?by=api_key&f=workspace%3Ais%3Awrkspc_redacted_a" })}`,
    );
  });

  it("opens a person under every provider when the scope's provider has no account", async () => {
    page.view = { ...page.view!, scope: "openai" };
    mocked.person.mockImplementation((_org: string, scope: string) =>
      scope === "all"
        ? Promise.resolve(fx.person)
        : Promise.reject(new ApiError(404, "/x", "unknown person")),
    );
    mocked.anomalies.mockResolvedValue({ ...fx.anomalies, anomalies: [] });
    render(await PersonPage({ params: Promise.resolve({ email: "alice%40example.com" }) }));

    expect(mocked.person).toHaveBeenCalledWith("default", "openai", "2026-08", "alice@example.com");
    expect(mocked.person).toHaveBeenCalledWith("default", "all", "2026-08", "alice@example.com");
    expect(
      screen.getByText("This person has no OpenAI account; the page shows every provider."),
    ).toBeInTheDocument();
  });

  it("renders a person across providers under all with badges, identities and breakdowns", async () => {
    page.view = { ...page.view!, scope: "all" };
    mocked.person.mockResolvedValue(fx.person);
    mocked.anomalies.mockResolvedValue({ ...fx.anomalies, anomalies: [] });
    const personRow = {
      ...fx.usageRows[0],
      key: "alice@example.com",
      label: "alice@example.com",
      provider: null,
      details: { kind: "person", providers: "anthropic,openai" },
      person: "alice@example.com",
    };
    mocked.usage.mockImplementation((_org: string, _provider: string, _month: string, by: string) =>
      Promise.resolve(
        by === "person" ? { ...fx.usage, dimension: "person", rows: [personRow] } : fx.usage,
      ),
    );
    page.view = { ...page.view!, scope: "all" };
    const params = Promise.resolve({ email: "alice%40example.com" });
    render(await PersonPage({ params }));

    expect(mocked.person).toHaveBeenCalledWith("default", "all", "2026-08", "alice@example.com");
    const filter = { person: "alice@example.com" };
    expect(mocked.usage).toHaveBeenCalledWith(
      "default",
      "all",
      { from: "2026-08-01", to: "2026-08-31" },
      "person",
      1,
      filter,
    );
    expect(mocked.series).toHaveBeenCalledWith(
      "default",
      "all",
      { from: "2026-08-01", to: "2026-08-31" },
      "provider",
      8,
      filter,
    );
    expect(mocked.usage).toHaveBeenCalledWith(
      "default",
      "all",
      { from: "2026-08-01", to: "2026-08-31" },
      "provider",
      25,
      filter,
    );
    expect(mocked.usage).toHaveBeenCalledWith(
      "default",
      "all",
      { from: "2026-08-01", to: "2026-08-31" },
      "model",
      25,
      filter,
    );
    expect(mocked.usage).toHaveBeenCalledWith(
      "default",
      "all",
      { from: "2026-08-01", to: "2026-08-31" },
      "api_key",
      25,
      filter,
    );
    expect(mocked.anomalies).toHaveBeenCalledWith(
      "default",
      "all",
      { from: "2026-08-01", to: "2026-08-31" },
      undefined,
      undefined,
      undefined,
      "alice@example.com",
    );
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("alice@example.com");
    expect(screen.getByText("Anthropic admin")).toBeInTheDocument();
    expect(screen.getByText("OpenAI owner")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Details"));
    // Each identity links to its own provider's account page.
    expect(screen.getByRole("link", { name: "user_alice" })).toHaveAttribute(
      "href",
      "/accounts/user_alice",
    );
    expect(screen.getByRole("link", { name: "user-alice" })).toHaveAttribute(
      "href",
      "/accounts/user-alice",
    );
    expect(screen.getByText(/owner, 1 key/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "By model" })).toBeInTheDocument();
    fireEvent.click(screen.getByText("Further breakdowns"));
    expect(screen.getByRole("heading", { name: /^By api key$/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open in Analyze" })).toHaveAttribute(
      "href",
      `/o/default?${new URLSearchParams({ scope: "all", next: "/explore?by=provider&f=person%3Ais%3Aalice%40example.com" })}`,
    );
    expect(screen.getByRole("link", { name: "All anomalies" })).toHaveAttribute(
      "href",
      "/anomalies?status=all&kind=account",
    );
  });

  it("answers 404 for a person nobody in scope carries", async () => {
    mocked.person.mockRejectedValue(new ApiError(404, "/x", "person not found"));
    const params = Promise.resolve({ email: "nobody%40example.com" });
    // The reads start together, so the 404 arrives beside them; the page still answers 404.
    await expect(PersonPage({ params })).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("links an account to its person across providers", async () => {
    render(await AccountPage({ params: withId("user_alice") }));
    expect(screen.getByRole("link", { name: "Across providers" })).toHaveAttribute(
      "href",
      "/people/alice%40example.com",
    );
  });

  it("shows an empty state for a model without spend in the month", async () => {
    mocked.usage.mockResolvedValue({ ...fx.usage, by: "model", rows: [] });
    render(await ModelPage({ params: withId("claude-haiku") }));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("claude-haiku");
    expect(
      screen.getByText(/No spend attributed to this model in August 2026/),
    ).toBeInTheDocument();
  });

  it("words empty states for the read-only sample without an action", async () => {
    page.organizations = [{ ...fx.organization, is_demo: true, role: null }];
    mocked.usage.mockResolvedValue({ ...fx.usage, by: "model", rows: [] });
    render(await ModelPage({ params: withId("claude-haiku") }));
    const empty = screen.getByText(/No spend attributed to this model in August 2026/);
    expect(empty).toHaveTextContent("The sample keeps what stopped spending");
    expect(screen.queryByRole("link", { name: /runs/i })).not.toBeInTheDocument();
    cleanup();

    mocked.usage.mockResolvedValue(fx.usage);
    render(await WorkspacePage({ params: withId("wrkspc_redacted_a") }));
    fireEvent.click(screen.getByText("Details"));
    expect(screen.getByText(/No budget for this workspace/)).toHaveTextContent(
      "The sample's budgets are fixed",
    );
    expect(screen.queryByRole("link", { name: "Set one" })).not.toBeInTheDocument();
  });

  it("treats a row with zero tokens as activity and renders amount and tokens independently", async () => {
    mocked.usage.mockResolvedValue({
      ...fx.usage,
      by: "model",
      rows: [
        {
          ...fx.usageRows[0],
          key: "zero-token-model",
          label: "zero-token-model",
          amount: "12.34",
          byok_amount: null,
          total_tokens: 0,
          tokens: {},
        },
      ],
    });
    render(await ModelPage({ params: withId("zero-token-model") }));

    expect(screen.queryByText(/No spend attributed/)).not.toBeInTheDocument();
    expect(screen.getByText("Spend in August 2026")).toBeInTheDocument();
    expect(screen.getAllByText("12.34").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByText("Details"));
    expect(screen.getByText("Tokens").nextSibling).toHaveTextContent("0");
  });

  it("keeps token and BYOK availability when the attributed amount is unavailable", async () => {
    mocked.usage.mockResolvedValue({
      ...fx.usage,
      by: "model",
      rows: [
        {
          ...fx.usageRows[0],
          key: "byok-only-model",
          label: "byok-only-model",
          amount: null,
          byok_amount: "5.25",
          total_tokens: 0,
          tokens: {},
        },
      ],
    });
    render(await ModelPage({ params: withId("byok-only-model") }));

    expect(screen.queryByText(/No spend attributed/)).not.toBeInTheDocument();
    expect(screen.getByText(/amount unavailable/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Details"));
    expect(screen.getByText("Routed on your own provider keys")).toBeInTheDocument();
    expect(screen.getAllByText("5.25").length).toBeGreaterThan(0);
  });
});
