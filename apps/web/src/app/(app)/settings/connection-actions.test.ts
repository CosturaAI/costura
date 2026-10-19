import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import * as fx from "@/test/fixtures";

const revalidatePath = vi.fn();
const redirect = vi.fn((url: string) => {
  throw new Error(`NEXT_REDIRECT ${url}`);
});

vi.mock("next/cache", () => ({ revalidatePath: (...args: unknown[]) => revalidatePath(...args) }));
vi.mock("next/navigation", () => ({ redirect: (url: string) => redirect(url) }));
// The active organization comes from the view cookie, not from a form field.
vi.mock("@/lib/session-cookie", () => ({ readSessionToken: () => Promise.resolve("tok-1") }));
vi.mock("@/lib/view-cookie", () => ({
  readViewCookie: () => Promise.resolve({ org: "default", month: "2026-08", scope: "anthropic" }),
}));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      addAccount: vi.fn(),
      addCreditPrice: vi.fn(),
      resetSetup: vi.fn(),
      connect: vi.fn(),
      deleteCreditPrice: vi.fn(),
      disconnect: vi.fn(),
      disconnectAccount: vi.fn(),
      removeAccount: vi.fn(),
      renameAccount: vi.fn(),
      replaceAccountKey: vi.fn(),
      syncNow: vi.fn(),
    },
  };
});

const { api } = await import("@/lib/api");
const {
  addCreditPriceAction,
  connectAction,
  deleteCreditPriceAction,
  disconnectAction,
  removeAccountAction,
  renameAccountAction,
  resetSetupAction,
  syncNowAction,
} = await import("./connection-actions");
const addCreditPrice = vi.mocked(api.addCreditPrice);
const resetSetup = vi.mocked(api.resetSetup);
const connect = vi.mocked(api.connect);
const deleteCreditPrice = vi.mocked(api.deleteCreditPrice);
const replaceAccountKey = vi.mocked(api.replaceAccountKey);

const form = () => new FormData();
const idle = { ok: false, message: null };

beforeEach(() => {
  vi.clearAllMocks();
});

