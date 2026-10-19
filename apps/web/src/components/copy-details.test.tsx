import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CopyDetails, detailsMarkdown } from "./copy-details";

const NOW = new Date("2026-10-18T12:00:00.000Z");

describe("detailsMarkdown", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("lists every field it was given and fences the message", () => {
    vi.stubEnv("NEXT_PUBLIC_COSTURA_VERSION", "1.2.3");
    const text = detailsMarkdown(
      {
        route: "/orgs/acme",
        job: "Cost report",
        status: 503,
        code: "provider_unavailable",
        message: "line one\nline two",
        digest: "4242",
      },
      NOW,
    );
    expect(text).toBe(
      [
        "## Costura error",
        "- Route: `/orgs/acme`",
        "- Job: Cost report",
        "- Status: 503",
        "- Code: `provider_unavailable`",
        "- Digest: 4242",
        "- Version: 1.2.3",
        "- Time: 2026-10-18T12:00:00.000Z",
        "",
        "```",
        "line one",
        "line two",
        "```",
        "",
      ].join("\n"),
    );
  });

  it("omits the lines it has no value for, including the version outside a build", () => {
    vi.stubEnv("NEXT_PUBLIC_COSTURA_VERSION", "");
    const text = detailsMarkdown({ message: "boom", status: null, code: null, digest: null }, NOW);
    expect(text).toBe("## Costura error\n- Time: 2026-10-18T12:00:00.000Z\n\n```\nboom\n```\n");
  });

  it("keeps a textual status such as a run status", () => {
    expect(detailsMarkdown({ message: "x", status: "failed" }, NOW)).toContain("- Status: failed");
  });
});

describe("CopyDetails", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("copies the Markdown, announces Copied, and restores its label after two seconds", async () => {
    vi.useFakeTimers();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    render(<CopyDetails details={{ message: "boom", status: 500 }} />);

    expect(screen.getByRole("status")).toHaveTextContent("");
    fireEvent.click(screen.getByRole("button", { name: "Copy details" }));
    await act(async () => Promise.resolve());
    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText.mock.calls[0]![0]).toContain("- Status: 500");
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Copied");

    act(() => vi.advanceTimersByTime(2000));
    expect(screen.getByRole("button", { name: "Copy details" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("");
  });

  it("says so when the clipboard refuses, and a second click restarts the timer", async () => {
    vi.useFakeTimers();
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    render(<CopyDetails details={{ message: "boom" }} />);

    fireEvent.click(screen.getByRole("button", { name: "Copy details" }));
    await act(async () => Promise.resolve());
    expect(screen.getByRole("button", { name: "Could not copy" })).toBeInTheDocument();

    act(() => vi.advanceTimersByTime(1000));
    fireEvent.click(screen.getByRole("button", { name: "Could not copy" }));
    await act(async () => Promise.resolve());
    act(() => vi.advanceTimersByTime(1500));
    expect(screen.getByRole("button", { name: "Could not copy" })).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(500));
    expect(screen.getByRole("button", { name: "Copy details" })).toBeInTheDocument();
  });

  it("unmounts cleanly before any click", () => {
    const { unmount } = render(<CopyDetails details={{ message: "boom" }} />);
    unmount();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("clears a pending timer when it unmounts", async () => {
    vi.useFakeTimers();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    const { unmount } = render(<CopyDetails details={{ message: "boom" }} />);
    fireEvent.click(screen.getByRole("button", { name: "Copy details" }));
    await act(async () => Promise.resolve());
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
