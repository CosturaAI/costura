import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { describeError } from "./action-errors";
import { ApiError, api } from "./api";

const redirect = vi.fn((url: string) => {
  const error = new Error(`NEXT_REDIRECT ${url}`) as Error & { digest: string };
  error.digest = `NEXT_REDIRECT;replace;${url};307;`;
  throw error;
});
vi.mock("next/navigation", () => ({ redirect: (url: string) => redirect(url) }));

let token: string | null = null;
let pagePath: string | null = null;
vi.mock("next/headers", () => ({
  cookies: () =>
    Promise.resolve({
      get: (name: string) =>
        name === "costura_session" && token !== null ? { name, value: token } : undefined,
    }),
  headers: () =>
    Promise.resolve(
      new Headers({
        host: "localhost:3000",
        ...(pagePath === null ? {} : { "x-costura-path": pagePath }),
      }),
    ),
}));

const fetchMock = vi.fn();
const answer = (status: number, body?: unknown) =>
  fetchMock.mockResolvedValue(
    new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
const sentHeaders = () => new Headers((fetchMock.mock.calls[0]![1] as RequestInit).headers);

beforeEach(() => {
  vi.clearAllMocks();
  token = null;
  pagePath = null;
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("request wrapper", () => {
  it("attaches the session cookie's token as a bearer", async () => {
    token = "tok-1";
    answer(200, []);
    await api.orgs();
    expect(sentHeaders().get("authorization")).toBe("Bearer tok-1");
    expect(String(fetchMock.mock.calls[0]![0])).toMatch(/\/api\/v1\/orgs$/);
  });

  it("sends no bearer without a cookie, and never for the sign-in call", async () => {
    answer(200, []);
    await api.orgs();
    expect(sentHeaders().get("authorization")).toBeNull();

    token = "tok-1";
    fetchMock.mockClear();
    answer(201, { token: "t", expires_at: "2026-10-01T00:00:00Z", user: { email: "a@b.co" } });
    await api.devSignIn("a@b.co");
    expect(sentHeaders().get("authorization")).toBeNull();
    expect(sentHeaders().get("content-type")).toBe("application/json");
    expect((fetchMock.mock.calls[0]![1] as RequestInit).body).toBe(
      JSON.stringify({ email: "a@b.co" }),
    );
  });

  it("sends the browser to /sign-in on 401", async () => {
    token = "stale";
    answer(401, { detail: "session expired" });
    await expect(api.me()).rejects.toThrow("NEXT_REDIRECT /sign-in");
    expect(redirect).toHaveBeenCalledWith("/sign-in?expired=1");
  });

  it("says the session ended and returns to the page it was on", async () => {
    token = "stale";
    pagePath = "/anomalies?status=open";
    answer(401, { detail: "session expired" });
    await expect(api.me()).rejects.toThrow("NEXT_REDIRECT");
    expect(redirect).toHaveBeenCalledWith("/sign-in?expired=1&next=%2Fanomalies%3Fstatus%3Dopen");
  });

  it("keeps a foreign next out and sends a visitor without a token to plain /sign-in", async () => {
    token = "stale";
    pagePath = "//evil.test/x";
    answer(401, { detail: "session expired" });
    await expect(api.me()).rejects.toThrow("NEXT_REDIRECT");
    expect(redirect).toHaveBeenLastCalledWith("/sign-in?expired=1");

    token = null;
    answer(401, { detail: "not signed in" });
    await expect(api.me()).rejects.toThrow("NEXT_REDIRECT");
    expect(redirect).toHaveBeenLastCalledWith("/sign-in");
  });

  it("answers 401 as an ApiError where the caller asked for it", async () => {
    answer(401, { detail: "session expired" });
    await expect(api.session()).rejects.toThrow("401 /me: session expired");
    await expect(api.signOut()).rejects.toBeInstanceOf(ApiError);
    expect(redirect).not.toHaveBeenCalled();
  });

  it("keeps other refusals as ApiError with the detail", async () => {
    answer(409, { detail: "slug taken" });
    await expect(api.createOrg("Acme", "acme")).rejects.toThrow("409 /orgs: slug taken");
    expect(redirect).not.toHaveBeenCalled();
  });

  it("carries the API's error code when the body names one", async () => {
    answer(409, { detail: "slug taken", code: "duplicate_slug" });
    const refusal = await api.createOrg("Acme", "acme").catch((e: unknown) => e);
    expect(refusal).toBeInstanceOf(ApiError);
    expect((refusal as ApiError).code).toBe("duplicate_slug");

    answer(422, { detail: [{ loc: ["body", "slug"], msg: "bad", type: "x" }], code: 7 });
    const invalid = await api.createOrg("Acme", "acme").catch((e: unknown) => e);
    expect((invalid as ApiError).code).toBeNull();
    expect((invalid as ApiError).detail).toContain('"loc"');

    fetchMock.mockResolvedValue(new Response("gateway timeout", { status: 504 }));
    const proxy = await api.createOrg("Acme", "acme").catch((e: unknown) => e);
    expect((proxy as ApiError).code).toBeNull();
  });
});

describe("anomaly and alert endpoints", () => {
  it("reads one anomaly and orders the list by impact on request", async () => {
    answer(200, {});
    await api.anomaly("acme", "all", 7);
    expect(String(fetchMock.mock.calls[0]![0])).toMatch(
      /\/api\/v1\/orgs\/acme\/providers\/all\/anomalies\/7$/,
    );

    fetchMock.mockClear();
    answer(200, {});
    await api.anomalies("acme", "anthropic", "2026-08", "open", undefined, "impact");
    const url = new URL(String(fetchMock.mock.calls[0]![0]));
    expect(url.pathname).toBe("/api/v1/orgs/acme/providers/anthropic/months/2026-08/anomalies");
    expect(url.searchParams.get("sort")).toBe("impact");
    expect(url.searchParams.get("status")).toBe("open");
    expect(url.searchParams.has("series_kind")).toBe(false);
  });

  it("reads the inbox, switches the opt-in and marks anomalies read", async () => {
    answer(200, { opted_in: false, unread_count: 0, items: [] });
    await api.alerts("acme");
    expect(String(fetchMock.mock.calls[0]![0])).toMatch(/\/api\/v1\/orgs\/acme\/alerts$/);

    fetchMock.mockClear();
    answer(200, {});
    await api.setAlertSettings("acme", true);
    let init = fetchMock.mock.calls[0]![1] as RequestInit;
    expect(String(fetchMock.mock.calls[0]![0])).toMatch(/\/orgs\/acme\/alerts\/settings$/);
    expect(init.method).toBe("PUT");
    expect(init.body).toBe(JSON.stringify({ opted_in: true }));

    fetchMock.mockClear();
    answer(200, {});
    await api.markAlertsRead("acme", { ids: [7, 8] });
    init = fetchMock.mock.calls[0]![1] as RequestInit;
    expect(String(fetchMock.mock.calls[0]![0])).toMatch(/\/orgs\/acme\/alerts\/read$/);
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ anomaly_ids: [7, 8] }));

    fetchMock.mockClear();
    answer(200, {});
    await api.markAlertsRead("acme", { all: true });
    expect((fetchMock.mock.calls[0]![1] as RequestInit).body).toBe(JSON.stringify({ all: true }));
  });
});

