import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import * as fx from "@/test/fixtures";

import { WhatChanged } from "./what-changed";

describe("WhatChanged", () => {
  it("states the three largest moves in one sentence each", () => {
    render(<WhatChanged movers={fx.movers} />);
    const rows = within(screen.getByRole("list", { name: "Largest moves" })).getAllByRole(
      "listitem",
    );
    expect(rows.length).toBeLessThanOrEqual(3);
    expect(rows[0]).toHaveTextContent(
      "batch-ingest rose 28,000.00 USD (+233.33%) against July 2026.",
    );
    expect(rows[1]).toHaveTextContent("nightly-eval stopped: 9,000.00 USD in July 2026, none now.");
    expect(rows[2]).toHaveTextContent("agent-loop is new: 5,200.00 USD, nothing in July 2026.");
  });

  it("says nothing when the moves cannot be ranked", () => {
    const { container } = render(<WhatChanged movers={fx.noMovers} />);
    expect(container).toBeEmptyDOMElement();
  });
});