describe("connectAction", () => {
  const connectForm = (key: string, provider = "anthropic") => {
    const data = form();
    data.set("provider", provider);
    data.set("admin_key", key);
    data.set("key_prefix", provider === "anthropic" ? "sk-ant-admin" : "sk-or-v1-");
    data.set("key_label", provider === "anthropic" ? "admin key" : "management key");
    return data;
  };
  const rejected = (detail: string, provider = "anthropic") =>
    new ApiError(422, `/orgs/default/providers/${provider}/connection`, detail);

  it("echoes the provider, the kind of key and its last four once accepted", async () => {
    connect.mockResolvedValue({ ...fx.connection, first_sync_run_id: 31 });

    await expect(connectAction(idle, connectForm("sk-ant-admin-abc"))).resolves.toEqual({
      ok: true,
      message: "Anthropic admin key ending in 4321 accepted; the first import is starting.",
    });
    expect(connect).toHaveBeenCalledWith("default", "anthropic", "sk-ant-admin-abc");
    expect(revalidatePath).toHaveBeenCalledWith("/", "layout");

    // A replaced key on a provider that already synced starts no import.
    connect.mockResolvedValue({ ...fx.openRouterConnection, first_sync_run_id: null });
    await expect(connectAction(idle, connectForm("sk-or-v1-abc", "openrouter"))).resolves.toEqual({
      ok: true,
      message: "OpenRouter management key ending in or99 accepted.",
    });
  });

  it("sends Cursor billing settings and permits key replacement without them", async () => {
    connect.mockResolvedValue({
      ...fx.connection,
      provider: "cursor",
      key_hint: "cret",
      first_sync_run_id: 32,
    });
    const cursor = connectForm("crsr_current-secret", "cursor");
    cursor.set("key_prefix", "crsr_");
    cursor.set("key_label", "team API key");
    cursor.set("seat_price_usd", "40");
    cursor.set("include_included_in_business", "on");

    await connectAction(idle, cursor);

    expect(connect).toHaveBeenCalledWith("default", "cursor", "crsr_current-secret", {
      seat_price_usd: "40",
      include_included_in_business: true,
    });

    replaceAccountKey.mockResolvedValue(fx.anthropicAccount);
    const replacement = connectForm("key_legacy-secret", "cursor");
    replacement.set("key_prefix", "crsr_");
    replacement.set("mode", "replace");
    replacement.set("account_id", "1");
    await expect(connectAction(idle, replacement)).resolves.toMatchObject({ ok: true });
    expect(replaceAccountKey).toHaveBeenCalledWith("default", "cursor", 1, "key_legacy-secret");
  });

  it("requires and sends the Codex workspace ID", async () => {
    const codex = connectForm("sk-admin-codex", "codex");
    codex.set("key_prefix", "sk-admin-");
    codex.set("key_label", "Admin API key");
    await expect(connectAction(idle, codex)).resolves.toEqual({
      ok: false,
      message: "Paste the Codex workspace ID first.",
      field: "workspace_id",
    });

    codex.set("workspace_id", "11111111-2222-4333-8444-555555555555");
    connect.mockResolvedValue({
      ...fx.connection,
      provider: "codex",
      first_sync_run_id: 33,
    });
    await expect(connectAction(idle, codex)).resolves.toMatchObject({ ok: true });
    expect(connect).toHaveBeenCalledWith("default", "codex", "sk-admin-codex", {
      workspace_id: "11111111-2222-4333-8444-555555555555",
    });
  });

  it("takes a Claude.ai Analytics key or an admin key", async () => {
    const claudeForm = (key: string) => {
      const data = connectForm(key);
      data.set("provider", "claude_ai");
      data.set("key_prefix", "sk-ant-api01-");
      data.set("key_label", "analytics API key");
      return data;
    };
    connect.mockResolvedValue(fx.connection);
    for (const key of ["sk-ant-api01-abc", "sk-ant-admin01-abc"]) {
      await expect(connectAction(idle, claudeForm(key))).resolves.toMatchObject({ ok: true });
      expect(connect).toHaveBeenLastCalledWith("default", "claude_ai", key);
    }
    connect.mockClear();
    await expect(connectAction(idle, claudeForm("sk-or-v1-abc"))).resolves.toMatchObject({
      ok: false,
      field: "admin_key",
      message: expect.stringContaining("sk-ant-api01- (or sk-ant-admin)"),
    });
    expect(connect).not.toHaveBeenCalled();
  });

  it("refuses the wrong kind of key before calling the API", async () => {
    await expect(connectAction(idle, connectForm("sk-ant-api03-abc"))).resolves.toEqual({
      ok: false,
      message:
        "Anthropic admin keys start with sk-ant-admin; this looks like a different kind of key.",
      field: "admin_key",
    });
    expect(connect).not.toHaveBeenCalled();
  });

  it("classifies the provider's refusal from the API detail", async () => {
    connect.mockRejectedValue(
      rejected(
        "Anthropic rejected the key (HTTP 401). Check that it is a admin key (sk-ant-admin...), not a regular API key, and that it was not revoked.",
      ),
    );
    await expect(connectAction(idle, connectForm("sk-ant-admin-abc"))).resolves.toEqual({
      ok: false,
      message:
        "Anthropic rejected the key as invalid or revoked. Create a new admin key in the console and paste it here.",
      field: "admin_key",
    });

    // Other 422 sentences are the API's own (a management key check, for instance).
    connect.mockRejectedValue(
      rejected("OpenRouter accepted the key but it is not a management key", "openrouter"),
    );
    await expect(
      connectAction(idle, connectForm("sk-or-v1-abc", "openrouter")),
    ).resolves.toMatchObject({
      ok: false,
      message: "OpenRouter accepted the key but it is not a management key",
      field: "admin_key",
    });
  });

  it("adds a retry hint when the API itself failed or did not answer", async () => {
    connect.mockRejectedValue(
      new ApiError(500, "/orgs/default/providers/anthropic/connection", "boom"),
    );
    await expect(connectAction(idle, connectForm("sk-ant-admin-abc"))).resolves.toEqual({
      ok: false,
      message: "boom Retry in a moment.",
      field: undefined,
    });

    connect.mockRejectedValue(new TypeError("fetch failed"));
    await expect(connectAction(idle, connectForm("sk-ant-admin-abc"))).resolves.toMatchObject({
      ok: false,
      message: "Costura did not answer. Retry in a moment.",
    });

    connect.mockRejectedValue(
      new ApiError(
        403,
        "/orgs/demo/providers/anthropic/connection",
        "demo organization is read-only",
      ),
    );
    await expect(connectAction(idle, connectForm("sk-ant-admin-abc"))).resolves.toMatchObject({
      ok: false,
      message: "The sample organization is read-only; connect a provider in your own organization.",
    });
  });

  it.each([
    [502, "OpenRouter returned an unexpected response while validating the key."],
    [503, "Anthropic could not validate the key because the provider is temporarily unavailable."],
  ])(
    "keeps the key field neutral for an upstream HTTP %s validation failure",
    async (status, detail) => {
      connect.mockRejectedValue(
        new ApiError(status, "/orgs/default/providers/anthropic/connection", detail),
      );

      await expect(connectAction(idle, connectForm("sk-ant-admin-abc"))).resolves.toEqual({
        ok: false,
        message: `${detail} Retry in a moment.`,
        field: undefined,
      });
    },
  );
});

