import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ writeViewCookie: vi.fn(), org: vi.fn() }));
vi.mock("@/lib/view-cookie", () => ({ writeViewCookie: mocks.writeViewCookie }));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { org: mocks.org } };
});

import { ApiError } from "@/lib/api";

import { GET } from "./route";

const params = (org: string) => ({ params: Promise.resolve({ org }) });

beforeEach(() => {
  vi.clearAllMocks();
  mocks.org.mockResolvedValue({ slug: "acme", name: "Acme", is_demo: false, role: "owner" });
});

describe("GET /o/{slug}", () => {
  it("writes the view cookie from the query and lands on next with a relative Location", async () => {
    const response = await GET(
      new Request("http://web.test/o/acme?scope=openrouter&month=2026-08&next=%2Freconcile"),
      params("acme"),
    );

    expect(mocks.org).toHaveBeenCalledWith("acme");
    expect(mocks.writeViewCookie).toHaveBeenCalledWith({
      org: "acme",
      month: "2026-08",
      scope: "openrouter",
    });
    expect(response.status).toBe(302);
    // Relative on purpose: the server's own host is not the one the browser used.
    expect(response.headers.get("location")).toBe("/reconcile");
    expect(response.headers.get("cache-control")).toBe("private, no-store, max-age=0");
  });

  it("drops an invalid month and scope, and lands on the overview without next", async () => {
    const response = await GET(
      new Request("http://web.test/o/acme?scope=nope&month=2026-13"),
      params("acme"),
    );

    expect(mocks.writeViewCookie).toHaveBeenCalledWith({ org: "acme", month: null, scope: "all" });
    expect(response.headers.get("location")).toBe("/overview");
  });

  it("carries a time frame across a scope change and ignores an unknown preset", async () => {
    await GET(
      new Request(
        "http://web.test/o/acme?scope=anthropic&from=2026-07-20&to=2026-08-14&time_frame=ytd&next=%2Freconcile",
      ),
      params("acme"),
    );
    expect(mocks.writeViewCookie).toHaveBeenLastCalledWith({
      org: "acme",
      month: "2026-08",
      scope: "anthropic",
      from: "2026-07-20",
      to: "2026-08-14",
      timeFrame: "ytd",
    });

    await GET(
      new Request("http://web.test/o/acme?from=2026-08-14&to=2026-07-20&time_frame=bogus"),
      params("acme"),
    );
    expect(mocks.writeViewCookie).toHaveBeenLastCalledWith({
      org: "acme",
      month: null,
      scope: null,
    });
  });

  it("keeps next on this origin", async () => {
    const response = await GET(
      new Request("http://web.test/o/acme?next=https%3A%2F%2Fevil.test%2Fx"),
      params("acme"),
    );

    expect(response.headers.get("location")).toBe("/overview");
  });

  it("answers a prefetch with 204 and no cookie", async () => {
    const response = await GET(
      new Request("http://web.test/o/acme", { headers: { "next-router-prefetch": "1" } }),
      params("acme"),
    );

    expect(response.status).toBe(204);
    expect(mocks.org).not.toHaveBeenCalled();
    expect(mocks.writeViewCookie).not.toHaveBeenCalled();
  });

  it("sends an unknown or foreign slug to the 404 page", async () => {
    mocks.org.mockRejectedValue(new ApiError(404, "/orgs/missing", "not found"));

    const response = await GET(new Request("http://web.test/o/missing"), params("missing"));

    expect(response.status).toBe(302);
    expect(response.headers.get("location")).toBe("/o/-missing");
    expect(mocks.writeViewCookie).not.toHaveBeenCalled();
  });
});
