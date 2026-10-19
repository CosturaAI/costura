import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MobileNav, Sidebar } from "@/components/sidebar-nav";
import { ApiError, type Me, type Organization } from "@/lib/api";
import {
  clearGoogleOAuthCookie,
  parseGoogleOAuthCookie,
  setGoogleOAuthCookie,
} from "@/lib/oauth-transaction-cookie";
import * as fx from "@/test/fixtures";

import { createOrgAction } from "./new/actions";
import NewOrgPage from "./new/page";
import Home from "./page";
import { signInAction } from "./sign-in/actions";
import SignInPage from "./sign-in/page";
import { signOutAction, signOutEverywhereAction } from "@/actions/sign-out";

const redirect = vi.fn((url: string) => {
  throw new Error(`NEXT_REDIRECT ${url}`);
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/overview",
  useSelectedLayoutSegment: () => "overview",
  redirect: (url: string) => redirect(url),
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));

/** The request cookie jar the pages read and the actions write. */
const jar = new Map<string, string>();
const cookieStore = {
  get: (name: string) => (jar.has(name) ? { name, value: jar.get(name)! } : undefined),
  has: (name: string) => jar.has(name),
  set: vi.fn((cookie: { name: string; value: string }) => {
    jar.set(cookie.name, cookie.value);
  }),
  delete: vi.fn((name: string) => {
    jar.delete(name);
  }),
};
let host = "localhost:3000";

vi.mock("next/headers", () => ({
  cookies: () => Promise.resolve(cookieStore),
  headers: () => Promise.resolve(new Headers({ host })),
}));

vi.mock("./new/actions", async () => {
  const actual = await vi.importActual<typeof import("./new/actions")>("./new/actions");
  return { ...actual, createOrgAction: vi.fn() };
});

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      me: vi.fn(),
      org: vi.fn(),
      session: vi.fn(),
      googleAuth: vi.fn(),
      devSignIn: vi.fn(),
      signOut: vi.fn(),
      signOutEverywhere: vi.fn(),
      createOrg: vi.fn(),
      setup: vi.fn(),
    },
  };
});

const { api } = await import("@/lib/api");
const mocked = api as unknown as Record<keyof typeof api, ReturnType<typeof vi.fn>>;

const owner: Organization = { slug: "acme", name: "Acme", is_demo: false, role: "owner" };
const demo: Organization = { slug: "demo", name: "Sample organization", is_demo: true, role: null };
const me: Me = {
  user: { email: "jane@acme.com", name: "Jane" },
  organizations: [demo, owner],
  demo_org: "demo",
  invitations: [],
};
const noOrgs: Me = { ...me, organizations: [demo] };

beforeEach(() => {
  vi.clearAllMocks();
  jar.clear();
  host = "localhost:3000";
  mocked.me.mockResolvedValue(me);
  mocked.org.mockResolvedValue(demo);
  mocked.session.mockResolvedValue(me);
  mocked.googleAuth.mockResolvedValue({
    enabled: false,
    dev_sign_in_enabled: true,
    operator_sign_in_enabled: false,
  });
  mocked.setup.mockResolvedValue(fx.setupReady);
});

const signedIn = () => jar.set("costura_session", "tok-1");

