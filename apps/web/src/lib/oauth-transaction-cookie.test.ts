import { beforeEach, describe, expect, it, vi } from "vitest";

let host = "localhost:3000";
const values = new Map<string, string>();
const set = vi.fn();
const remove = vi.fn();

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => (values.has(name) ? { name, value: values.get(name)! } : undefined),
    set,
    delete: remove,
  }),
  headers: async () => new Headers({ host }),
}));

import {
  GOOGLE_OAUTH_COOKIE,
  HOST_GOOGLE_OAUTH_COOKIE,
  clearGoogleOAuthCookie,
  parseGoogleOAuthCookie,
  readGoogleOAuthCookie,
  setGoogleOAuthCookie,
  type GoogleOAuthTransaction,
} from "./oauth-transaction-cookie";

const transaction: GoogleOAuthTransaction = {
  state: "s".repeat(32),
  nonce: "n".repeat(32),
  codeVerifier: "v".repeat(43),
  next: "/overview",
};

beforeEach(() => {
  host = "localhost:3000";
  values.clear();
  set.mockReset();
  remove.mockReset();
});

describe("Google OAuth transaction cookie", () => {
  it("round-trips an encoded transaction", () => {
    const value = encodeURIComponent(JSON.stringify(transaction));
    expect(parseGoogleOAuthCookie(value)).toEqual(transaction);
  });

  it.each([
    undefined,
    "not-json",
    encodeURIComponent(JSON.stringify({ ...transaction, state: "short" })),
    encodeURIComponent(JSON.stringify({ ...transaction, nonce: "!".repeat(32) })),
    encodeURIComponent(JSON.stringify({ ...transaction, codeVerifier: 3 })),
    encodeURIComponent(JSON.stringify({ ...transaction, next: null })),
  ])("rejects malformed transaction", (value) => {
    expect(parseGoogleOAuthCookie(value)).toBeNull();
  });

  it("prefers the secure cookie", async () => {
    values.set(
      GOOGLE_OAUTH_COOKIE,
      encodeURIComponent(JSON.stringify({ ...transaction, next: "/plain" })),
    );
    values.set(HOST_GOOGLE_OAUTH_COOKIE, encodeURIComponent(JSON.stringify(transaction)));
    await expect(readGoogleOAuthCookie()).resolves.toEqual(transaction);
  });

  it("sets plain localhost and secure external cookies", async () => {
    await setGoogleOAuthCookie(transaction, "2026-10-10T08:00:00Z");
    expect(set).toHaveBeenLastCalledWith(
      expect.objectContaining({ name: GOOGLE_OAUTH_COOKIE, secure: false }),
    );
    host = "costura.example.com";
    await setGoogleOAuthCookie(transaction, "2026-10-10T08:00:00Z");
    expect(set).toHaveBeenLastCalledWith(
      expect.objectContaining({ name: HOST_GOOGLE_OAUTH_COOKIE, secure: true }),
    );
  });

  it("clears both variants", async () => {
    await clearGoogleOAuthCookie();
    expect(remove.mock.calls.map(([name]) => name)).toEqual([
      GOOGLE_OAUTH_COOKIE,
      HOST_GOOGLE_OAUTH_COOKIE,
    ]);
  });
});
