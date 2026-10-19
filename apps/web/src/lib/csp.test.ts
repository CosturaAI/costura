import { describe, expect, it } from "vitest";

import { contentSecurityPolicy, createNonce } from "./csp";

const directive = (policy: string, name: string) =>
  policy.split("; ").find((part) => part.startsWith(`${name} `));

describe("contentSecurityPolicy", () => {
  it("allows only nonced scripts in production", () => {
    const policy = contentSecurityPolicy("abc123", true);
    expect(directive(policy, "script-src")).toBe(
      "script-src 'self' 'nonce-abc123' 'strict-dynamic'",
    );
    expect(policy).not.toMatch(/script-src[^;]*'unsafe-inline'/);
    expect(policy).not.toContain("'unsafe-eval'");
    expect(policy).toContain("upgrade-insecure-requests");
    expect(policy).toContain("frame-ancestors 'none'");
    expect(policy).toContain("object-src 'none'");
  });

  it("adds eval for the dev server and no upgrade on plain http", () => {
    const policy = contentSecurityPolicy("abc123", false);
    expect(directive(policy, "script-src")).toContain("'unsafe-eval'");
    expect(policy).not.toContain("upgrade-insecure-requests");
  });
});

describe("createNonce", () => {
  it("is base64 of 16 bytes and differs per call", () => {
    const first = createNonce();
    expect(first).toMatch(/^[A-Za-z0-9+/]{22}==$/);
    expect(createNonce()).not.toBe(first);
  });
});
