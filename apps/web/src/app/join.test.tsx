import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, type Me, type Organization, type PendingInvitation } from "@/lib/api";
import * as fx from "@/test/fixtures";

import { acceptInvitationAction, claimInvitationAction } from "./join/actions";
import ClaimInvitationPage from "./join/[token]/page";
import JoinPage from "./join/page";
import NewOrgPage from "./new/page";
import Home from "./page";

const redirect = vi.fn((url: string) => {
  throw new Error(`NEXT_REDIRECT ${url}`);
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/join",
  useSelectedLayoutSegment: () => null,
  redirect: (url: string) => redirect(url),
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));

vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));

let token: string | null = "tok-1";
const writeViewCookie = vi.fn();
vi.mock("@/lib/session-cookie", () => ({ readSessionToken: () => Promise.resolve(token) }));
vi.mock("@/lib/view-cookie", () => ({
  readViewCookie: () => Promise.resolve(null),
  writeViewCookie: (...args: unknown[]) => writeViewCookie(...args),
  clearViewCookie: vi.fn(),
}));

vi.mock("@/actions/sign-out", () => ({ signOutAction: vi.fn() }));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      me: vi.fn(),
      setup: vi.fn(),
      acceptInvitation: vi.fn(),
      claimInvitation: vi.fn(),
    },
  };
});

const { api } = await import("@/lib/api");
const mocked = api as unknown as Record<keyof typeof api, ReturnType<typeof vi.fn>>;

const acme: Organization = { slug: "acme", name: "Acme", is_demo: false, role: "member" };
const invitation: PendingInvitation = { ...fx.pendingInvitation, organization: acme };
const noOrgs: Me = {
  user: { email: "newcomer@example.com", name: null },
  organizations: [],
  demo_org: null,
  invitations: [invitation],
};
const NOW = new Date("2026-09-14T12:00:00Z");

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(NOW);
  token = "tok-1";
  mocked.me.mockResolvedValue(noOrgs);
  mocked.setup.mockResolvedValue(fx.setupReady);
  mocked.acceptInvitation.mockResolvedValue(acme);
  mocked.claimInvitation.mockResolvedValue(acme);
});

afterEach(() => {
  vi.useRealTimers();
  cleanup();
});

describe("landing with an invitation", () => {
  it("sends someone invited but not yet a member to /join", async () => {
    await expect(Home()).rejects.toThrow("NEXT_REDIRECT /join");
  });

  it("prefers an organization they already belong to", async () => {
    mocked.me.mockResolvedValue({ ...noOrgs, organizations: [acme] });
    await expect(Home()).rejects.toThrow("NEXT_REDIRECT /o/acme?next=%2Foverview");
  });

  it("still offers creating one when no invitation waits", async () => {
    mocked.me.mockResolvedValue({ ...noOrgs, invitations: [] });
    await expect(Home()).rejects.toThrow("NEXT_REDIRECT /new");
  });
});

describe("/join", () => {
  it("lists what waits for the signed-in address, with Accept", async () => {
    render(await JoinPage());

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("You have been invited");
    expect(screen.getByText(/Signed in as newcomer@example.com/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("Acme");
    expect(screen.getByText(/owner@example.com invited you as member\./)).toBeInTheDocument();
    // Expiry as a distance, which is the decision the reader makes with it.
    expect(screen.getByText("in 14 days")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Join Acme" })).toBeInTheDocument();
  });

  it("explains an empty list instead of showing a blank page", async () => {
    mocked.me.mockResolvedValue({ ...noOrgs, invitations: [] });
    render(await JoinPage());

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("No invitation waiting");
    expect(
      screen.getByText(/Ask an owner to invite newcomer@example.com again/),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create your own organization" })).toHaveAttribute(
      "href",
      "/new",
    );
  });

  it("asks for sign-in first and comes back to /join", async () => {
    token = null;
    await expect(JoinPage()).rejects.toThrow("NEXT_REDIRECT /sign-in?next=/join");
  });
});

describe("/join/[token]", () => {
  const params = Promise.resolve({ token: "abc123" });

  it("asks for sign-in first and comes back to the link", async () => {
    token = null;
    await expect(ClaimInvitationPage({ params })).rejects.toThrow(
      "NEXT_REDIRECT /sign-in?next=/join/abc123",
    );
  });

  it("names the organization and claims with the token", async () => {
    render(await ClaimInvitationPage({ params }));

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Join Acme");
    expect(screen.getByRole("button", { name: "Accept invitation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("says nothing waits for this address when the link was sent to another", async () => {
    mocked.me.mockResolvedValue({ ...noOrgs, invitations: [] });
    render(await ClaimInvitationPage({ params }));

    expect(screen.getByText(/Nothing is waiting for newcomer@example.com/)).toBeInTheDocument();
    // The claim stays available: the API is the authority on the token.
    expect(screen.getByRole("button", { name: "Accept invitation" })).toBeInTheDocument();
  });
});

describe("/new with an invitation", () => {
  it("offers joining above the create form", async () => {
    render(await NewOrgPage());

    expect(screen.getByText(/Acme has invited you\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Join instead of creating one" })).toHaveAttribute(
      "href",
      "/join",
    );
  });

  it("says nothing about invitations when there are none", async () => {
    mocked.me.mockResolvedValue({ ...noOrgs, invitations: [] });
    render(await NewOrgPage());

    expect(screen.queryByRole("link", { name: /Join instead/ })).not.toBeInTheDocument();
  });
});

describe("accepting", () => {
  const idle = { ok: false, message: null };

  it("lands in the organization after accepting from the list", async () => {
    const form = new FormData();
    form.set("invitation_id", "7");
    // The new organization becomes the active one before the browser lands on it.
    await expect(acceptInvitationAction(idle, form)).rejects.toThrow("NEXT_REDIRECT /overview");
    expect(mocked.acceptInvitation).toHaveBeenCalledWith(7);
    expect(writeViewCookie).toHaveBeenCalledWith({ org: "acme", scope: "all" });
  });

  it("lands in the organization after claiming a link", async () => {
    const form = new FormData();
    form.set("token", "abc123");
    await expect(claimInvitationAction(idle, form)).rejects.toThrow("NEXT_REDIRECT /overview");
    expect(mocked.claimInvitation).toHaveBeenCalledWith("abc123");
    expect(writeViewCookie).toHaveBeenCalledWith({ org: "acme", scope: "all" });
  });

  it("reports a mismatched invitation without naming the invited address", async () => {
    mocked.claimInvitation.mockRejectedValue(
      new ApiError(
        410,
        "/invitations/claim",
        "this invitation is no longer valid; ask an owner for a new one",
      ),
    );
    const form = new FormData();
    form.set("token", "abc123");
    const state = await claimInvitationAction(idle, form);

    expect(state.ok).toBe(false);
    expect(state.message).toContain("no longer valid");
    expect(state.message).not.toContain("@");
  });

  it("reports an expired or revoked invitation", async () => {
    mocked.acceptInvitation.mockRejectedValue(
      new ApiError(410, "/invitations/7/accept", "this invitation is no longer valid"),
    );
    const form = new FormData();
    form.set("invitation_id", "7");
    const state = await acceptInvitationAction(idle, form);

    expect(state.ok).toBe(false);
    expect(state.message).toContain("no longer valid");
  });
});
