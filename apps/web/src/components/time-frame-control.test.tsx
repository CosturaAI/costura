import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setViewAction } from "@/actions/view";
import { IntervalControl } from "@/components/interval-control";
import { TimeFrameControl } from "@/components/time-frame-control";

vi.mock("@/actions/view", () => ({
  setViewAction: vi.fn(),
}));

describe("time range controls", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-10-10T12:00:00Z"));
    vi.mocked(setViewAction).mockReset();
    vi.mocked(setViewAction).mockResolvedValue();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows the preset and its dates on the trigger", () => {
    render(<TimeFrameControl from="2026-09-10" to="2026-10-09" />);

    expect(screen.getByRole("button", { name: /^Time frame/ })).toHaveTextContent("Last 30 days");
    expect(screen.getByRole("button", { name: /^Time frame/ })).toHaveTextContent("Sep 10 - Oct 9");
  });

  it("shows and applies dates for a custom range", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<TimeFrameControl from="2026-06-10" to="2026-06-20" />);

    const trigger = screen.getByRole("button", { name: /^Time frame/ });
    expect(trigger).toHaveTextContent("Custom");
    expect(trigger).toHaveTextContent("Jun 10 - Jun 20");
    await user.click(trigger);

    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-06-01" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-08-31" } });
    expect(screen.getByText("92 days")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() =>
      expect(setViewAction).toHaveBeenCalledWith({
        from: "2026-06-01",
        to: "2026-08-31",
        interval: "week",
        timeFrame: null,
      }),
    );
  });

  it("blocks a custom range that ends before it starts", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<TimeFrameControl from="2026-06-10" to="2026-06-20" />);
    await user.click(screen.getByRole("button", { name: /^Time frame/ }));

    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-07-01" } });

    expect(screen.getByText("The start date is after the end date.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply" })).toBeDisabled();
  });

  it("applies a calendar preset in one click", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<TimeFrameControl from="2026-09-01" to="2026-09-30" />);
    await user.click(screen.getByRole("button", { name: /^Time frame/ }));

    expect(
      within(screen.getByRole("dialog")).getByRole("button", { name: /Last month/ }),
    ).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: /This quarter/ }));

    await waitFor(() =>
      expect(setViewAction).toHaveBeenCalledWith({
        from: "2026-10-01",
        to: "2026-10-10",
        interval: "day",
        timeFrame: "quarter",
      }),
    );
  });

  it("switches a last-N window between complete days and including today", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<TimeFrameControl from="2026-10-03" to="2026-10-09" />);
    await user.click(screen.getByRole("button", { name: /^Time frame/ }));

    expect(screen.getByRole("button", { name: "7 days" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/Ends yesterday, Oct 9/)).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: "Include today" }));

    await waitFor(() =>
      expect(setViewAction).toHaveBeenCalledWith({
        from: "2026-10-04",
        to: "2026-10-10",
        interval: "day",
        timeFrame: "rolling_7_days",
      }),
    );
  });

  it("labels a window that includes today", () => {
    render(<TimeFrameControl from="2026-09-11" to="2026-10-10" />);

    expect(screen.getByRole("button", { name: /^Time frame/ })).toHaveTextContent(
      "Last 30 days + today",
    );
  });

  it("renders the selected interval", () => {
    render(<IntervalControl interval="week" />);

    expect(screen.getByRole("combobox", { name: /^Interval/ })).toHaveTextContent("Weekly");
  });
});
