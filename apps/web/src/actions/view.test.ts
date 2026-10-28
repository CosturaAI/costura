import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  readViewCookie: vi.fn(),
  writeViewCookie: vi.fn(),
  revalidatePath: vi.fn(),
  redirect: vi.fn((to: string) => {
    throw new Error(`NEXT_REDIRECT ${to}`);
  }),
  org: vi.fn(),
}));
vi.mock("@/lib/view-cookie", () => ({
  readViewCookie: mocks.readViewCookie,
  writeViewCookie: mocks.writeViewCookie,
}));
vi.mock("next/cache", () => ({ revalidatePath: mocks.revalidatePath }));
vi.mock("next/navigation", () => ({ redirect: mocks.redirect }));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { org: mocks.org } };
});

import { ApiError } from "@/lib/api";

import { setViewAction, switchOrganizationAction } from "@/actions/view";

function form(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) data.set(key, value);
  return data;
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.readViewCookie.mockResolvedValue({ org: "acme", month: "2026-08", scope: "anthropic" });
  mocks.org.mockResolvedValue({ slug: "default", name: "Default", is_demo: false, role: "owner" });
});

describe("setViewAction", () => {
  it("merges the patch into the cookie and re-renders the layout without navigating", async () => {
    await setViewAction({ scope: "openrouter" });

    expect(mocks.writeViewCookie).toHaveBeenCalledWith({
      org: "acme",
      month: "2026-08",
      scope: "openrouter",
      from: null,
      to: null,
      interval: null,
      timeFrame: null,
    });
    expect(mocks.revalidatePath).toHaveBeenCalledWith("/", "layout");
    expect(mocks.redirect).not.toHaveBeenCalled();
  });

  it("drops an invalid month and an unknown scope", async () => {
    await setViewAction({ month: "2026-13", scope: "nope" });

    expect(mocks.writeViewCookie).toHaveBeenCalledWith({
      org: "acme",
      month: null,
      scope: "all",
      from: null,
      to: null,
      interval: null,
      timeFrame: null,
    });
  });

  it("persists a bounded range and takes the month of its last day", async () => {
    await setViewAction({
      from: "2026-07-15",
      to: "2026-09-12",
      interval: "week",
    });

    expect(mocks.writeViewCookie).toHaveBeenCalledWith({
      org: "acme",
      month: "2026-09",
      scope: "anthropic",
      from: "2026-07-15",
      to: "2026-09-12",
      interval: "week",
      timeFrame: null,
    });
  });

  it("persists complete versus rolling period semantics", async () => {
    await setViewAction({
      from: "2026-09-11",
      to: "2026-09-17",
      interval: "day",
      timeFrame: "rolling_7_days",
    });

    expect(mocks.writeViewCookie).toHaveBeenCalledWith(
      expect.objectContaining({ timeFrame: "rolling_7_days" }),
    );
  });

  it("starts over at / without a view", async () => {
    mocks.readViewCookie.mockResolvedValue(null);

    await expect(setViewAction({ scope: "all" })).rejects.toThrow("NEXT_REDIRECT /");
    expect(mocks.writeViewCookie).not.toHaveBeenCalled();
  });
});

describe("switchOrganizationAction", () => {
  it("checks the membership, resets the view to the organization and stays on the page", async () => {
    await expect(
      switchOrganizationAction(form({ slug: "default", next: "/runs" })),
    ).rejects.toThrow("NEXT_REDIRECT /runs");

    expect(mocks.org).toHaveBeenCalledWith("default");
    expect(mocks.writeViewCookie).toHaveBeenCalledWith({
      org: "default",
      month: null,
      scope: "all",
    });
    expect(mocks.revalidatePath).toHaveBeenCalledWith("/", "layout");
  });

  it("leaves an owner-only section or an id of the old organization for a root", async () => {
    await expect(
      switchOrganizationAction(form({ slug: "default", next: "/settings/audit" })),
    ).rejects.toThrow("NEXT_REDIRECT /settings");
    await expect(
      switchOrganizationAction(form({ slug: "default", next: "/anomalies/12" })),
    ).rejects.toThrow("NEXT_REDIRECT /anomalies");
  });

  it("keeps next on this origin", async () => {
    await expect(
      switchOrganizationAction(form({ slug: "default", next: "https://evil.test/x" })),
    ).rejects.toThrow("NEXT_REDIRECT /overview");
  });

  it("sends a stale entry to the 404 page without touching the cookie", async () => {
    mocks.org.mockRejectedValue(new ApiError(404, "/orgs/gone", "not found"));

    await expect(switchOrganizationAction(form({ slug: "gone" }))).rejects.toThrow(
      "NEXT_REDIRECT /o/-missing",
    );
    expect(mocks.writeViewCookie).not.toHaveBeenCalled();
  });
});
