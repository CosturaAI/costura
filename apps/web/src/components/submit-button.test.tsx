import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SubmitButton } from "./submit-button";

describe("SubmitButton", () => {
  it("keeps focus and ignores clicks while its form posts", () => {
    const submit = vi.fn((event: SubmitEvent) => event.preventDefault());
    const { rerender } = render(
      <form onSubmit={(event) => submit(event.nativeEvent as SubmitEvent)}>
        <SubmitButton pending>Save</SubmitButton>
      </form>,
    );
    const button = screen.getByRole("button", { name: "Save" });
    button.focus();
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).not.toBeDisabled();
    fireEvent.click(button);
    expect(submit).not.toHaveBeenCalled();
    expect(button).toHaveFocus();

    rerender(
      <form onSubmit={(event) => submit(event.nativeEvent as SubmitEvent)}>
        <SubmitButton pending={false}>Save</SubmitButton>
      </form>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(submit).toHaveBeenCalledTimes(1);
  });
});
