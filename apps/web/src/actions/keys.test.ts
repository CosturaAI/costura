import { beforeEach, describe, expect, it, vi } from "vitest";

import { idleAction } from "@/lib/action-errors";

const revalidatePath = vi.fn();

vi.mock("next/cache", () => ({ revalidatePath: (...args: unknown[]) => revalidatePath(...args) }));
vi.mock("@/lib/session-cookie", () => ({ readSessionToken: () => Promise.resolve("tok-1") }));
vi.mock("@/lib/view-cookie", () => ({
  readViewCookie: () => Promise.resolve({ org: "acme", month: "2026-09", scope: "anthropic" }),
}));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { snoozeGap: vi.fn(), liftSnooze: vi.fn() } };
});

const { api } = await import("@/lib/api");
const { liftSnoozeAction, snoozeGapAction } = await import("./keys");

const formOf = (fields: Record<string, string>) => {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields)) data.set(key, value);
  return data;
};

beforeEach(() => vi.clearAllMocks());

describe("snoozeGapAction", () => {
  it("snoozes one gap of one key with the chosen days and note", async () => {
    vi.mocked(api.snoozeGap).mockResolvedValue({
      kind: "no_owner",
      provider: "anthropic",
      key_id: "k1",
      until: "2026-11-14",
      note: "shared",
    });
    await expect(
      snoozeGapAction(
        idleAction,
        formOf({
          provider: "anthropic",
          api_key_id: "k1",
          kind: "no_owner",
          days: "30",
          note: " shared ",
        }),
      ),
    ).resolves.toEqual({ ok: true, message: "Snoozed until 2026-11-14." });
    expect(api.snoozeGap).toHaveBeenCalledWith("acme", "anthropic", {
      kind: "no_owner",
      key_id: "k1",
      days: 30,
      note: "shared",
    });
  });

  it("refuses an anomaly or an odd duration before calling the API", async () => {
    for (const fields of [
      { api_key_id: "k1", kind: "anomaly", days: "30" },
      { api_key_id: "k1", kind: "no_owner", days: "10" },
    ]) {
      const state = await snoozeGapAction(idleAction, formOf(fields));
      expect(state.ok).toBe(false);
    }
    expect(api.snoozeGap).not.toHaveBeenCalled();
  });
});

describe("liftSnoozeAction", () => {
  it("brings the gap back", async () => {
    vi.mocked(api.liftSnooze).mockResolvedValue(undefined);
    await expect(
      liftSnoozeAction(idleAction, formOf({ api_key_id: "k1", kind: "no_limit" })),
    ).resolves.toEqual({ ok: true, message: "The gap is back in the queue." });
    expect(api.liftSnooze).toHaveBeenCalledWith("acme", "anthropic", "no_limit", "k1");
  });
});
