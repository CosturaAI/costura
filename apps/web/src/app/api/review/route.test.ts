import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  readViewCookie: vi.fn(),
  loadReview: vi.fn(),
  org: vi.fn(),
}));
vi.mock("@/lib/view-cookie", () => ({ readViewCookie: mocks.readViewCookie }));
vi.mock("@/lib/api", () => ({ api: { org: mocks.org } }));
vi.mock("@/lib/review", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/review")>()),
  loadReview: mocks.loadReview,
}));

import * as fx from "@/test/fixtures";

import { GET } from "./route";

beforeEach(() => {
  vi.clearAllMocks();
  mocks.readViewCookie.mockResolvedValue({ org: "acme", month: "2026-07", scope: "all" });
  mocks.org.mockResolvedValue({ ...fx.organization, name: "Acme" });
  mocks.loadReview.mockResolvedValue({
    scope: "all",
    month: "2026-08",
    summary: fx.summary,
    projections: null,
    budgets: null,
    movers: null,
    anomalies: null,
    signals: null,
  });
});

describe("month review route", () => {
  it("returns the review as a private Markdown attachment", async () => {
    const response = await GET(new Request("http://web.test/api/review?scope=all&month=2026-08"));
    expect(response.status).toBe(200);
    expect(mocks.loadReview).toHaveBeenCalledWith("acme", "all", "2026-08");
    expect(response.headers.get("content-type")).toBe("text/markdown; charset=utf-8");
    expect(response.headers.get("cache-control")).toBe("private, no-store, max-age=0");
    expect(response.headers.get("content-disposition")).toBe(
      'attachment; filename="costura-acme-all-2026-08.md"',
    );
    const body = await response.text();
    expect(body.startsWith("# Acme: August 2026 in review, all providers\n")).toBe(true);
    expect(body).toContain("## Where the money went");
  });

  it("refuses a malformed month and a missing organization", async () => {
    const bad = await GET(new Request("http://web.test/api/review?month=2026-8"));
    expect(bad.status).toBe(400);
    mocks.readViewCookie.mockResolvedValue(null);
    const none = await GET(new Request("http://web.test/api/review?month=2026-08"));
    expect(none.status).toBe(404);
    expect(mocks.loadReview).not.toHaveBeenCalled();
  });

  it("answers 502 when the summary cannot be read", async () => {
    mocks.loadReview.mockRejectedValue(new Error("down"));
    const response = await GET(new Request("http://web.test/api/review?month=2026-08"));
    expect(response.status).toBe(502);
  });
});
