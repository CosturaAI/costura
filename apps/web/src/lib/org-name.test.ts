import { describe, expect, it } from "vitest";

import { isValidSlug, nextSlug, slugify, suggestOrgName } from "./org-name";

describe("suggestOrgName", () => {
  it("capitalizes the first label of a company domain", () => {
    expect(suggestOrgName("jane@acme.com")).toBe("Acme");
    expect(suggestOrgName("Jane@ACME.IO")).toBe("Acme");
    expect(suggestOrgName("jane@acme.co.uk")).toBe("Acme");
    expect(suggestOrgName("jane@mail.acme.co.uk")).toBe("Mail");
  });

  it("names the organization after the local part on public mail domains", () => {
    expect(suggestOrgName("jane@gmail.com")).toBe("Jane's organization");
    expect(suggestOrgName("jane.doe@googlemail.com")).toBe("Jane.doe's organization");
    expect(suggestOrgName("jane@outlook.com")).toBe("Jane's organization");
    expect(suggestOrgName("jane@hotmail.com")).toBe("Jane's organization");
    expect(suggestOrgName("jane@live.com")).toBe("Jane's organization");
    expect(suggestOrgName("jane@yahoo.com")).toBe("Jane's organization");
    expect(suggestOrgName("jane@icloud.com")).toBe("Jane's organization");
    expect(suggestOrgName("jane@me.com")).toBe("Jane's organization");
    expect(suggestOrgName("jane@proton.me")).toBe("Jane's organization");
    expect(suggestOrgName("jane@protonmail.com")).toBe("Jane's organization");
    expect(suggestOrgName("jane@aol.com")).toBe("Jane's organization");
  });

  it("falls back when the address has no domain", () => {
    expect(suggestOrgName("jane")).toBe("Jane's organization");
    expect(suggestOrgName("")).toBe("My's organization");
  });
});

describe("slugify", () => {
  it("lowercases and joins runs of other characters with one hyphen", () => {
    expect(slugify("Acme")).toBe("acme");
    expect(slugify("Acme Corp.")).toBe("acme-corp");
    expect(slugify("  Jane's   organization ")).toBe("jane-s-organization");
    expect(slugify("Ünïcödé Ltd")).toBe("unicode-ltd");
  });

  it("trims hyphens, drops a leading hyphen and caps at 63 characters", () => {
    expect(slugify("--acme--")).toBe("acme");
    expect(slugify("-")).toBe("");
    const long = slugify("a".repeat(70));
    expect(long).toHaveLength(63);
    expect(slugify(`${"a".repeat(62)}-b`)).toBe("a".repeat(62));
  });
});

describe("nextSlug", () => {
  it("appends -2, then increments a trailing counter", () => {
    expect(nextSlug("acme")).toBe("acme-2");
    expect(nextSlug("acme-2")).toBe("acme-3");
    expect(nextSlug("acme-9")).toBe("acme-10");
    expect(nextSlug("acme-v2-2")).toBe("acme-v2-3");
  });

  it("keeps the 63-character limit", () => {
    const next = nextSlug("a".repeat(63));
    expect(next).toHaveLength(63);
    expect(next.endsWith("-2")).toBe(true);
  });
});

describe("isValidSlug", () => {
  it("follows the API pattern", () => {
    expect(isValidSlug("acme")).toBe(true);
    expect(isValidSlug("a1")).toBe(true);
    expect(isValidSlug("a")).toBe(false);
    expect(isValidSlug("-acme")).toBe(false);
    expect(isValidSlug("Acme")).toBe(false);
    expect(isValidSlug("a".repeat(63))).toBe(true);
    expect(isValidSlug("a".repeat(64))).toBe(false);
  });
});
