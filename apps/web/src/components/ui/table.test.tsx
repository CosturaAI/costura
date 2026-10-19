import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Table, TableBody, TableCell, TableRow } from "./table";

function renderTable() {
  const { container } = render(
    <Table>
      <TableBody>
        <TableRow>
          <TableCell>last owner</TableCell>
        </TableRow>
      </TableBody>
    </Table>,
  );
  return container.querySelector<HTMLElement>('[data-slot="table-container"]')!;
}

function widths(scrollWidth: number, clientWidth: number) {
  vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockReturnValue(scrollWidth);
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(clientWidth);
}

describe("Table", () => {
  afterEach(() => vi.restoreAllMocks());

  it("lets the keyboard reach a container that scrolls sideways", () => {
    widths(640, 358);
    expect(renderTable()).toHaveAttribute("tabindex", "0");
  });

  it("adds no tab stop when the table fits", () => {
    widths(358, 358);
    expect(renderTable()).not.toHaveAttribute("tabindex");
  });

  it("renders no container when scrolling is off", () => {
    const { container } = render(<Table scroll={false} />);
    expect(container.querySelector('[data-slot="table-container"]')).toBeNull();
  });
});
