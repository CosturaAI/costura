import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PUBLIC_DEMO_REPOSITORY, isPublicDemo } from "@/lib/public-demo";

import { PublicDemoBar } from "./public-demo-bar";

describe("PublicDemoBar", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("pins the repository link above every page and opens it in a new tab", () => {
    render(<PublicDemoBar />);
    const bar = screen.getByRole("region", { name: "Live demo" });
    expect(bar).toHaveClass("sticky", "top-0");
    expect(bar).toHaveTextContent(
      "Costura live demo: synthetic data, open source under Apache 2.0.",
    );
    const link = within(bar).getByRole("link", { name: "View on GitHub" });
    expect(link).toHaveAttribute("href", "https://github.com/CosturaAI/costura");
    expect(link).toHaveAttribute("href", PUBLIC_DEMO_REPOSITORY);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("is on only when the deployment sets COSTURA_PUBLIC_DEMO_HOME=true", () => {
    expect(isPublicDemo()).toBe(false);
    vi.stubEnv("COSTURA_PUBLIC_DEMO_HOME", "1");
    expect(isPublicDemo()).toBe(false);
    vi.stubEnv("COSTURA_PUBLIC_DEMO_HOME", "true");
    expect(isPublicDemo()).toBe(true);
  });
});
