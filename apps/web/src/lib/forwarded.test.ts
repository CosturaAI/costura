import { beforeEach, describe, expect, it, vi } from "vitest";

let incoming: Headers | Error = new Headers();
vi.mock("next/headers", () => ({
  headers: async () => {
    if (incoming instanceof Error) throw incoming;
    return incoming;
  },
}));

import { forwardedRequestHeaders } from "./forwarded";

beforeEach(() => {
  incoming = new Headers();
});

describe("forwarded request headers", () => {
  it("preserves base headers and forwards address and request id", async () => {
    incoming = new Headers({ "x-forwarded-for": "203.0.113.7", "x-request-id": "req-1" });
    const result = await forwardedRequestHeaders({ accept: "application/json" });
    expect(Object.fromEntries(result)).toEqual({
      accept: "application/json",
      "x-forwarded-for": "203.0.113.7",
      "x-request-id": "req-1",
    });
  });

  it("does not overwrite with absent values", async () => {
    const result = await forwardedRequestHeaders({ "x-request-id": "existing" });
    expect(result.get("x-request-id")).toBe("existing");
    expect(result.has("x-forwarded-for")).toBe(false);
  });

  it("returns base headers outside a request", async () => {
    incoming = new Error("outside request scope");
    const result = await forwardedRequestHeaders({ accept: "text/csv" });
    expect(Object.fromEntries(result)).toEqual({ accept: "text/csv" });
  });
});
