import userEvent from "@testing-library/user-event";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CopyButton } from "./copy-button";

describe("CopyButton", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("copies, confirms, and restores its label", async () => {
    vi.useFakeTimers();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    render(<CopyButton value="account-123" label="Copy account" />);

    fireEvent.click(screen.getByRole("button", { name: "Copy account" }));
    await act(async () => Promise.resolve());
    expect(writeText).toHaveBeenCalledWith("account-123");
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();

    act(() => vi.advanceTimersByTime(2000));
    expect(screen.getByRole("button", { name: "Copy account" })).toBeInTheDocument();
  });

  it("keeps the original label when clipboard access fails", async () => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    });
    await userEvent.click(
      render(<CopyButton value="secret" label="Copy secret" />).getByRole("button"),
    );
    expect(screen.getByRole("button", { name: "Copy secret" })).toBeInTheDocument();
  });
});
