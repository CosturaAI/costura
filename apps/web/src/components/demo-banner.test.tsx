import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DemoBanner } from "./demo-banner";

function band() {
  return screen.getByRole("region", { name: "Sample organization" });
}

describe("DemoBanner", () => {
  it("says what the sample is and how to leave it", () => {
    render(<DemoBanner connectHref="/sign-in" orgName="Lumen Labs" />);
    expect(band()).toHaveTextContent(
      "Lumen Labs is a fictional company: every figure is synthetic, refreshed daily, and read-only.",
    );
    expect(within(band()).getByRole("link", { name: "Sign in to connect yours" })).toHaveAttribute(
      "href",
      "/sign-in",
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it.each([
    ["/new", "Create your organization"],
    ["/o/acme?next=%2Fwelcome", "Connect a provider in your organization"],
  ])("labels the way out to %s", (href, label) => {
    render(<DemoBanner connectHref={href} orgName="Lumen Labs" />);
    expect(within(band()).getByRole("link", { name: label })).toHaveAttribute("href", href);
  });
});