describe("/", () => {
  it("sends the browser to sign in without a session cookie", async () => {
    await expect(Home()).rejects.toThrow("NEXT_REDIRECT /sign-in");
    expect(mocked.me).not.toHaveBeenCalled();
  });

  it("sends a user without an organization to /new, ignoring the sample one", async () => {
    signedIn();
    mocked.me.mockResolvedValue(noOrgs);
    await expect(Home()).rejects.toThrow("NEXT_REDIRECT /new");
    expect(mocked.setup).not.toHaveBeenCalled();
  });

  it("opens the first owned organization through /o, which writes the view cookie", async () => {
    signedIn();
    await expect(Home()).rejects.toThrow("NEXT_REDIRECT /o/acme?next=%2Foverview");
    expect(mocked.setup).toHaveBeenCalledWith("acme");
  });

  it("stays on the remembered organization while the user is still a member of it", async () => {
    signedIn();
    jar.set("costura_view", JSON.stringify({ org: "acme", month: "2026-08", scope: "all" }));
    await expect(Home()).rejects.toThrow("NEXT_REDIRECT /overview");
    expect(mocked.setup).toHaveBeenCalledWith("acme");

    // A cookie naming an organization the user left is ignored, not trusted.
    jar.set("costura_view", JSON.stringify({ org: "gone", month: null, scope: null }));
    await expect(Home()).rejects.toThrow("NEXT_REDIRECT /o/acme?next=%2Foverview");
    // The public sample is never "remembered" as home: it is not the user's organization.
    jar.set("costura_view", JSON.stringify({ org: "demo", month: null, scope: null }));
    await expect(Home()).rejects.toThrow("NEXT_REDIRECT /overview");
  });

  it("prefers owned organizations, then members, alphabetically", async () => {
    signedIn();
    mocked.me.mockResolvedValue({
      ...me,
      organizations: [
        { slug: "zeta", name: "Zeta", is_demo: false, role: "member" },
        { slug: "beta", name: "Beta", is_demo: false, role: "owner" },
        { slug: "alpha", name: "Alpha", is_demo: false, role: "member" },
        demo,
      ],
    });
    mocked.setup.mockResolvedValue(fx.setupConnect);
    await expect(Home()).rejects.toThrow("NEXT_REDIRECT /o/beta?next=%2Fwelcome");

    mocked.me.mockResolvedValue({
      ...me,
      organizations: [
        { slug: "zeta", name: "Zeta", is_demo: false, role: "member" },
        { slug: "alpha", name: "Alpha", is_demo: false, role: "member" },
      ],
    });
    await expect(Home()).rejects.toThrow("NEXT_REDIRECT /o/alpha?next=%2Fwelcome");
  });

  it("opens the overview while the first sync runs; the banner follows it there", async () => {
    signedIn();
    mocked.setup.mockResolvedValue(fx.setupSyncing);
    await expect(Home()).rejects.toThrow("NEXT_REDIRECT /o/acme?next=%2Foverview");
  });
});

