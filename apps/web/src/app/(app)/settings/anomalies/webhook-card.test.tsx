import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as fx from "@/test/fixtures";

import { WebhookCard } from "./webhook-card";

const actions = vi.hoisted(() => ({
  save: vi.fn(),
  test: vi.fn(),
  remove: vi.fn(),
  digest: vi.fn(),
  resend: vi.fn(),
}));
vi.mock("../webhook-actions", () => ({
  saveWebhookAction: actions.save,
  testWebhookAction: actions.test,
  removeWebhookAction: actions.remove,
  setDigestAction: actions.digest,
}));
vi.mock("./resend-action", () => ({ resendDeliveryAction: actions.resend }));

describe("WebhookCard", () => {
  beforeEach(() => {
    actions.save.mockReset();
    actions.test.mockReset();
    actions.resend.mockReset();
  });

  it("shows the signing secret once after a save", async () => {
    actions.save.mockResolvedValue({ ok: true, message: "Saved.", secret: "s3cret" });
    render(<WebhookCard webhook={{ ...fx.webhookSaved, configured: false }} canManage />);
    expect(screen.getByText(/No webhook saved. Allowed hosts: hooks.slack.com/)).toBeVisible();
    fireEvent.change(screen.getByLabelText("Webhook URL"), {
      target: { value: "https://hooks.slack.com/services/x" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByText("s3cret")).toBeInTheDocument());
    expect(screen.getByText(/The signing secret is shown once/)).toBeInTheDocument();
  });

  it("reports the test result and warns when the host left the allowlist", async () => {
    actions.test.mockResolvedValue({ ok: false, message: "The webhook did not accept it." });
    render(<WebhookCard webhook={{ ...fx.webhookSaved, host_blocked: true }} canManage />);
    expect(screen.getByText(/is no longer in COSTURA_WEBHOOK_HOSTS/)).toBeInTheDocument();
    expect(screen.getByLabelText("Digest")).toHaveValue("weekly");
    fireEvent.click(screen.getByRole("button", { name: "Send a test message" }));
    await waitFor(() =>
      expect(screen.getByText("The webhook did not accept it.")).toBeInTheDocument(),
    );
  });

  it("leaves a member without the controls", () => {
    render(<WebhookCard webhook={fx.webhookSaved} canManage={false} />);
    expect(screen.queryByRole("button", { name: "Send a test message" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/webhook URL/i)).not.toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Recent deliveries" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Resend/ })).not.toBeInTheDocument();
  });

  it("lists each delivery with its outcome and lets an owner resend one", async () => {
    actions.resend.mockResolvedValue({ ok: true, message: "Posted again." });
    render(<WebhookCard webhook={fx.webhookSaved} canManage />);
    const table = screen.getByRole("table", { name: "Recent deliveries" });
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).getByText("HTTP 503, 2 attempts")).toBeInTheDocument();
    expect(within(table).getByText("2026-08-12 09:01:00 UTC")).toBeInTheDocument();
    const buttons = screen.getAllByRole("button", { name: /^Resend/ });
    expect(buttons.map((b) => b.getAttribute("aria-label"))).toEqual([
      "Resend anomaly anthropic",
      "Resend no owner openrouter",
    ]);
    fireEvent.click(buttons[1]!);
    await waitFor(() => expect(screen.getByText("Posted again.")).toBeInTheDocument());
    const form = actions.resend.mock.calls[0]![1] as FormData;
    expect(form.get("delivery_id")).toBe("12");
  });

  it("shows a refused resend next to its row", async () => {
    actions.resend.mockResolvedValue({ ok: false, message: "The webhook did not accept it." });
    render(<WebhookCard webhook={fx.webhookSaved} canManage />);
    fireEvent.click(screen.getByRole("button", { name: "Resend anomaly anthropic" }));
    await waitFor(() =>
      expect(screen.getByText("The webhook did not accept it.")).toBeInTheDocument(),
    );
  });

  it("names what fills an empty history and reports a webhook that did not load", () => {
    render(<WebhookCard webhook={{ ...fx.webhookSaved, deliveries: [] }} canManage />);
    expect(screen.getByText("Nothing posted yet")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    render(<WebhookCard webhook={null} canManage />);
    expect(screen.getByText(/Could not load the webhook/)).toBeInTheDocument();
  });
});
