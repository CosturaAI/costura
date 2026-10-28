import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FilterEditor } from "./filter-editor";

const push = vi.fn();
let searchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  usePathname: () => "/explore",
  useRouter: () => ({ push }),
  useSearchParams: () => searchParams,
}));

const dimensions = [
  { value: "model", label: "Model" },
  { value: "workspace", label: "Workspace" },
];

beforeEach(() => {
  push.mockClear();
  searchParams = new URLSearchParams();
});

describe("Explore filter editor", () => {
  it("offers every operator and replaces only the selected dimension", () => {
    searchParams = new URLSearchParams("by=model&f=model%3Ais%3Agpt-4o&f=workspace%3Ais%3ABackend");
    render(
      <FilterEditor
        dimensions={dimensions}
        defaultDimension="model"
        valueOptions={{ model: [{ value: "gpt-5", label: "GPT-5" }] }}
      />,
    );

    expect(
      within(screen.getByLabelText("Operator"))
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual([
      "is",
      "is not",
      "is one of",
      "is not one of",
      "contains",
      "does not contain",
      "exists",
      "does not exist",
    ]);

    fireEvent.change(screen.getByLabelText("Operator"), { target: { value: "is_not" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Value" }), {
      target: { value: "GPT-5" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add filter" }));

    const url = new URL(push.mock.calls[0]![0], "http://web.test");
    expect(url.searchParams.get("by")).toBe("model");
    expect(url.searchParams.getAll("f")).toEqual(["workspace:is:Backend", "model:is_not:gpt-5"]);
  });

  it("joins a value to the dimension's clause of the same kind", () => {
    searchParams = new URLSearchParams("f=model%3Ais%3Agpt-4o");
    render(
      <FilterEditor
        dimensions={dimensions}
        defaultDimension="model"
        valueOptions={{ model: [{ value: "gpt-5", label: "GPT-5" }] }}
      />,
    );

    fireEvent.change(screen.getByRole("combobox", { name: "Value" }), {
      target: { value: "GPT-5" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add filter" }));

    const url = new URL(push.mock.calls[0]![0], "http://web.test");
    expect(url.searchParams.getAll("f")).toEqual(["model:one_of:gpt-4o,gpt-5"]);
  });

  it("refuses a name the full value list does not hold", () => {
    render(
      <FilterEditor
        dimensions={dimensions}
        defaultDimension="workspace"
        valueOptions={{ workspace: [{ value: "ws_1", label: "Backend" }] }}
        exhaustive={["workspace"]}
      />,
    );

    fireEvent.change(screen.getByRole("combobox", { name: "Value" }), {
      target: { value: "Frontend" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add filter" }));

    expect(push).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "No workspace named Frontend in this period.",
    );

    fireEvent.change(screen.getByRole("combobox", { name: "Value" }), {
      target: { value: "ws_1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add filter" }));
    const url = new URL(push.mock.calls[0]![0], "http://web.test");
    expect(url.searchParams.getAll("f")).toEqual(["workspace:is:ws_1"]);
  });

  it("adds value-free existence clauses", () => {
    render(<FilterEditor dimensions={dimensions} defaultDimension="model" valueOptions={{}} />);

    fireEvent.change(screen.getByLabelText("Dimension"), { target: { value: "workspace" } });
    fireEvent.change(screen.getByLabelText("Operator"), { target: { value: "not_exists" } });
    expect(screen.getByRole("textbox", { name: "Value" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Add filter" }));

    const url = new URL(push.mock.calls[0]![0], "http://web.test");
    expect(url.searchParams.getAll("f")).toEqual(["workspace:not_exists:"]);
  });
});