describe("time-range query", () => {
  it("serializes dimensions, filters, comparison and projection", async () => {
    answer(200, {});

    await api.query("acme", {
      measure: "billed_usd",
      dimensions: ["provider", "model"],
      start: "2026-07-01",
      end: "2026-09-17",
      interval: "week",
      top: 12,
      compare: "previous_period",
      projection: "linear",
      lookback: 12,
      horizon: 6,
      filters: { workspace: "workspace-1", provider: "anthropic" },
    });

    const url = new URL(String(fetchMock.mock.calls[0]![0]));
    expect(url.pathname).toBe("/api/v1/orgs/acme/query");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      measure: "billed_usd",
      dimensions: "provider,model",
      start: "2026-07-01",
      end: "2026-09-17",
      interval: "week",
      top: "12",
      compare: "previous_period",
      projection: "linear",
      lookback: "12",
      horizon: "6",
      workspace: "workspace-1",
      provider: "anthropic",
    });
  });

  it("serializes operator filters as repeatable f parameters", async () => {
    answer(200, {});

    await api.query("acme", {
      measure: "billed_usd",
      dimensions: ["model"],
      start: "2026-09-01",
      end: "2026-09-30",
      interval: "day",
      filters: {
        model: { op: "is_not", values: ["gpt-4o"] },
        workspace: { op: "one_of", values: ["Backend", "Platform"] },
      },
    });

    const url = new URL(String(fetchMock.mock.calls[0]![0]));
    expect(url.searchParams.getAll("f")).toEqual([
      "model:is_not:gpt-4o",
      "workspace:one_of:Backend,Platform",
    ]);
    expect(url.searchParams.has("model")).toBe(false);

    fetchMock.mockClear();
    answer(200, {});
    await api.usage("acme", "all", "2026-09", "model", 25, {
      model: { op: "contains", values: ["gpt"] },
      workspace: { op: "exists", values: [] },
    });
    const usageUrl = new URL(String(fetchMock.mock.calls[0]![0]));
    expect(usageUrl.searchParams.getAll("f")).toEqual(["model:contains:gpt", "workspace:exists:"]);
  });
});

