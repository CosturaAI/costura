import { beforeEach, describe, expect, it, vi } from "vitest";

import { idleAction } from "@/lib/action-errors";
import { ApiError } from "@/lib/api";

const revalidatePath = vi.fn();

vi.mock("next/cache", () => ({ revalidatePath: (...args: unknown[]) => revalidatePath(...args) }));
vi.mock("@/lib/session-cookie", () => ({ readSessionToken: () => Promise.resolve("tok-1") }));
vi.mock("@/lib/view-cookie", () => ({
  readViewCookie: () => Promise.resolve({ org: "acme", month: "2026-09", scope: "all" }),
}));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { resendWebhookDelivery: vi.fn() } };
});

const { api } = await import("@/lib/api");
const { resendDeliveryAction } = await import("./resend-action");

const formOf = (fields: Record<string, string>) => {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields)) data.set(key, value);
  return data;
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("resendDeliveryAction", () => {
  it("posts the row again and refreshes the settings pages", async () => {
    vi.mocked(api.resendWebhookDelivery).mockResolvedValue({ delivered: true, error: null });
    await expect(resendDeliveryAction(idleAction, formOf({ delivery_id: "12" }))).resolves.toEqual({
      ok: true,
      message: "Posted again.",
    });
    expect(api.resendWebhookDelivery).toHaveBeenCalledWith("acme", 12);
    expect(revalidatePath).toHaveBeenCalledWith("/settings", "layout");
  });

  it("reports a destination that refused, and an API error", async () => {
    vi.mocked(api.resendWebhookDelivery).mockResolvedValueOnce({
      delivered: false,
      error: "HTTP 404",
    });
    await expect(resendDeliveryAction(idleAction, formOf({ delivery_id: "12" }))).resolves.toEqual({
      ok: false,
      message: "The webhook did not accept it (HTTP 404).",
    });
    vi.mocked(api.resendWebhookDelivery).mockRejectedValueOnce(
      new ApiError(422, "/orgs/acme/webhook/deliveries/12/resend", "the signal closed"),
    );
    const state = await resendDeliveryAction(idleAction, formOf({ delivery_id: "12" }));
    expect(state.ok).toBe(false);
    expect(state.message).toContain("the signal closed");
  });

  it("refuses a missing id before calling the API", async () => {
    const state = await resendDeliveryAction(idleAction, formOf({ delivery_id: "x" }));
    expect(state).toEqual({ ok: false, message: "Pick a delivery to resend." });
    expect(api.resendWebhookDelivery).not.toHaveBeenCalled();
  });
});
