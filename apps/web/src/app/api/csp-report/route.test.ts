import { describe, expect, it, vi } from "vitest";

import { summarizeCspReport } from "@/lib/csp";

import { POST } from "./route";

describe("csp report route", () => {
  it("logs the directive, the blocked origin and the page path without queries", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const response = await POST(
      new Request("http://localhost/api/csp-report", {
        method: "POST",
        body: JSON.stringify({
          "csp-report": {
            "effective-directive": "script-src-elem",
            "blocked-uri": "https://evil.example/x.js?token=secret",
            "document-uri": "http://localhost/overview?org=acme",
          },
        }),
      }),
    );
    expect(response.status).toBe(204);
    expect(warn).toHaveBeenCalledWith(
      "csp violation script-src-elem blocked https://evil.example on /overview",
    );
    warn.mockRestore();
  });

  it("ignores a body that is not a report", () => {
    expect(summarizeCspReport({ other: 1 })).toBeNull();
  });
});
