import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OwnersCard } from "./owners-card";

describe("OwnersCard", () => {
  it("signs each driver by its direction", () => {
    render(
      <OwnersCard
        owners={[]}
        gap={null}
        drivers={[
          { label: "ci-agents", delta: "120.5", href: null, flagged: false },
          { label: "prod-backend", delta: "-380", href: null, flagged: false },
        ]}
      />,
    );
    expect(screen.getByText("+120.50")).toBeInTheDocument();
    expect(screen.getByText("-380.00")).toBeInTheDocument();
    expect(screen.queryByText(/\+-/)).not.toBeInTheDocument();
  });
});
