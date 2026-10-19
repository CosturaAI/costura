import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { QueryChips } from "@/components/query-chips";

const push = vi.fn();
let searchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  usePathname: () => "/explore",
  useRouter: () => ({ push }),
  useSearchParams: () => searchParams,
}));

beforeEach(() => {
  push.mockClear();
  searchParams = new URLSearchParams();
  window.history.replaceState({}, "", "/explore");
});

describe("QueryChips", () => {
  it("composes rapid changes from separate controls", () => {
    render(
      <>
        <QueryChips
          name="display"
          value="total"
          label="Display"
          options={[
            { value: "total", label: "Total" },
            { value: "delta", label: "Delta" },
          ]}
        />
        <QueryChips
          name="top"
          value="25"
          label="Rows"
          options={[
            { value: "10", label: "Top 10" },
            { value: "25", label: "Top 25" },
          ]}
        />
      </>,
    );

    fireEvent.click(screen.getByRole("link", { name: "Delta" }));
    fireEvent.click(screen.getByRole("link", { name: "Top 10" }));

    expect(push).toHaveBeenNthCalledWith(1, "/explore?display=delta");
    expect(push).toHaveBeenNthCalledWith(2, "/explore?display=delta&top=10");
  });
});