describe("describeError", () => {
  it("lets a redirect thrown by the wrapper leave the action's catch block", () => {
    let caught: unknown;
    try {
      redirect("/sign-in");
    } catch (error) {
      caught = error;
    }
    expect(() => describeError(caught)).toThrow("NEXT_REDIRECT /sign-in");
    expect(describeError(new Error("plain"))).toBe("plain");
  });

  it("words a refused write and an unreachable API without commands", () => {
    expect(
      describeError(
        new ApiError(
          403,
          "/orgs/default/setup",
          "write routes are disabled: they require COSTURA_ENV=development or test and a request from 127.0.0.1 or ::1 until authentication exists",
        ),
      ),
    ).toBe(
      "This Costura instance does not accept changes from the browser: connecting a key, Sync now and reset are turned off here.",
    );
    expect(describeError(new TypeError("fetch failed"))).toBe(
      "Costura did not answer. Retry in a moment.",
    );
  });

  it("words API 404 details for workspaces, budgets and anomalies", () => {
    const cases = [
      ["workspace", "workspace not found", "Workspace not found."],
      ["budget", "budget has gone", "Budget has gone."],
      ["anomaly", "anomaly disappeared", "Anomaly disappeared."],
    ] as const;
    for (const [, detail, expected] of cases) {
      expect(describeError(new ApiError(404, "/api/v1/resource", detail))).toBe(expected);
    }
    expect(
      describeError(new ApiError(404, "/api/v1/orgs/acme", "unknown organization 'acme'")),
    ).toBe("Organization not found on the API.");
    expect(
      describeError(new ApiError(404, "/api/v1/orgs/acme", "gone", null, "unknown_organization")),
    ).toBe("Organization not found on the API.");
    expect(describeError(new ApiError(404, "/api/v1/orgs/acme/teams/x", "team not found"))).toBe(
      "Team not found.",
    );
  });

  it("turns any other API detail into a sentence", () => {
    expect(describeError(new ApiError(409, "/orgs/acme/sync", "a sync is running"))).toBe(
      "A sync is running.",
    );
    expect(describeError(new ApiError(422, "/orgs/acme", "Name is too long."))).toBe(
      "Name is too long.",
    );
  });
  it("keeps a role or invitation refusal, which names what to do next", () => {
    expect(
      describeError(
        new ApiError(
          403,
          "/orgs/acme/invitations",
          "this action needs the owner role in the organization",
        ),
      ),
    ).toBe("This action needs the owner role in the organization.");
    expect(
      describeError(
        new ApiError(
          410,
          "/invitations/claim",
          "this invitation is no longer valid; ask an owner for a new one",
        ),
      ),
    ).toBe("This invitation is no longer valid; ask an owner for a new one.");
  });
});