describe("/sign-in", () => {
  it("renders the development sign-in card", async () => {
    render(await SignInPage());

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Sign in to Costura");
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("Development sign-in");
    expect(screen.getByText(/local loopback stack/)).toBeInTheDocument();
    expect(screen.getByLabelText("E-mail")).toHaveAttribute("type", "email");
    expect(screen.getByLabelText(/^Name/)).toHaveAttribute("name", "name");
    expect(screen.getByRole("button", { name: "Continue" })).toBeInTheDocument();
    expect(mocked.session).not.toHaveBeenCalled();
  });

  it("shows Google and hides the development form in production mode", async () => {
    mocked.googleAuth.mockResolvedValue({
      enabled: true,
      dev_sign_in_enabled: false,
      operator_sign_in_enabled: false,
    });
    render(await SignInPage({ searchParams: Promise.resolve({ next: "/join/abc" }) }));

    expect(screen.getByRole("link", { name: "Continue with Google" })).toHaveAttribute(
      "href",
      "/api/auth/google/start?next=%2Fjoin%2Fabc",
    );
    expect(screen.queryByRole("heading", { name: "Development sign-in" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Deployment administrator" }),
    ).not.toBeInTheDocument();
  });

  it("renders the operator form when production has an operator secret and no development sign-in", async () => {
    mocked.googleAuth.mockResolvedValue({
      enabled: false,
      dev_sign_in_enabled: false,
      operator_sign_in_enabled: true,
    });
    render(await SignInPage());

    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("Deployment administrator");
    expect(screen.getByText(/administrator e-mail and secret/)).toBeInTheDocument();
    expect(screen.getByLabelText("Secret")).toHaveAttribute("type", "password");
    expect(screen.queryByLabelText(/^Name/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Google sign-in is not configured/)).not.toBeInTheDocument();
  });

  it("redirects to / when the cookie names a live session", async () => {
    signedIn();
    await expect(SignInPage()).rejects.toThrow("NEXT_REDIRECT /");
    expect(mocked.session).toHaveBeenCalled();
  });

  it("shows the form when the cookie is stale", async () => {
    signedIn();
    mocked.session.mockRejectedValue(new ApiError(401, "/me", "session expired"));
    render(await SignInPage());
    expect(screen.getByRole("button", { name: "Continue" })).toBeInTheDocument();
    expect(redirect).not.toHaveBeenCalled();
  });

  it("passes other API failures to the boundary", async () => {
    signedIn();
    mocked.session.mockRejectedValue(new Error("fetch failed"));
    await expect(SignInPage()).rejects.toThrow("fetch failed");
  });

  it("links to the public sample organization when it is seeded", async () => {
    render(await SignInPage());
    expect(mocked.org).toHaveBeenCalledWith("demo");
    expect(screen.getByRole("link", { name: "Explore the sample organization" })).toHaveAttribute(
      "href",
      "/o/demo",
    );
  });

  it("hides the sample link when the API has no sample organization", async () => {
    mocked.org.mockRejectedValue(new ApiError(404, "/orgs/demo", "unknown organization 'demo'"));
    render(await SignInPage());
    expect(screen.queryByRole("link", { name: /sample organization/ })).not.toBeInTheDocument();
  });
});

describe("Google transaction cookie", () => {
  it("is HttpOnly, Lax, Secure in production, parseable, and cleared by both names", async () => {
    host = "costura.example.com";
    const transaction = {
      state: "s".repeat(43),
      nonce: "n".repeat(43),
      codeVerifier: "v".repeat(86),
      next: "/join/token",
    };
    await setGoogleOAuthCookie(transaction, "2026-09-17T15:00:00Z");
    expect(cookieStore.set).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "__Host-costura_google_oauth",
        httpOnly: true,
        sameSite: "lax",
        secure: true,
        path: "/",
      }),
    );
    expect(parseGoogleOAuthCookie(jar.get("__Host-costura_google_oauth"))).toEqual(transaction);
    await clearGoogleOAuthCookie();
    expect(cookieStore.delete).toHaveBeenCalledWith("costura_google_oauth");
    expect(cookieStore.delete).toHaveBeenCalledWith("__Host-costura_google_oauth");
  });
});

