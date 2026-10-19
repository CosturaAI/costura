import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import * as fx from "@/test/fixtures";

import { PostureList } from "./posture-list";

describe("PostureList", () => {
  it("keeps the key gaps, one row per key, and leaves anomalies and budgets out", () => {
    const gateway = fx.signals.items[1]!;
    const signals = {
      ...fx.signals,
      items: [...fx.signals.items, { ...gateway, kind: "no_owner" as const }],
    };
    render(<PostureList signals={signals} showProvider />);
    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);

    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByRole("link", { name: "gateway (or_gateway)" })).toHaveAttribute(
      "href",
      "/keys/or_gateway",
    );
    expect(within(rows[0]!).getByText("no limit")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("no owner", { selector: "span" })).toBeInTheDocument();
    expect(within(rows[1]!).getByText("new key")).toBeInTheDocument();
    expect(screen.queryByText("prod-backend (apikey_1)")).not.toBeInTheDocument();
  });

  it("says when every key is in order", () => {
    render(<PostureList signals={fx.noSignals} showProvider={false} />);
    expect(screen.getByText(/Every active key has an owner/)).toBeInTheDocument();
  });
});
