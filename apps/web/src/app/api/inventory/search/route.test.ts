import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ readSessionToken: vi.fn(), readViewCookie: vi.fn() }));
vi.mock("@/lib/session-cookie", () => ({ readSessionToken: mocks.readSessionToken }));
vi.mock("@/lib/view-cookie", () => ({ readViewCookie: mocks.readViewCookie }));

import { GET } from "./route";

const fetchMock = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  mocks.readSessionToken.mockResolvedValue("session-token");
  mocks.readViewCookie.mockResolvedValue({ org: "acme", month: "2026-07", scope: "openai" });
  vi.stubGlobal("fetch", fetchMock);
  vi.stubEnv("COSTURA_API_URL", "http://api.internal/");
  fetchMock.mockResolvedValue(Response.json({ items: [] }));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("inventory search route", () => {
  it("forwards the view's organization and provider, and only the query", async () => {
    const controller = new AbortController();
    const response = await GET(
      new Request("http://web.test/api/inventory/search?q=ada%25_&limit=5&org=other&provider=all", {
        signal: controller.signal,
      }),
    );

    const [url, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(url.origin).toBe("http://api.internal");
    expect(url.pathname).toBe("/api/v1/orgs/acme/providers/openai/inventory/search");
    expect(Object.fromEntries(url.searchParams)).toEqual({ q: "ada%_", limit: "5" });
    expect(new Headers(init.headers).get("authorization")).toBe("Bearer session-token");
    expect(init.cache).toBe("no-store");
    expect(init.signal).toBeInstanceOf(AbortSignal);
    controller.abort();
    expect(init.signal?.aborted).toBe(true);
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("private, no-store, max-age=0");
    expect(await response.json()).toEqual({ items: [] });
  });

  it("uses every provider when the view scope is all, without a session bearer", async () => {
    mocks.readSessionToken.mockResolvedValue(null);
    mocks.readViewCookie.mockResolvedValue({ org: "demo", month: "2026-07", scope: "all" });

    await GET(new Request("http://web.test/api/inventory/search?q=ana"));

    const [url, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(url.pathname).toBe("/api/v1/orgs/demo/providers/all/inventory/search");
    expect(url.searchParams.get("q")).toBe("ana");
    expect(url.searchParams.has("limit")).toBe(false);
    expect(new Headers(init.headers).has("authorization")).toBe(false);
  });

  it("answers 404 without a view and 400 for a short, long or oversized query", async () => {
    mocks.readViewCookie.mockResolvedValue(null);
    const missing = await GET(new Request("http://web.test/api/inventory/search?q=ada"));
    expect(missing.status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();

    mocks.readViewCookie.mockResolvedValue({ org: "acme", month: "2026-07", scope: "all" });
    for (const q of ["a", "  a", "x".repeat(101)]) {
      const response = await GET(
        new Request(`http://web.test/api/inventory/search?q=${encodeURIComponent(q)}`),
      );
      expect(response.status).toBe(400);
    }
    const limit = await GET(new Request("http://web.test/api/inventory/search?q=ada&limit=9"));
    expect(limit.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
