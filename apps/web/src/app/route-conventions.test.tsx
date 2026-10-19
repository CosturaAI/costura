/** Next.js convention files: loading skeletons, the error boundary, the 404 page and the proxy. */

import type { ComponentType } from "react";
import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { proxy } from "@/proxy";

import ScopeError from "./(app)/error";
import MissingOrganization from "./o/-missing/page";

const notFound = vi.fn(() => {
  throw new Error("NEXT_NOT_FOUND");
});
vi.mock("next/navigation", () => ({
  notFound: () => notFound(),
  useRouter: () => ({ refresh: vi.fn() }),
}));

const loaders = import.meta.glob("./**/loading.tsx", { eager: true }) as Record<
  string,
  { default: ComponentType }
>;

afterEach(() => {
  cleanup();
});

describe("loading skeletons", () => {
  it("exist for the app pages", () => {
    expect(Object.keys(loaders).length).toBeGreaterThan(10);
  });

  it.each(Object.entries(loaders))("%s announces a loading region", (_path, module) => {
    const Loading = module.default;
    render(<Loading />);
    expect(screen.getAllByRole("status", { name: "Loading" }).length).toBeGreaterThan(0);
  });
});

describe("error and missing pages", () => {
  it("renders the API-down card with a retry", () => {
    const reset = vi.fn();
    render(<ScopeError error={new TypeError("fetch failed")} reset={reset} />);
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(reset).toHaveBeenCalled();
  });

  it("answers an unknown organization with the 404 page", () => {
    expect(() => MissingOrganization()).toThrow("NEXT_NOT_FOUND");
    expect(notFound).toHaveBeenCalled();
  });
});

describe("proxy", () => {
  const request = (path: string) => new NextRequest(new URL(path, "http://localhost:3000"));

  it("lets a page of the app through", () => {
    const response = proxy(request("/overview"));
    expect(response.headers.get("location")).toBeNull();
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("sends a fresh nonce to the page and the browser", () => {
    const first = proxy(request("/overview"));
    const policy = first.headers.get("content-security-policy") ?? "";
    const nonce = /'nonce-([^']+)'/.exec(policy)?.[1];
    expect(nonce).toBeTruthy();
    expect(first.headers.get("x-middleware-request-x-nonce")).toBe(nonce);
    expect(first.headers.get("x-middleware-request-content-security-policy")).toBe(policy);
    const second = proxy(request("/overview")).headers.get("content-security-policy");
    expect(second).not.toBe(policy);
  });
});

describe("page titles", () => {
  const sources = import.meta.glob("./**/page.tsx", {
    query: "?raw",
    import: "default",
    eager: true,
  }) as Record<string, string>;
  const redirectsOnly = ["./page.tsx", "./(app)/settings/page.tsx"];

  it("gives every rendered page its own tab title", () => {
    const untitled = Object.entries(sources)
      .filter(([path]) => !redirectsOnly.includes(path) && !path.startsWith("./o/"))
      .filter(
        ([, source]) =>
          !/export const metadata: Metadata = \{ title: "[^"]+" \}/.test(source) &&
          !/export const generateMetadata = entityMetadata\("[a-z_]+", "[^"]+"/.test(source) &&
          !/export async function generateMetadata\(/.test(source),
      )
      .map(([path]) => path);
    expect(untitled).toEqual([]);
  });
});
