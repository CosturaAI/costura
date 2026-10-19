import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DataTable, type Column } from "@/components/data-table";
import { useMinWidth } from "@/lib/use-min-width";
import { ViewportProvider } from "@/lib/viewport";
import { parseViewportWidth } from "@/lib/viewport-cookie";

type Listener = () => void;

/** A `matchMedia` whose answer the test changes, firing `change` like a resized window. */
function mockMatchMedia(initialWidth: number) {
  let width = initialWidth;
  const listeners = new Set<{ min: number; fn: Listener; query: { matches: boolean } }>();
  window.matchMedia = vi.fn((media: string) => {
    const min = Number(/min-width: (\d+)px/.exec(media)?.[1] ?? 0);
    const query = {
      get matches() {
        return width >= min;
      },
      addEventListener: (_: string, fn: Listener) => listeners.add({ min, fn, query }),
      removeEventListener: () => undefined,
    };
    return query as unknown as MediaQueryList;
  });
  return {
    resize(next: number) {
      width = next;
      Object.defineProperty(window, "innerWidth", { value: next, configurable: true });
      listeners.forEach((listener) => listener.fn());
    },
  };
}

function Probe() {
  return <p>{useMinWidth(768) ? "wide" : "narrow"}</p>;
}

const columns: Column<{ id: string }>[] = [
  { id: "name", header: "Name", render: (row) => row.id, priority: "primary" },
];

afterEach(() => {
  document.cookie = "costura_vw=; max-age=0; path=/";
});

describe("useMinWidth", () => {
  it("follows matchMedia change events and records the width for the next server render", () => {
    const media = mockMatchMedia(1280);
    render(<Probe />);
    expect(screen.getByText("wide")).toBeInTheDocument();
    act(() => media.resize(390));
    expect(screen.getByText("narrow")).toBeInTheDocument();
    expect(document.cookie).toContain("costura_vw=390");
    act(() => media.resize(1024));
    expect(screen.getByText("wide")).toBeInTheDocument();
  });

  it("starts from the width the server knew, so a phone never paints the desktop table", () => {
    // No matchMedia: only the server's width decides, as on the first paint.
    const original = window.matchMedia;
    // @ts-expect-error the first render happens before any media query exists
    window.matchMedia = undefined;
    render(
      <ViewportProvider width={390}>
        <DataTable rows={[{ id: "row-1" }]} columns={columns} rowKey={(r) => r.id} caption="Rows" />
      </ViewportProvider>,
    );
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText("row-1").closest("article")).not.toBeNull();
    window.matchMedia = original;
  });

  it("reads only a plausible width from the cookie", () => {
    expect(parseViewportWidth("390")).toBe(390);
    expect(parseViewportWidth("abc")).toBeNull();
    expect(parseViewportWidth(undefined)).toBeNull();
  });
});