describe("Codex credit price actions", () => {
  const priceForm = () => {
    const data = form();
    data.set("account_id", "7");
    data.set("effective_from", "2026-09-18");
    data.set("price_per_credit", "0.08");
    return data;
  };

  it("validates and adds an effective credit rate", async () => {
    const invalidDate = priceForm();
    invalidDate.set("effective_from", "2026-02-30");
    await expect(addCreditPriceAction(idle, invalidDate)).resolves.toEqual({
      ok: false,
      message: "Choose the date this credit rate starts.",
      field: "effective_from",
    });

    const invalid = priceForm();
    invalid.set("price_per_credit", "0");
    await expect(addCreditPriceAction(idle, invalid)).resolves.toEqual({
      ok: false,
      message: "Credit price must be a positive USD amount.",
      field: "price_per_credit",
    });
    expect(addCreditPrice).not.toHaveBeenCalled();

    addCreditPrice.mockResolvedValue({
      id: 4,
      organization_id: 1,
      provider_account_id: 7,
      effective_from: "2026-09-18",
      price_per_credit: "0.08000000",
      created_by: 1,
      created_at: "2026-09-18T12:00:00Z",
    });
    await expect(addCreditPriceAction(idle, priceForm())).resolves.toEqual({
      ok: true,
      message: "Credit rate added.",
    });
    expect(addCreditPrice).toHaveBeenCalledWith("default", 7, {
      effective_from: "2026-09-18",
      price_per_credit: "0.08",
    });
    expect(revalidatePath).toHaveBeenCalledWith("/settings", "layout");
    expect(revalidatePath).toHaveBeenCalledWith("/reconcile");
  });

  it("deletes a rate and rejects invalid identifiers", async () => {
    const invalid = form();
    invalid.set("account_id", "7");
    invalid.set("price_id", "nope");
    await expect(deleteCreditPriceAction(idle, invalid)).resolves.toEqual({
      ok: false,
      message: "Credit rate not found.",
    });

    deleteCreditPrice.mockResolvedValue(undefined);
    const valid = form();
    valid.set("account_id", "7");
    valid.set("price_id", "4");
    await expect(deleteCreditPriceAction(idle, valid)).resolves.toEqual({
      ok: true,
      message: "Credit rate deleted.",
    });
    expect(deleteCreditPrice).toHaveBeenCalledWith("default", 7, 4);
  });
});

