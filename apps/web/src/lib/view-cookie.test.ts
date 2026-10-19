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
  HOST_VIEW_COOKIE,
  VIEW_COOKIE,
  clearViewCookie,
  parseViewCookie,
  readViewCookie,
  viewCookieName,
  writeViewCookie,
} from "./view-cookie";

beforeEach(() => {
  host = "localhost:3000";
  values.clear();
  set.mockReset();
  remove.mockReset();
});

describe("view cookie", () => {
  it.each([undefined, null, "", "not-json", "[]", JSON.stringify({ org: "A" })])(
    "rejects malformed value %s",
    (value) => expect(parseViewCookie(value)).toBeNull(),
  );

  it("sanitizes every optional field and inverted ranges", () => {
    expect(
      parseViewCookie(
        JSON.stringify({
          org: "acme",
          month: "2026-13",
          scope: "not valid!",
          from: "2026-10-11",
          to: "2026-10-10",
          interval: "year",
          timeFrame: "future",
        }),
      ),
    ).toEqual({
      org: "acme",
      month: null,
      scope: null,
      from: null,
      to: null,
      interval: null,
      timeFrame: null,
    });
  });

  it("accepts a month without a range", () => {
    expect(
      parseViewCookie(JSON.stringify({ org: "acme", month: "2026-08", scope: "anthropic" })),
    ).toEqual({
      org: "acme",
      month: "2026-08",
      scope: "anthropic",
      from: null,
      to: null,
      interval: null,
      timeFrame: null,
    });
  });

  it("keeps a valid range and drops an incomplete one", () => {
    expect(
      parseViewCookie(
        JSON.stringify({
          org: "acme",
          month: "2026-09",
          scope: "all",
          from: "2026-07-01",
          to: "2026-09-17",
          interval: "week",
        }),
      ),
    ).toMatchObject({ from: "2026-07-01", to: "2026-09-17", interval: "week" });

    expect(
      parseViewCookie(JSON.stringify({ org: "acme", from: "2026-07-01", interval: "month" })),
    ).toMatchObject({ from: null, to: null, interval: "month" });
  });

  it("keeps complete and rolling period semantics", () => {
    expect(
      parseViewCookie(
        JSON.stringify({
          org: "acme",
          from: "2026-09-11",
          to: "2026-09-17",
          timeFrame: "rolling_7_days",
        }),
      ),
    ).toMatchObject({ timeFrame: "rolling_7_days" });
    expect(
      parseViewCookie(JSON.stringify({ org: "acme", timeFrame: "future_7_days" })),
    ).toMatchObject({ timeFrame: null });
  });

  it("reads the secure cookie first", async () => {
    values.set(VIEW_COOKIE, JSON.stringify({ org: "plain" }));
    values.set(HOST_VIEW_COOKIE, JSON.stringify({ org: "secure" }));
    await expect(readViewCookie()).resolves.toMatchObject({ org: "secure" });
  });

  it("selects cookie name by host and writes one-year state", async () => {
    expect(viewCookieName("localhost")).toBe(VIEW_COOKIE);
    expect(viewCookieName("costura.example.com")).toBe(HOST_VIEW_COOKIE);
    host = "costura.example.com";
    await writeViewCookie({
      org: "acme",
      month: "2026-10",
      from: "2026-10-01",
      to: "2026-10-10",
      interval: "day",
      timeFrame: "custom",
    });
    const options = set.mock.calls[0]![0] as Record<string, unknown>;
    expect(options).toMatchObject({
      name: HOST_VIEW_COOKIE,
      secure: true,
      httpOnly: true,
      maxAge: 365 * 24 * 60 * 60,
    });
    expect(JSON.parse(String(options.value))).toMatchObject({ org: "acme", timeFrame: "custom" });
  });

  it("clears both variants", async () => {
    await clearViewCookie();
    expect(remove.mock.calls.map(([name]) => name)).toEqual([VIEW_COOKIE, HOST_VIEW_COOKIE]);
  });
});
