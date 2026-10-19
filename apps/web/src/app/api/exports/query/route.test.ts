import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ readSessionToken: vi.fn(), readViewCookie: vi.fn() }));
vi.mock("@/lib/session-cookie", () => ({ readSessionToken: mocks.readSessionToken }));
vi.mock("@/lib/view-cookie", () => ({ readViewCookie: mocks.readViewCookie }));

import { GET } from "./route";

const fetchMock = vi.fn();
const RANGE = "start=2026-07-01&end=2026-09-17";

beforeEach(() => {
  vi.clearAllMocks();
  mocks.readViewCookie.mockResolvedValue({ org: "acme", month: "2026-07", scope: "all" });
  vi.stubGlobal("fetch", fetchMock);
  vi.stubEnv("COSTURA_API_URL", "http://api.internal/");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("CSV export route", () => {
  it("forwards the session and allowlisted parameters while streaming CSV headers", async () => {
    mocks.readSessionToken.mockResolvedValue("session-token");
    fetchMock.mockResolvedValue(
      new Response("bucket,series_type,value\n", {
        headers: {
          "content-disposition": 'attachment; filename="costura.csv"',
          "content-length": "25",
          "content-type": "text/csv; charset=utf-8",
          "x-upstream-secret": "hidden",
        },
      }),
    );
    const request = new Request(
      `http://web.test/api/exports/query?measure=billed_usd&dimensions=model&${RANGE}&interval=week&provider=anthropic&unexpected=leak&format=json`,
    );

    const response = await GET(request);

    const [url, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(url.origin).toBe("http://api.internal");
    expect(url.pathname).toBe("/api/v1/orgs/acme/query");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      measure: "billed_usd",
      dimensions: "model",
      start: "2026-07-01",
      end: "2026-09-17",
      interval: "week",
      provider: "anthropic",
      format: "csv",
    });
    expect(new Headers(init.headers).get("authorization")).toBe("Bearer session-token");
    expect(init.cache).toBe("no-store");
    expect(response.status).toBe(200);
    expect(response.headers.get("content-disposition")).toBe('attachment; filename="costura.csv"');
    expect(response.headers.get("content-type")).toBe("text/csv; charset=utf-8");
    expect(response.headers.get("cache-control")).toBe("private, no-store, max-age=0");
    expect(response.headers.get("x-upstream-secret")).toBeNull();
    expect(await response.text()).toBe("bucket,series_type,value\n");
  });

  it("forwards without a bearer when there is no session and relays the API's 401", async () => {
    mocks.readSessionToken.mockResolvedValue(null);
    fetchMock.mockResolvedValue(
      Response.json({ detail: "sign in first" }, { status: 401, headers: { "x-hidden": "1" } }),
    );

    const response = await GET(new Request(`http://web.test/api/exports/query?${RANGE}`));

    const [, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(new Headers(init.headers).has("authorization")).toBe(false);
    expect(response.status).toBe(401);
    expect(response.headers.get("cache-control")).toContain("no-store");
    expect(response.headers.get("x-hidden")).toBeNull();
  });

  it("serves the public sample organization without a session", async () => {
    mocks.readSessionToken.mockResolvedValue(null);
    fetchMock.mockResolvedValue(
      new Response("bucket,series_type,value\n", {
        headers: { "content-type": "text/csv; charset=utf-8" },
      }),
    );

    mocks.readViewCookie.mockResolvedValue({ org: "demo", month: "2026-08", scope: "all" });
    const response = await GET(
      new Request(`http://web.test/api/exports/query?measure=billed_usd&${RANGE}`),
    );

    const [url] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(url.pathname).toBe("/api/v1/orgs/demo/query");
    expect(response.status).toBe(200);
    expect(await response.text()).toBe("bucket,series_type,value\n");
  });

  it("forwards repeated operator filters", async () => {
    mocks.readSessionToken.mockResolvedValue("session-token");
    fetchMock.mockResolvedValue(new Response("bucket,series_type,value\n"));
    const request = new Request(
      "http://web.test/api/exports/query?measure=billed_usd&dimensions=workspace&f=model%3Ais_not%3Agpt-4o&f=workspace%3Aone_of%3ABackend%2CPlatform&start=2026-09-01&end=2026-09-30&interval=day",
    );
    await GET(request);

    const [url] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(url.searchParams.get("dimensions")).toBe("workspace");
    expect(url.searchParams.getAll("f")).toEqual([
      "model:is_not:gpt-4o",
      "workspace:one_of:Backend,Platform",
    ]);
  });

  it("answers 404 without an active organization and 400 without valid dates", async () => {
    mocks.readSessionToken.mockResolvedValue("session-token");
    mocks.readViewCookie.mockResolvedValue(null);
    const none = await GET(new Request(`http://web.test/api/exports/query?${RANGE}`));
    expect(none.status).toBe(404);

    mocks.readViewCookie.mockResolvedValue({ org: "acme", month: "2026-08", scope: "all" });
    const noEnd = await GET(new Request("http://web.test/api/exports/query?start=2026-07-01"));
    expect(noEnd.status).toBe(400);
    const badDate = await GET(
      new Request("http://web.test/api/exports/query?start=2026-07-01&end=2026-13-01"),
    );
    expect(badDate.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