describe("signInAction", () => {
  const form = (email: string, name = "") => {
    const data = new FormData();
    data.set("email", email);
    data.set("name", name);
    return data;
  };
  const idle = { ok: false, message: null };

  it("signs in, sets the cookie and lands on /", async () => {
    mocked.devSignIn.mockResolvedValue({
      token: "tok-2",
      expires_at: "2026-10-15T00:00:00Z",
      user: { email: "jane@acme.com", name: "Jane" },
    });

    await expect(signInAction(idle, form(" Jane@Acme.com ", "Jane"))).rejects.toThrow(
      "NEXT_REDIRECT /",
    );

    expect(mocked.devSignIn).toHaveBeenCalledWith("jane@acme.com", "Jane");
    expect(cookieStore.set).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "costura_session",
        value: "tok-2",
        httpOnly: true,
        sameSite: "lax",
        path: "/",
        secure: false,
        expires: new Date("2026-10-15T00:00:00Z"),
      }),
    );
    expect(jar.get("costura_session")).toBe("tok-2");
  });

  it("marks the cookie secure away from localhost", async () => {
    host = "costura.example.com";
    mocked.devSignIn.mockResolvedValue({
      token: "tok-3",
      expires_at: "2026-10-15T00:00:00Z",
      user: { email: "jane@acme.com", name: null },
    });
    await expect(signInAction(idle, form("jane@acme.com"))).rejects.toThrow("NEXT_REDIRECT /");
    // Over HTTPS the cookie takes the `__Host-` prefix; the reader accepts either name.
    expect(cookieStore.set).toHaveBeenCalledWith(
      expect.objectContaining({ name: "__Host-costura_session", secure: true, path: "/" }),
    );
    expect(jar.get("__Host-costura_session")).toBe("tok-3");
    expect(mocked.devSignIn).toHaveBeenCalledWith("jane@acme.com", undefined);
  });

  it("refuses a malformed address before asking the API", async () => {
    await expect(signInAction(idle, form("jane"))).resolves.toEqual({
      ok: false,
      message: "Enter an e-mail address like you@example.com.",
      field: "email",
    });
    expect(mocked.devSignIn).not.toHaveBeenCalled();
  });

  it("explains a 403, keeps a 422 on the field and names a down API", async () => {
    mocked.devSignIn.mockRejectedValue(
      new ApiError(403, "/auth/dev-sign-in", "dev sign-in is disabled in this environment"),
    );
    await expect(signInAction(idle, form("jane@acme.com"))).resolves.toEqual({
      ok: false,
      message: "This API refuses the development sign-in; it runs in production mode.",
    });

    mocked.devSignIn.mockRejectedValue(
      new ApiError(403, "/auth/dev-sign-in", "write routes require authentication"),
    );
    await expect(signInAction(idle, form("jane@acme.com"))).resolves.toEqual({
      ok: false,
      message:
        "This API accepts the development sign-in only from a loopback address on this machine.",
    });

    mocked.devSignIn.mockRejectedValue(new ApiError(422, "/auth/dev-sign-in", "invalid e-mail"));
    await expect(signInAction(idle, form("jane@acme.com"))).resolves.toEqual({
      ok: false,
      message: "invalid e-mail",
      field: "email",
    });

    mocked.devSignIn.mockRejectedValue(new TypeError("fetch failed"));
    await expect(signInAction(idle, form("jane@acme.com"))).resolves.toEqual({
      ok: false,
      message: "Costura did not answer. Retry in a moment.",
      field: undefined,
    });
    expect(cookieStore.set).not.toHaveBeenCalled();
    expect(redirect).not.toHaveBeenCalled();
  });
});

describe("signOutEverywhereAction", () => {
  it("revokes every session on the API, clears the cookie and lands on sign-in", async () => {
    signedIn();
    mocked.signOutEverywhere.mockResolvedValue(undefined);
    await expect(signOutEverywhereAction()).rejects.toThrow("NEXT_REDIRECT /sign-in");
    expect(mocked.signOutEverywhere).toHaveBeenCalledTimes(1);
    expect(mocked.signOut).not.toHaveBeenCalled();
    expect(jar.has("costura_session")).toBe(false);
  });
});

describe("signOutAction", () => {
  it("ends the API session, clears the cookie and lands on sign-in", async () => {
    signedIn();
    mocked.signOut.mockResolvedValue(undefined);
    await expect(signOutAction()).rejects.toThrow("NEXT_REDIRECT /sign-in");
    expect(cookieStore.delete).toHaveBeenCalledWith("costura_session");
    expect(jar.has("costura_session")).toBe(false);
  });

  it("clears the cookie when the API session is already gone", async () => {
    signedIn();
    mocked.signOut.mockRejectedValue(new ApiError(401, "/auth/sign-out", "no session"));
    await expect(signOutAction()).rejects.toThrow("NEXT_REDIRECT /sign-in");
    expect(jar.has("costura_session")).toBe(false);
  });

  it("propagates other refusals without touching the cookie", async () => {
    signedIn();
    mocked.signOut.mockRejectedValue(new ApiError(500, "/auth/sign-out", "boom"));
    await expect(signOutAction()).rejects.toThrow("500 /auth/sign-out: boom");
    expect(jar.has("costura_session")).toBe(true);
  });
});

