import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import * as fx from "@/test/fixtures";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/actions/welcome", () => ({ getSetupAction: vi.fn() }));
vi.mock("./connection-actions", () => ({
  addCreditPriceAction: vi.fn(),
  connectAction: vi.fn(),
  deleteCreditPriceAction: vi.fn(),
  disconnectAction: vi.fn(),
  removeAccountAction: vi.fn(),
  renameAccountAction: vi.fn(),
  resetSetupAction: vi.fn(),
  syncNowAction: vi.fn(),
}));

const { CodexCreditPriceSchedule, ConnectForm } = await import("./connection-forms");

const codex = {
  ...fx.anthropicInfo,
  provider: "codex",
  label: "Codex",
  vendor: "OpenAI",
  surface: "Codex",
  key_label: "Admin API key",
  key_prefix: "sk-admin-",
  env_var: "CODEX_ADMIN_KEY",
  attribution: "direct" as const,
};

describe("Codex connection form", () => {
  it("captures a required workspace ID for new accounts", () => {
    render(<ConnectForm org="default" info={codex} />);

    expect(screen.getByRole("textbox", { name: "Workspace ID" })).toBeRequired();
    expect(screen.getByLabelText("Codex Admin API key")).toHaveAttribute(
      "placeholder",
      "sk-admin-...",
    );
  });

  it("keeps the immutable workspace ID out of key replacement", () => {
    render(
      <ConnectForm org="default" info={codex} mode="replace" account={{ id: 7, label: "Codex" }} />,
    );

    expect(screen.queryByRole("textbox", { name: "Workspace ID" })).toBeNull();
  });
});

describe("Codex credit price schedule", () => {
  const account = { id: 7, label: "Engineering Codex" };
  const price = {
    id: 4,
    organization_id: 1,
    provider_account_id: 7,
    effective_from: "2026-09-18",
    price_per_credit: "0.08000000",
    created_by: 1,
    created_at: "2026-09-18T12:00:00Z",
  };

  it("lists rates and offers add and delete controls to operators", () => {
    render(
      <CodexCreditPriceSchedule org="default" account={account} prices={[price]} canOperate />,
    );

    expect(screen.getByRole("list", { name: "Effective credit rates" })).toHaveTextContent(
      "2026-09-18 - 0.08000000 USD",
    );
    expect(screen.getByRole("button", { name: "Add rate" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Delete the rate from 2026-09-18" })).toBeEnabled();
  });

  it("shows required pricing and disables fields for viewers", () => {
    render(
      <CodexCreditPriceSchedule org="default" account={account} prices={[]} canOperate={false} />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Pricing required");
    expect(screen.getByLabelText("Effective from")).toBeDisabled();
    expect(screen.getByLabelText("USD per credit")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Add rate" })).toBeNull();
    expect(screen.getByText(/owner or member/)).toBeVisible();
  });
});

describe("connection form risk line", () => {
  it("says how far a leaked OpenRouter management key reaches", () => {
    render(<ConnectForm org="default" info={fx.openRouterInfo} />);
    expect(screen.getByText(/Management keys are unscoped/)).toBeInTheDocument();
  });
});
