import userEvent from "@testing-library/user-event";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { QuerySelect } from "./query-select";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => "/spend",
  useSearchParams: () => new URLSearchParams("month=2026-10&by=provider"),
}));

describe("QuerySelect", () => {
  beforeEach(() => push.mockReset());

  it("preserves existing parameters and replaces its own", async () => {
    const user = userEvent.setup();
    render(
      <QuerySelect
        name="by"
        value="provider"
        label="Group by"
        options={[
          { value: "provider", label: "Provider" },
          { value: "model", label: "Model" },
        ]}
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Group by" }));
    await user.click(screen.getByRole("option", { name: "Model" }));

    expect(push).toHaveBeenCalledWith("/spend?month=2026-10&by=model");
  });

  it("does not navigate when the selected value is unchanged", async () => {
    const user = userEvent.setup();
    render(
      <QuerySelect
        name="by"
        value="provider"
        label="Group by"
        options={[{ value: "provider", label: "Provider" }]}
      />,
    );
    await user.click(screen.getByRole("combobox", { name: "Group by" }));
    await user.click(screen.getByRole("option", { name: "Provider" }));
    expect(push).not.toHaveBeenCalled();
  });
});