describe("resetSetupAction", () => {
  it("resets the organization, revalidates it and lands on the welcome page", async () => {
    resetSetup.mockResolvedValue(fx.setupConnect);

    await expect(resetSetupAction()).rejects.toThrow("NEXT_REDIRECT /welcome");

    expect(resetSetup).toHaveBeenCalledWith("default");
    expect(revalidatePath).toHaveBeenCalledWith("/", "layout");
  });

  it("returns the refusal as the form message instead of redirecting", async () => {
    resetSetup.mockRejectedValue(
      new ApiError(
        403,
        "/orgs/default/setup/reset",
        "write routes are disabled: they require COSTURA_ENV=development or test and a request from 127.0.0.1 or ::1 until authentication exists",
      ),
    );

    await expect(resetSetupAction()).resolves.toEqual({
      ok: false,
      message:
        "This Costura instance does not accept changes from the browser: connecting a key, Sync now and reset are turned off here.",
    });
    expect(redirect).not.toHaveBeenCalled();
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("passes a server error through", async () => {
    resetSetup.mockRejectedValue(new ApiError(500, "/orgs/default/setup/reset", "boom"));

    await expect(resetSetupAction()).resolves.toEqual({ ok: false, message: "boom" });
    expect(redirect).not.toHaveBeenCalled();
  });
});

describe("account actions", () => {
  const accountForm = (fields: Record<string, string>) => {
    const data = form();
    data.set("provider", "anthropic");
    data.set("key_prefix", "sk-ant-admin");
    data.set("key_label", "admin key");
    for (const [key, value] of Object.entries(fields)) data.set(key, value);
    return data;
  };

  it("adds one more account with its label", async () => {
    vi.mocked(api.addAccount).mockResolvedValue(fx.secondAnthropicAccount);
    const state = await connectAction(
      idle,
      accountForm({ mode: "add", admin_key: "sk-ant-admin-2", label: " Research " }),
    );
    expect(state.ok).toBe(true);
    expect(api.addAccount).toHaveBeenCalledWith(
      "default",
      "anthropic",
      "sk-ant-admin-2",
      "Research",
      undefined,
    );
  });

  it("replaces the key of the chosen account and asks for one when missing", async () => {
    replaceAccountKey.mockResolvedValue(fx.anthropicAccount);
    await connectAction(
      idle,
      accountForm({ mode: "replace", admin_key: "sk-ant-admin-3", account_id: "4" }),
    );
    expect(replaceAccountKey).toHaveBeenCalledWith("default", "anthropic", 4, "sk-ant-admin-3");

    await expect(
      connectAction(idle, accountForm({ mode: "replace", admin_key: "sk-ant-admin-3" })),
    ).resolves.toEqual({ ok: false, message: "Choose the account whose key to replace." });
  });

  it("puts a refused label on the label field", async () => {
    vi.mocked(api.addAccount).mockRejectedValue(
      new ApiError(422, "/orgs/default/providers/anthropic/accounts", "label is already taken"),
    );
    await expect(
      connectAction(idle, accountForm({ mode: "add", admin_key: "sk-ant-admin-2", label: "A" })),
    ).resolves.toMatchObject({ ok: false, field: "label" });
  });

  it("disconnects the provider route or one account", async () => {
    vi.mocked(api.disconnect).mockResolvedValue(fx.notConnected);
    await expect(disconnectAction(idle, accountForm({}))).resolves.toEqual({
      ok: true,
      message: "Stored key removed.",
    });
    expect(api.disconnect).toHaveBeenCalledWith("default", "anthropic");

    vi.mocked(api.disconnectAccount).mockRejectedValue(new TypeError("fetch failed"));
    await expect(disconnectAction(idle, accountForm({ account_id: "4" }))).resolves.toMatchObject({
      ok: false,
    });
    expect(api.disconnectAccount).toHaveBeenCalledWith("default", "anthropic", 4);
  });

  it("renames an account and validates the name and the account", async () => {
    vi.mocked(api.renameAccount).mockResolvedValue({ ...fx.anthropicAccount, label: "Prod" });
    await expect(
      renameAccountAction(idle, accountForm({ account_id: "4", label: " Prod " })),
    ).resolves.toEqual({ ok: true, message: "Renamed to Prod." });
    expect(api.renameAccount).toHaveBeenCalledWith("default", "anthropic", 4, "Prod", undefined);

    await expect(renameAccountAction(idle, accountForm({ label: "Prod" }))).resolves.toEqual({
      ok: false,
      message: "Choose the account to rename.",
    });
    await expect(
      renameAccountAction(idle, accountForm({ account_id: "4", label: "" })),
    ).resolves.toMatchObject({ ok: false, field: "label" });
  });

  it("saves Cursor billing settings with a rename and refuses a negative seat price", async () => {
    vi.mocked(api.renameAccount).mockResolvedValue(fx.anthropicAccount);
    const cursorForm = (seat: string) => {
      const data = form();
      data.set("provider", "cursor");
      data.set("account_id", "6");
      data.set("label", "Cursor");
      data.set("seat_price_usd", seat);
      data.set("include_included_in_business", "on");
      return data;
    };
    await expect(renameAccountAction(idle, cursorForm("40"))).resolves.toEqual({
      ok: true,
      message: "Billing settings saved.",
    });
    expect(api.renameAccount).toHaveBeenCalledWith("default", "cursor", 6, "Cursor", {
      seat_price_usd: "40",
      include_included_in_business: true,
    });
    await expect(renameAccountAction(idle, cursorForm("-1"))).resolves.toMatchObject({
      ok: false,
      field: "seat_price_usd",
    });
  });

  it("removes an account with its data", async () => {
    vi.mocked(api.removeAccount).mockResolvedValue(undefined);
    await expect(removeAccountAction(idle, accountForm({ account_id: "4" }))).resolves.toEqual({
      ok: true,
      message: "Account removed with its synced data.",
    });
    await expect(removeAccountAction(idle, accountForm({}))).resolves.toEqual({
      ok: false,
      message: "Choose the account to remove.",
    });
  });
});

describe("syncNowAction", () => {
  const result = (provider: string, status: "queued" | "skipped", error: string | null = null) => ({
    provider,
    provider_account_id: null,
    run_id: 1,
    status,
    error,
    steps: [],
  });
  const syncForm = (provider: string) => {
    const data = form();
    data.set("provider", provider);
    return data;
  };
  const idleSync = { ok: false, message: null, results: [] };

  it("words one started provider, several and a skipped one", async () => {
    vi.mocked(api.syncNow).mockResolvedValueOnce({ results: [result("anthropic", "queued")] });
    await expect(syncNowAction(idleSync, syncForm("anthropic"))).resolves.toMatchObject({
      ok: true,
      message: "Sync started.",
    });

    vi.mocked(api.syncNow).mockResolvedValueOnce({
      results: [
        result("anthropic", "queued"),
        result("openrouter", "queued"),
        result("openai", "skipped", "no key connected"),
      ],
    });
    await expect(syncNowAction(idleSync, syncForm("all"))).resolves.toMatchObject({
      ok: true,
      message: "Sync started for Anthropic and OpenRouter. OpenAI: no key connected",
    });

    vi.mocked(api.syncNow).mockResolvedValueOnce({ results: [result("anthropic", "skipped")] });
    await expect(syncNowAction(idleSync, syncForm("anthropic"))).resolves.toMatchObject({
      ok: false,
      message: "Nothing to sync.",
    });
  });

  it("returns a refusal with no results", async () => {
    vi.mocked(api.syncNow).mockRejectedValue(new ApiError(500, "/orgs/default/sync", "boom"));
    await expect(syncNowAction(idleSync, syncForm("anthropic"))).resolves.toEqual({
      ok: false,
      message: "boom",
      results: [],
    });
  });
});