describe("/new", () => {
  it("requires a session", async () => {
    await expect(NewOrgPage()).rejects.toThrow("NEXT_REDIRECT /sign-in");
    expect(mocked.me).not.toHaveBeenCalled();
  });

  it("pre-fills the name from the e-mail domain and previews the address live", async () => {
    signedIn();
    mocked.me.mockResolvedValue(noOrgs);
    render(await NewOrgPage());

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Name your organization");
    expect(screen.getByText(/Signed in as jane@acme.com/)).toBeInTheDocument();
    expect(screen.queryByText(/rename it later/i)).not.toBeInTheDocument();
    const name = screen.getByLabelText("Name");
    expect(name).toHaveValue("Acme");
    expect(screen.getByText("/acme")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create organization" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^Back to/ })).not.toBeInTheDocument();

    fireEvent.change(name, { target: { value: "Acme Corp." } });
    expect(screen.getByText("/acme-corp")).toBeInTheDocument();
    const form = name.closest("form")!;
    expect(form.querySelector('input[name="slug"]')).toHaveAttribute("value", "acme-corp");

    // Edit turns the preview into a field; the name stops driving it.
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const slug = screen.getByLabelText("Address");
    expect(slug).toHaveValue("acme-corp");
    fireEvent.change(slug, { target: { value: "acme-eu" } });
    fireEvent.change(name, { target: { value: "Acme Europe" } });
    expect(slug).toHaveValue("acme-eu");
  });

  it("links back to the first organization when the user already has one", async () => {
    signedIn();
    render(await NewOrgPage());
    expect(screen.getByRole("link", { name: "Back to Acme" })).toHaveAttribute("href", "/o/acme");
  });

  it("shows the taken address inline with the next free one to use", async () => {
    signedIn();
    mocked.me.mockResolvedValue(noOrgs);
    vi.mocked(createOrgAction).mockResolvedValue({
      ok: false,
      message: "The address /acme is taken.",
      field: "slug",
      suggestion: "acme-2",
    });
    render(await NewOrgPage());

    fireEvent.submit(screen.getByRole("button", { name: "Create organization" }).closest("form")!);

    expect(await screen.findByRole("alert")).toHaveTextContent("The address /acme is taken.");
    // The name typed before the refusal stays.
    expect(screen.getByLabelText("Name")).toHaveValue("Acme");
    fireEvent.click(screen.getByRole("button", { name: "Use /acme-2" }));
    await waitFor(() => expect(screen.getByLabelText("Address")).toHaveValue("acme-2"));
  });
});

describe("createOrgAction", () => {
  const idle = { ok: false, message: null, suggestion: null };
  const form = (name: string, slug: string) => {
    const data = new FormData();
    data.set("name", name);
    data.set("slug", slug);
    return data;
  };
  let action: typeof createOrgAction;

  beforeEach(async () => {
    const actual = await vi.importActual<typeof import("./new/actions")>("./new/actions");
    action = actual.createOrgAction;
  });

  it("creates the organization and lands on its welcome page", async () => {
    mocked.createOrg.mockResolvedValue(owner);
    await expect(action(idle, form(" Acme ", "acme"))).rejects.toThrow("NEXT_REDIRECT /welcome");
    expect(mocked.createOrg).toHaveBeenCalledWith("Acme", "acme");
    // The new organization is the active one from here on.
    expect(JSON.parse(jar.get("costura_view")!)).toMatchObject({ org: "acme" });
  });

  it("validates the name and the address before asking the API", async () => {
    await expect(action(idle, form("", "acme"))).resolves.toMatchObject({ field: "name" });
    await expect(action(idle, form("Acme", "-acme"))).resolves.toMatchObject({ field: "slug" });
    await expect(action(idle, form("Acme", "a"))).resolves.toMatchObject({ field: "slug" });
    expect(mocked.createOrg).not.toHaveBeenCalled();
  });

  it("names a reserved address without suggesting another reserved one", async () => {
    mocked.createOrg.mockRejectedValue(
      new ApiError(409, "/orgs", "organization slug 'demo' is reserved for this deployment"),
    );
    await expect(action(idle, form("Demo", "demo"))).resolves.toEqual({
      ok: false,
      message: "The address /demo is reserved on this deployment. Choose another.",
      field: "slug",
      suggestion: null,
    });
  });

  it("turns 409 into the taken message with the next slug, 422 into a field error", async () => {
    mocked.createOrg.mockRejectedValue(new ApiError(409, "/orgs", "slug taken"));
    await expect(action(idle, form("Acme", "acme-2"))).resolves.toEqual({
      ok: false,
      message: "The address /acme-2 is taken.",
      field: "slug",
      suggestion: "acme-3",
    });

    mocked.createOrg.mockRejectedValue(new ApiError(422, "/orgs", "invalid slug"));
    await expect(action(idle, form("Acme", "acme"))).resolves.toEqual({
      ok: false,
      message: "invalid slug",
      field: "slug",
      suggestion: null,
    });
    expect(redirect).not.toHaveBeenCalled();
  });
});

describe("sidebar account menu", () => {
  const account = { slug: "acme", name: "Acme", role: "owner" as const, isDemo: false };
  const jane = {
    email: "jane@acme.com",
    invitations: 0,
    organizations: [{ slug: "acme", name: "Acme", role: "owner" as const }],
  };

  it("renders the host brand on the shell for light and dark", () => {
    const { unmount } = render(
      <div data-theme="light">
        <Sidebar account={account} brandName="Northwind" />
      </div>,
    );
    expect(screen.getByText("Northwind")).toBeInTheDocument();
    expect(document.querySelector("[data-brand-mark]")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
    expect(document.querySelector("[data-theme='light']")).toBeTruthy();
    unmount();
    render(
      <div data-theme="dark">
        <Sidebar account={account} brandName="Northwind" />
      </div>,
    );
    expect(document.querySelector("[data-theme='dark']")).toBeTruthy();
    expect(screen.getByText("Northwind")).toBeInTheDocument();
  });

  it("shows the account menu only when a user is given", async () => {
    const { unmount } = render(<Sidebar account={account} />);
    expect(screen.queryByRole("button", { name: "Account menu" })).not.toBeInTheDocument();
    unmount();

    render(<Sidebar account={account} user={jane} />);
    const aside = screen.getByRole("complementary", { name: "Sidebar" });
    const trigger = within(aside).getByRole("button", { name: "Account menu" });
    expect(trigger).toHaveTextContent("Acme");
    expect(trigger).toHaveTextContent("Owner - Acme");
    fireEvent.keyDown(trigger, { key: "Enter" });
    const menu = await screen.findByRole("menu");
    expect(within(menu).getByText("jane@acme.com")).toBeInTheDocument();
    expect(within(menu).getByRole("menuitem", { name: "New organization" })).toHaveAttribute(
      "href",
      "/new",
    );
    expect(within(menu).queryByRole("menuitem", { name: /Invitations/ })).not.toBeInTheDocument();
    expect(within(menu).getByRole("menuitem", { name: "Log out" })).toHaveAttribute(
      "type",
      "submit",
    );
  });

  it("repeats the account menu in the mobile sheet", () => {
    render(<MobileNav account={account} user={jane} />);
    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Account menu" })).toHaveTextContent("Acme");
  });

  it("offers Sign in to a visitor on the sample organization, on desktop and mobile", () => {
    const sample = { slug: "demo", name: "Sample organization", role: null, isDemo: true };
    const { unmount } = render(<Sidebar account={sample} user={null} />);
    const aside = screen.getByRole("complementary", { name: "Sidebar" });
    expect(within(aside).getByRole("link", { name: "Sign in" })).toHaveAttribute(
      "href",
      "/sign-in",
    );
    expect(within(aside).queryByRole("button", { name: "Account menu" })).not.toBeInTheDocument();
    unmount();

    render(<MobileNav account={sample} user={null} />);
    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    expect(
      within(screen.getByRole("dialog")).getByRole("link", { name: "Sign in" }),
    ).toHaveAttribute("href", "/sign-in");
  });
});
