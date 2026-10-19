import { beforeEach, describe, expect, it, vi } from "vitest";

import { idleWebhook } from "@/lib/action-errors";
import { ApiError } from "@/lib/api";
import * as fx from "@/test/fixtures";

const revalidatePath = vi.fn();

vi.mock("next/cache", () => ({ revalidatePath: (...args: unknown[]) => revalidatePath(...args) }));
vi.mock("@/lib/session-cookie", () => ({ readSessionToken: () => Promise.resolve("tok-1") }));
vi.mock("@/lib/view-cookie", () => ({
  readViewCookie: () => Promise.resolve({ org: "acme", month: "2026-09", scope: "all" }),
}));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      saveWebhook: vi.fn(),
      testWebhook: vi.fn(),
      removeWebhook: vi.fn(),
      setWebhookDigest: vi.fn(),
    },
  };
});

const { api } = await import("@/lib/api");
const { removeWebhookAction, saveWebhookAction, setDigestAction, testWebhookAction } =
  await import("./webhook-actions");

const URL = "https://hooks.slack.com/services/T/B/x";
const formOf = (fields: Record<string, string>) => {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields)) data.set(key, value);
  return data;
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("saveWebhookAction", () => {
  it("saves the URL and hands the signing secret to the form once", async () => {
    vi.mocked(api.saveWebhook).mockResolvedValue({ ...fx.webhookSaved, signing_secret: "s3cret" });
    await expect(saveWebhookAction(idleWebhook, formOf({ url: ` ${URL} ` }))).resolves.toEqual({
      ok: true,
      message: "Saved. New signals post to hooks.slack.com; the ones open now are not sent.",
      secret: "s3cret",
    });
    expect(api.saveWebhook).toHaveBeenCalledWith("acme", URL);
    expect(revalidatePath).toHaveBeenCalledWith("/settings", "layout");
  });

  it("refuses an empty or plain-http URL before calling the API", async () => {
    for (const url of ["", "http://hooks.slack.com/x"]) {
      const state = await saveWebhookAction(idleWebhook, formOf({ url }));
      expect(state).toMatchObject({ ok: false, field: "url", secret: null });
    }
    expect(api.saveWebhook).not.toHaveBeenCalled();
  });

  it("puts the API refusal on the URL field", async () => {
    vi.mocked(api.saveWebhook).mockRejectedValue(
      new ApiError(422, "/orgs/acme/webhook", "evil.example.com is not an allowed webhook host"),
    );
    const state = await saveWebhookAction(idleWebhook, formOf({ url: URL }));
    expect(state).toMatchObject({ ok: false, field: "url", secret: null });
    expect(state.message).toContain("not an allowed webhook host");
  });
});

describe("testWebhookAction and removeWebhookAction", () => {
  it("reports whether the test message was accepted", async () => {
    vi.mocked(api.testWebhook).mockResolvedValueOnce({ delivered: true, error: null });
    await expect(testWebhookAction()).resolves.toEqual({
      ok: true,
      message: "The test message was delivered.",
    });
    vi.mocked(api.testWebhook).mockResolvedValueOnce({ delivered: false, error: "HTTP 404" });
    await expect(testWebhookAction()).resolves.toEqual({
      ok: false,
      message: "The webhook did not accept the test message (HTTP 404).",
    });
    vi.mocked(api.testWebhook).mockRejectedValueOnce(
      new ApiError(409, "/orgs/acme/webhook/test", "outbound webhooks are off"),
    );
    await expect(testWebhookAction()).resolves.toMatchObject({ ok: false });
  });

  it("removes the destination and refreshes the settings pages", async () => {
    vi.mocked(api.removeWebhook).mockResolvedValue(fx.webhookOff);
    await expect(removeWebhookAction()).resolves.toEqual({
      ok: true,
      message: "The webhook is removed; nothing is sent until one is saved again.",
    });
    expect(revalidatePath).toHaveBeenCalledWith("/settings", "layout");
  });
});

describe("setDigestAction", () => {
  it("sets the cadence and refuses an unknown one", async () => {
    vi.mocked(api.setWebhookDigest).mockResolvedValue({ ...fx.webhookSaved, digest: "weekly" });
    await expect(setDigestAction(idleWebhook, formOf({ digest: "weekly" }))).resolves.toEqual({
      ok: true,
      message: "A weekly digest will be posted on Mondays.",
    });
    expect(api.setWebhookDigest).toHaveBeenCalledWith("acme", "weekly");
    const state = await setDigestAction(idleWebhook, formOf({ digest: "daily" }));
    expect(state.ok).toBe(false);
  });
});
