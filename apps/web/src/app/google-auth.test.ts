import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const googleAuthorization = vi.fn();
const googleCallback = vi.fn();
const setGoogleOAuthCookie = vi.fn();
const clearGoogleOAuthCookie = vi.fn();
const readGoogleOAuthCookie = vi.fn();
const setSessionCookie = vi.fn();

vi.mock("@/lib/api", () => ({
  api: { googleAuthorization, googleCallback },
}));

vi.mock("@/lib/oauth-transaction-cookie", () => ({
  setGoogleOAuthCookie,
  clearGoogleOAuthCookie,
  readGoogleOAuthCookie,
}));
vi.mock("@/lib/session-cookie", () => ({ setSessionCookie }));

const { GET: start } = await import("./api/auth/google/start/route");
const { GET: callback } = await import("./api/auth/google/callback/route");

beforeEach(() => {
  vi.clearAllMocks();
  googleAuthorization.mockResolvedValue({
    authorization_url: "https://accounts.google.com/o/oauth2/v2/auth?state=state-value",
    state: "state-value",
    nonce: "nonce-value",
    code_verifier: "verifier-value",
    expires_at: "2026-09-17T15:00:00Z",
  });
  readGoogleOAuthCookie.mockResolvedValue({
    state: "state-value",
    nonce: "nonce-value",
    codeVerifier: "verifier-value",
    next: "/join/abc",
  });
});

describe("Google web callback", () => {
  it("stores the transaction before redirecting to Google", async () => {
    const response = await start(
      new NextRequest("https://costura.example.test/api/auth/google/start?next=/join/abc"),
    );
    expect(response.headers.get("location")).toMatch(/^https:\/\/accounts\.google\.com\//);
    expect(setGoogleOAuthCookie).toHaveBeenCalledWith(
      {
        state: "state-value",
        nonce: "nonce-value",
        codeVerifier: "verifier-value",
        next: "/join/abc",
      },
      "2026-09-17T15:00:00Z",
    );
  });

  it("exchanges the callback server-side, stores the Costura session, and clears state", async () => {
    googleCallback.mockResolvedValue({
      token: "costura-token",
      expires_at: "2026-10-17T15:00:00Z",
      user: { email: "verified@example.com", name: null },
    });
    const response = await callback(
      new NextRequest(
        "https://costura.example.test/api/auth/google/callback?code=code&state=state-value",
      ),
    );
    expect(googleCallback).toHaveBeenCalledWith({
      code: "code",
      state: "state-value",
      nonce: "nonce-value",
      code_verifier: "verifier-value",
    });
    expect(setSessionCookie).toHaveBeenCalledWith("costura-token", "2026-10-17T15:00:00Z");
    expect(clearGoogleOAuthCookie).toHaveBeenCalled();
    expect(response.headers.get("location")).toBe("https://costura.example.test/join/abc");
  });

  it("rejects state mismatch and clears the transaction without exchanging", async () => {
    const response = await callback(
      new NextRequest(
        "https://costura.example.test/api/auth/google/callback?code=code&state=wrong-state",
      ),
    );
    expect(googleCallback).not.toHaveBeenCalled();
    expect(clearGoogleOAuthCookie).toHaveBeenCalled();
    expect(response.headers.get("location")).toContain("/sign-in?error=state");
  });

  it("turns provider and exchange failures into cleared sign-in errors", async () => {
    const denied = await callback(
      new NextRequest(
        "https://costura.example.test/api/auth/google/callback?error=access_denied&state=state-value",
      ),
    );
    expect(denied.headers.get("location")).toContain("/sign-in?error=denied");

    googleCallback.mockRejectedValue(new Error("invalid token"));
    const failed = await callback(
      new NextRequest(
        "https://costura.example.test/api/auth/google/callback?code=code&state=state-value",
      ),
    );
    expect(failed.headers.get("location")).toContain("/sign-in?error=callback");
    expect(clearGoogleOAuthCookie).toHaveBeenCalledTimes(2);
  });
});
