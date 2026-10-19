import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";

import { ApiDown } from "./api-down";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

describe("ApiDown", () => {
  it("blames the data service only when it did not answer", () => {
    render(<ApiDown error={new Error("fetch failed")} reset={() => {}} />);
    expect(screen.getByText("Costura did not answer")).toBeInTheDocument();
  });

  it("names an API 5xx as the data service", () => {
    render(<ApiDown error={new ApiError(503, "/orgs/a", "down")} reset={() => {}} />);
    expect(screen.getByText("Costura did not answer")).toBeInTheDocument();
  });

  it("shows a neutral title and the digest for any other error", () => {
    const error = Object.assign(new Error("An error occurred in the Server Components render."), {
      digest: "4242",
    });
    render(<ApiDown error={error} reset={() => {}} />);
    expect(screen.getByText("This page could not load")).toBeInTheDocument();
    expect(screen.getByText("Reference 4242")).toBeInTheDocument();
  });

  it("names the API error code under Technical details and copies it", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    const error = new ApiError(409, "/orgs/a", "slug taken", null, "duplicate_slug");
    render(<ApiDown error={error} reset={() => {}} />);
    expect(screen.getByText("duplicate_slug")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Copy details" }));
    await act(async () => Promise.resolve());
    const copied = writeText.mock.calls[0]![0] as string;
    expect(copied).toContain("- Route: `/orgs/a`");
    expect(copied).toContain("- Status: 409");
    expect(copied).toContain("- Code: `duplicate_slug`");
    expect(copied).toContain("slug taken");
    expect(copied).not.toContain("Digest");
  });

  it("copies the digest and message of a render error without a code line", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    const error = Object.assign(new Error("render failed"), { digest: "4242" });
    render(<ApiDown error={error} reset={() => {}} />);
    expect(screen.queryByText(/Error code/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Copy details" }));
    await act(async () => Promise.resolve());
    const copied = writeText.mock.calls[0]![0] as string;
    expect(copied).toContain("- Digest: 4242");
    expect(copied).toContain("render failed");
    expect(copied).not.toContain("Route");
    expect(copied).not.toContain("Code");
  });

  it("refreshes the route and resets the boundary on Retry", () => {
    const reset = vi.fn();
    render(<ApiDown error={new Error("boom")} reset={reset} />);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(reset).toHaveBeenCalledTimes(1);
  });
});
