import { beforeEach, describe, expect, it, vi } from "vitest";

import { idleAction } from "@/lib/action-errors";
import { ApiError } from "@/lib/api";

const revalidatePath = vi.fn();
const redirect = vi.fn((url: string) => {
  throw new Error(`NEXT_REDIRECT ${url}`);
});

vi.mock("next/cache", () => ({ revalidatePath: (...args: unknown[]) => revalidatePath(...args) }));
vi.mock("next/navigation", () => ({ redirect: (url: string) => redirect(url) }));
vi.mock("@/lib/session-cookie", () => ({ readSessionToken: () => Promise.resolve("tok-1") }));
vi.mock("@/lib/view-cookie", () => ({
  readViewCookie: () => Promise.resolve({ org: "acme", month: "2026-09", scope: "all" }),
}));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      renameOrg: vi.fn(),
      removeMember: vi.fn(),
      saveAnomalySettings: vi.fn(),
      deleteOrganization: vi.fn(),
    },
  };
});

const { api } = await import("@/lib/api");
const {
  deleteOrganizationAction,
  leaveOrganizationAction,
  renameOrganizationAction,
  saveAnomalySettingsAction,
} = await import("./organization-actions");

const formOf = (fields: Record<string, string>) => {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields)) data.set(key, value);
  return data;
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("renameOrganizationAction", () => {
  it("renames and refreshes every page", async () => {
    vi.mocked(api.renameOrg).mockResolvedValue({ name: "Acme Labs" } as never);
    await expect(
      renameOrganizationAction(idleAction, formOf({ name: " Acme Labs " })),
    ).resolves.toEqual({ ok: true, message: "Renamed to Acme Labs." });
    expect(api.renameOrg).toHaveBeenCalledWith("acme", "Acme Labs");
    expect(revalidatePath).toHaveBeenCalledWith("/", "layout");
  });

  it("asks for a name before calling the API", async () => {
    const state = await renameOrganizationAction(idleAction, formOf({ name: "  " }));
    expect(state).toMatchObject({ ok: false, field: "name" });
    expect(api.renameOrg).not.toHaveBeenCalled();
  });

  it("puts a 422 on the name field and other errors on the form", async () => {
    vi.mocked(api.renameOrg).mockRejectedValueOnce(new ApiError(422, "/orgs/acme", "too long"));
    expect(await renameOrganizationAction(idleAction, formOf({ name: "x" }))).toMatchObject({
      ok: false,
      field: "name",
    });
    vi.mocked(api.renameOrg).mockRejectedValueOnce(new ApiError(503, "/orgs/acme", "down"));
    expect(await renameOrganizationAction(idleAction, formOf({ name: "x" }))).toMatchObject({
      ok: false,
      field: undefined,
    });
  });
});

describe("leaveOrganizationAction", () => {
  it("removes the caller and lands on the landing page", async () => {
    vi.mocked(api.removeMember).mockResolvedValue(undefined as never);
    await expect(leaveOrganizationAction(idleAction, formOf({ user_id: "7" }))).rejects.toThrow(
      "NEXT_REDIRECT /",
    );
    expect(api.removeMember).toHaveBeenCalledWith("acme", 7);
  });

  it("stays on the page when the API refuses", async () => {
    vi.mocked(api.removeMember).mockRejectedValue(new ApiError(409, "/m", "last owner"));
    const state = await leaveOrganizationAction(idleAction, formOf({ user_id: "7" }));
    expect(state).toMatchObject({ ok: false });
    expect(redirect).not.toHaveBeenCalled();
  });
});

describe("saveAnomalySettingsAction", () => {
  it("sends the parsed settings", async () => {
    vi.mocked(api.saveAnomalySettings).mockResolvedValue(undefined as never);
    const state = await saveAnomalySettingsAction(
      idleAction,
      formOf({ sensitivity: "high", retention_days: "120", detect_drops: "on" }),
    );
    expect(state).toMatchObject({ ok: true, message: "Anomaly detection saved." });
    expect(api.saveAnomalySettings).toHaveBeenCalledWith("acme", {
      sensitivity: "high",
      detect_drops: true,
      detect_new_principals: false,
      retention_days: 120,
      idle_days: 30,
      new_key_days: 7,
    });
  });

  it("sends the posture thresholds and refuses them out of range", async () => {
    vi.mocked(api.saveAnomalySettings).mockResolvedValue(undefined as never);
    await saveAnomalySettingsAction(
      idleAction,
      formOf({ sensitivity: "normal", retention_days: "90", idle_days: "60", new_key_days: "14" }),
    );
    expect(api.saveAnomalySettings).toHaveBeenCalledWith(
      "acme",
      expect.objectContaining({ idle_days: 60, new_key_days: 14 }),
    );
    const state = await saveAnomalySettingsAction(
      idleAction,
      formOf({ sensitivity: "normal", retention_days: "90", idle_days: "3" }),
    );
    expect(state).toMatchObject({ ok: false, field: "idle_days" });
  });

  it("refuses a retention outside 30 to 365 days", async () => {
    const state = await saveAnomalySettingsAction(
      idleAction,
      formOf({ sensitivity: "normal", retention_days: "10" }),
    );
    expect(state).toMatchObject({ ok: false, field: "retention_days" });
    expect(api.saveAnomalySettings).not.toHaveBeenCalled();
  });
});

describe("deleteOrganizationAction", () => {
  it("needs the slug typed back", async () => {
    const state = await deleteOrganizationAction(idleAction, formOf({ slug: "other" }));
    expect(state).toEqual({
      ok: false,
      message: "Type the organization ID (acme) to confirm.",
      field: "slug",
    });
    expect(api.deleteOrganization).not.toHaveBeenCalled();
  });

  it("deletes and leaves for the landing page", async () => {
    vi.mocked(api.deleteOrganization).mockResolvedValue(undefined as never);
    await expect(deleteOrganizationAction(idleAction, formOf({ slug: "acme" }))).rejects.toThrow(
      "NEXT_REDIRECT /",
    );
    expect(api.deleteOrganization).toHaveBeenCalledWith("acme", "acme");
  });

  it("reports an API refusal on the slug field", async () => {
    vi.mocked(api.deleteOrganization).mockRejectedValue(new ApiError(409, "/o", "sync running"));
    expect(await deleteOrganizationAction(idleAction, formOf({ slug: "acme" }))).toMatchObject({
      ok: false,
      field: "slug",
    });
  });
});
