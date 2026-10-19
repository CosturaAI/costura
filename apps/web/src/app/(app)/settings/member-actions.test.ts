import { beforeEach, describe, expect, it, vi } from "vitest";

import { idleAction, idleInvite } from "@/lib/action-errors";
import { ApiError } from "@/lib/api";
import * as fx from "@/test/fixtures";

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
      invite: vi.fn(),
      revokeInvitation: vi.fn(),
      setMemberRole: vi.fn(),
      removeMember: vi.fn(),
      renameOrg: vi.fn(),
    },
  };
});

const { api } = await import("@/lib/api");
const { inviteAction, removeMemberAction, revokeInvitationAction, setMemberRoleAction } =
  await import("./member-actions");
const { leaveOrganizationAction, renameOrganizationAction } =
  await import("./organization-actions");

const formOf = (fields: Record<string, string>) => {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields)) data.set(key, value);
  return data;
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("inviteAction", () => {
  it("invites the trimmed address and returns the one-time join link", async () => {
    vi.mocked(api.invite).mockResolvedValue(
      {
        ...fx.invitations[0]!,
        role: "viewer",
        url: "https://costura.test/join/abc",
      }!,
    );

    await expect(
      inviteAction(idleInvite, formOf({ email: "  newcomer@example.com ", role: "viewer" })),
    ).resolves.toEqual({
      ok: true,
      message: "newcomer@example.com is invited as viewer.",
      url: "https://costura.test/join/abc",
      email: "newcomer@example.com",
    });
    expect(api.invite).toHaveBeenCalledWith("acme", "newcomer@example.com", "viewer");
    expect(revalidatePath).toHaveBeenCalledWith("/settings", "layout");
  });

  it("asks for the address and a known role before calling the API", async () => {
    await expect(inviteAction(idleInvite, formOf({ email: " " }))).resolves.toMatchObject({
      ok: false,
      field: "email",
    });
    await expect(
      inviteAction(idleInvite, formOf({ email: "a@b.co", role: "admin" })),
    ).resolves.toMatchObject({ ok: false, message: "Pick a role." });
    expect(api.invite).not.toHaveBeenCalled();
  });

  it("points a conflict at the e-mail field and keeps other refusals unfielded", async () => {
    vi.mocked(api.invite).mockRejectedValueOnce(
      new ApiError(409, "/orgs/acme/invitations", "this address is already a member"),
    );
    await expect(
      inviteAction(idleInvite, formOf({ email: "dev@example.com" })),
    ).resolves.toMatchObject({ ok: false, field: "email", url: null, email: null });

    vi.mocked(api.invite).mockRejectedValueOnce(new TypeError("fetch failed"));
    const state = await inviteAction(idleInvite, formOf({ email: "dev@example.com" }));
    expect(state).toMatchObject({ ok: false, field: undefined });
    expect(revalidatePath).not.toHaveBeenCalled();
  });
});

describe("member changes", () => {
  it("revokes an invitation by id", async () => {
    vi.mocked(api.revokeInvitation).mockResolvedValue(undefined);
    await expect(
      revokeInvitationAction(idleAction, formOf({ invitation_id: "7" })),
    ).resolves.toEqual({ ok: true, message: "Invitation revoked; its link no longer works." });
    expect(api.revokeInvitation).toHaveBeenCalledWith("acme", 7);
  });

  it("changes a role and names the member and the new role", async () => {
    vi.mocked(api.setMemberRole).mockResolvedValue({ ...fx.members[1]!, role: "viewer" });
    await expect(
      setMemberRoleAction(idleAction, formOf({ user_id: "2", role: "viewer" })),
    ).resolves.toEqual({ ok: true, message: "dev@example.com is now viewer." });
    expect(api.setMemberRole).toHaveBeenCalledWith("acme", 2, "viewer");

    await expect(
      setMemberRoleAction(idleAction, formOf({ user_id: "2", role: "root" })),
    ).resolves.toEqual({ ok: false, message: "Pick a role." });
  });

  it("removes a member and reports a refusal as a message", async () => {
    vi.mocked(api.removeMember).mockResolvedValueOnce(undefined);
    await expect(
      removeMemberAction(idleAction, formOf({ user_id: "2", email: "dev@example.com" })),
    ).resolves.toEqual({
      ok: true,
      message: "dev@example.com can no longer open this organization.",
    });

    vi.mocked(api.removeMember).mockRejectedValueOnce(
      new ApiError(409, "/orgs/acme/members/1", "the organization needs an owner"),
    );
    await expect(
      removeMemberAction(idleAction, formOf({ user_id: "1", email: "owner@example.com" })),
    ).resolves.toMatchObject({ ok: false });
  });
});

describe("organization actions", () => {
  it("renames with a trimmed name and refuses a blank one", async () => {
    vi.mocked(api.renameOrg).mockResolvedValue({ ...fx.organization, name: "Acme Inc" });
    await expect(
      renameOrganizationAction(idleAction, formOf({ name: " Acme Inc " })),
    ).resolves.toEqual({ ok: true, message: "Renamed to Acme Inc." });
    expect(api.renameOrg).toHaveBeenCalledWith("acme", "Acme Inc");

    await expect(renameOrganizationAction(idleAction, formOf({ name: "" }))).resolves.toEqual({
      ok: false,
      message: "Give the organization a name.",
      field: "name",
    });
  });

  it("points a validation refusal at the name field", async () => {
    vi.mocked(api.renameOrg).mockRejectedValue(new ApiError(422, "/orgs/acme", "name too long"));
    await expect(
      renameOrganizationAction(idleAction, formOf({ name: "x".repeat(300) })),
    ).resolves.toMatchObject({ ok: false, field: "name" });
  });

  it("leaves through the member route and lands on the landing page", async () => {
    vi.mocked(api.removeMember).mockResolvedValue(undefined);
    await expect(leaveOrganizationAction(idleAction, formOf({ user_id: "1" }))).rejects.toThrow(
      "NEXT_REDIRECT /",
    );
    expect(api.removeMember).toHaveBeenCalledWith("acme", 1);
    expect(revalidatePath).toHaveBeenCalledWith("/", "layout");
  });

  it("stays on the page when leaving is refused", async () => {
    vi.mocked(api.removeMember).mockRejectedValue(
      new ApiError(409, "/orgs/acme/members/1", "the organization needs an owner"),
    );
    await expect(
      leaveOrganizationAction(idleAction, formOf({ user_id: "1" })),
    ).resolves.toMatchObject({ ok: false });
    expect(redirect).not.toHaveBeenCalled();
  });
});
