import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as fx from "@/test/fixtures";

import { AlertsBell, unreadByKindSentence } from "./alerts-bell";

const actions = vi.hoisted(() => ({
  get: vi.fn(),
  mark: vi.fn(),
  markSignal: vi.fn(),
  settings: vi.fn(),
}));
vi.mock("@/actions/alerts", () => ({
  getAlertsAction: actions.get,
  markAllReadAction: actions.mark,
  markSignalReadAction: actions.markSignal,
  setAlertSettingsAction: actions.settings,
}));

describe("AlertsBell", () => {
  beforeEach(() => {
    actions.get.mockReset().mockResolvedValue({ alerts: fx.alerts, error: null });
    actions.mark.mockReset().mockResolvedValue({ alerts: fx.alerts, error: null });
  });
  afterEach(() => vi.useRealTimers());

  it("leaves focus where it is on mount", () => {
    render(<AlertsBell initial={fx.alerts} canWrite />);
    expect(document.activeElement).toBe(document.body);
  });

  it("moves focus into the dialog on open and back to the bell on Escape", () => {
    render(<AlertsBell initial={fx.alerts} canWrite />);
    const bell = screen.getByRole("button", { name: /^Alerts/ });
    bell.focus();

    fireEvent.click(bell);
    const dialog = screen.getByRole("dialog", { name: "Alerts" });
    expect(dialog.contains(document.activeElement)).toBe(true);
    expect(document.activeElement).not.toBe(bell);

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.activeElement).toBe(bell);
  });

  it("polls opted-in alerts and clears the timer on unmount", async () => {
    vi.useFakeTimers();
    const { unmount } = render(<AlertsBell initial={fx.alerts} canWrite />);
    act(() => vi.advanceTimersByTime(60_000));
    await act(async () => Promise.resolve());
    expect(actions.get).toHaveBeenCalledWith();

    const calls = actions.get.mock.calls.length;
    unmount();
    act(() => vi.advanceTimersByTime(60_000));
    expect(actions.get).toHaveBeenCalledTimes(calls);
  });

  it("skips the poll while the tab is hidden and refreshes when it comes back", async () => {
    vi.useFakeTimers();
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    const { unmount } = render(<AlertsBell initial={fx.alerts} canWrite />);
    act(() => vi.advanceTimersByTime(120_000));
    await act(async () => Promise.resolve());
    expect(actions.get).not.toHaveBeenCalled();

    hidden.mockReturnValue(false);
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await act(async () => Promise.resolve());
    expect(actions.get).toHaveBeenCalledTimes(1);
    unmount();
    hidden.mockRestore();
  });

  it("shows refresh failures without replacing the current inbox", async () => {
    actions.get.mockResolvedValue({ alerts: fx.alerts, error: "provider unavailable" });
    render(<AlertsBell initial={fx.alerts} canWrite />);
    fireEvent.click(screen.getByRole("button", { name: /^Alerts/ }));
    await waitFor(() => expect(screen.getByText("provider unavailable")).toBeInTheDocument());
  });

  it("lists unread budget alerts and key gaps and marks one read when it is opened", async () => {
    actions.get.mockResolvedValue({ alerts: fx.mixedAlerts, error: null });
    actions.markSignal.mockReset().mockResolvedValue(undefined);
    render(<AlertsBell initial={fx.mixedAlerts} canWrite />);
    fireEvent.click(screen.getByRole("button", { name: "Alerts, 4 unread" }));
    const dialog = screen.getByRole("dialog", { name: "Alerts" });

    expect(screen.getByText("4 unread: 2 anomalies, 1 budget, 1 no owner")).toBeInTheDocument();
    const totals = screen.getAllByRole("link", { name: "organization total" });
    expect(totals.map((link) => link.getAttribute("href"))).toContain("/budgets");
    expect(dialog).toHaveTextContent("projected over the budget");
    const gap = screen.getByRole("link", { name: "router-prod" });
    expect(dialog).toHaveTextContent("no owner in the provider inventory or in Costura");

    fireEvent.click(gap);
    expect(actions.markSignal).toHaveBeenCalledWith({
      kind: "no_owner",
      provider: "openrouter",
      read_reference: "orkey_hash_1",
    });
    expect(screen.getByRole("button", { name: "Alerts, 3 unread" })).toBeInTheDocument();
  });

  it("names each unread kind in queue order", () => {
    expect(unreadByKindSentence({ new_key: 2, anomaly: 1, budget: 3 })).toBe(
      "1 anomaly, 3 budgets, 2 new key",
    );
    expect(unreadByKindSentence({})).toBe("");
  });
});
