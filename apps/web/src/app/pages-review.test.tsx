/** The month review page. */

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import ReviewPage from "./(app)/review/page";
import { withPageDefaults, type MockedApi } from "@/test/page-harness";

vi.mock("next/navigation", () => import("@/test/page-harness").then((h) => h.navigationModule()));
vi.mock("@/lib/session-cookie", () =>
  import("@/test/page-harness").then((h) => h.sessionCookieModule()),
);
vi.mock("@/lib/view-cookie", () => import("@/test/page-harness").then((h) => h.viewCookieModule()));
vi.mock("@/lib/api", () => import("@/test/page-harness").then((h) => h.apiModule()));

const { api } = await import("@/lib/api");
const mocked = api as unknown as MockedApi;
withPageDefaults(mocked);

describe("month review", () => {
  it("reads the month from the URL and offers a share link and the Markdown export", async () => {
    render(
      await ReviewPage({ searchParams: Promise.resolve({ scope: "anthropic", month: "2026-07" }) }),
    );
    expect(mocked.summary).toHaveBeenCalledWith("default", "anthropic", "2026-07");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toMatch(
      /July 2026 in review, Anthropic$/,
    );
    for (const title of [
      "Where the money went",
      "Against the plan",
      "Anomalies",
      "Needs a person",
    ]) {
      expect(screen.getByText(title)).toBeTruthy();
    }
    expect(screen.getByRole("link", { name: "Download as Markdown" }).getAttribute("href")).toBe(
      "/api/review?scope=anthropic&month=2026-07",
    );
    expect(screen.getByRole("button", { name: /Copy the link/ })).toBeTruthy();
  });

  it("falls back to the view month when the URL month is malformed", async () => {
    render(await ReviewPage({ searchParams: Promise.resolve({ month: "July" }) }));
    expect(mocked.summary).toHaveBeenLastCalledWith("default", "anthropic", "2026-08");
  });
});
