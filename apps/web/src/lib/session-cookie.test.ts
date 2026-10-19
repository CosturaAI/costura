import { beforeEach, describe, expect, it, vi } from "vitest";

let host: string | null = "localhost:3000";
const values = new Map<string, string>();
const set = vi.fn();
const remove = vi.fn();

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => (values.has(name) ? { name, value: values.get(name)! } : undefined),
    set,
    delete: remove,
  }),
  headers: async () => new Headers(host === null ? {} : { host }),
}));

import {
  HOST_SESSION_COOKIE,
  SESSION_COOKIE,
  clearSessionCookie,
  isLocalhost,
  readSessionToken,
  sessionCookieName,
  setSessionCookie,
} from "./session-cookie";

beforeEach(() => {
  host = "localhost:3000";
  values.clear();
  set.mockReset();
  remove.mockReset();
});

describe("session cookie", () => {
  it("prefers the secure host cookie and treats empty values as absent", async () => {
    values.set(SESSION_COOKIE, "plain");
    values.set(HOST_SESSION_COOKIE, "secure");
    await expect(readSessionToken()).resolves.toBe("secure");
    values.set(HOST_SESSION_COOKIE, "");
    await expect(readSessionToken()).resolves.toBeNull();
    values.clear();
    await expect(readSessionToken()).resolves.toBeNull();
  });

  it("ignores a plain cookie on an external host, where only __Host- is trusted", async () => {
    host = "costura.example.com";
    values.set(SESSION_COOKIE, "planted");
    await expect(readSessionToken()).resolves.toBeNull();
    values.set(HOST_SESSION_COOKIE, "secure");
    await expect(readSessionToken()).resolves.toBe("secure");
  });

  it.each(["localhost", "localhost:3000", "127.0.0.1:80", "[::1]:3000"])(
    "uses the plain cookie on %s",
    (localHost) => {
      expect(isLocalhost(localHost)).toBe(true);
      expect(sessionCookieName(localHost)).toBe(SESSION_COOKIE);
    },
  );

  it("uses the __Host cookie on external or missing hosts", () => {
    expect(isLocalhost("costura.example.com")).toBe(false);
    expect(isLocalhost(null)).toBe(false);
    expect(sessionCookieName("costura.example.com")).toBe(HOST_SESSION_COOKIE);
  });

  it("sets an insecure localhost cookie with a valid expiry", async () => {
    await setSessionCookie("token", "2026-11-01T00:00:00Z");
    expect(set).toHaveBeenCalledWith(
      expect.objectContaining({
        name: SESSION_COOKIE,
        value: "token",
        httpOnly: true,
        sameSite: "lax",
        secure: false,
        expires: new Date("2026-11-01T00:00:00Z"),
      }),
    );
  });

  it("sets a secure external cookie and omits an invalid expiry", async () => {
    host = "costura.example.com";
    await setSessionCookie("token", "not-a-date");
    const options = set.mock.calls[0]![0] as Record<string, unknown>;
    expect(options).toMatchObject({ name: HOST_SESSION_COOKIE, secure: true });
    expect(options).not.toHaveProperty("expires");
  });

  it("clears both cookie names", async () => {
    await clearSessionCookie();
    expect(remove.mock.calls.map(([name]) => name)).toEqual([SESSION_COOKIE, HOST_SESSION_COOKIE]);
  });
});
