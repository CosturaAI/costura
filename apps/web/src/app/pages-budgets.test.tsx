/** The budgets page. */

import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import * as fx from "@/test/fixtures";
import BudgetsPage from "./(app)/budgets/page";
import { page, withPageDefaults, type MockedApi } from "@/test/page-harness";

vi.mock("next/navigation", () => import("@/test/page-harness").then((h) => h.navigationModule()));
vi.mock("@/lib/session-cookie", () =>
  import("@/test/page-harness").then((h) => h.sessionCookieModule()),
);
vi.mock("@/lib/view-cookie", () => import("@/test/page-harness").then((h) => h.viewCookieModule()));
vi.mock("@/lib/api", () => import("@/test/page-harness").then((h) => h.apiModule()));
vi.mock("./(app)/settings/connection-actions", () =>
  import("@/test/page-harness").then((h) =>
    h.stubs(
      "addCreditPriceAction",
      "connectAction",
      "deleteCreditPriceAction",
      "disconnectAction",
      "renameAccountAction",
      "removeAccountAction",
      "resetSetupAction",
      "syncNowAction",
    ),
  ),
);
vi.mock("./(app)/settings/member-actions", () =>
  import("@/test/page-harness").then((h) =>
    h.stubs("inviteAction", "revokeInvitationAction", "setMemberRoleAction", "removeMemberAction"),
  ),
);
vi.mock("./(app)/settings/organization-actions", () =>
  import("@/test/page-harness").then((h) =>
    h.stubs("leaveOrganizationAction", "renameOrganizationAction"),
  ),
);
vi.mock("./(app)/budgets/actions", () =>
  import("@/test/page-harness").then((h) => h.stubs("setBudgetAction", "deleteBudgetAction")),
);
vi.mock("./(app)/anomalies/actions", () =>
  import("@/test/page-harness").then((h) => h.anomalyActionsModule()),
);
vi.mock("./(app)/overview/actions", () =>
  import("@/test/page-harness").then((h) => h.stubs("dismissSetupAction")),
);
vi.mock("@/actions/view", () => import("@/test/page-harness").then((h) => h.viewActionsModule()));
vi.mock("@/actions/welcome", () =>
  import("@/test/page-harness").then((h) => h.stubs("getSetupAction", "startSyncAction")),
);

const { api } = await import("@/lib/api");
const mocked = api as unknown as MockedApi;
withPageDefaults(mocked);

describe("budgets page", () => {
  it("opens the form when there is no budget and offers the org and workspace scopes", async () => {
    render(await BudgetsPage());

    expect(mocked.workspaces).toHaveBeenCalledWith("default", "anthropic", false);
    expect(screen.getByText(/No budget yet/)).toBeInTheDocument();
    expect(screen.getByText("New budget")).toBeInTheDocument();
    // The first budget is the page's main action: an inline form, not a modal to escape from.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "New budget" })).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    const scope = screen.getByLabelText("Scope");
    expect(
      within(scope)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Organization total", "Platform"]);
    expect(screen.getByLabelText("Amount (USD)")).toHaveAttribute("type", "number");
    expect(screen.getByLabelText("Alert at (% of amount)")).toHaveAttribute(
      "placeholder",
      "50, 80, 100",
    );
    expect(screen.getByRole("button", { name: "Save budget" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add a budget" })).not.toBeInTheDocument();
  });

  it("lists each budget with its bar, opens inline edit and shows the month's alerts", async () => {
    mocked.budgets.mockResolvedValue({ budgets: fx.budgets });
    mocked.budgetStatuses.mockResolvedValue(fx.budgetStatuses);
    render(await BudgetsPage());

    const table = screen.getByRole("table");
    expect(within(table).getByText("organization total")).toBeInTheDocument();
    expect(within(table).getByText("Platform")).toBeInTheDocument();
    expect(within(table).getByRole("meter", { name: "Platform budget" })).toHaveAttribute(
      "aria-valuenow",
      "81",
    );
    expect(within(table).getByText("50%*, 80%*, 100%")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Remove the budget for Platform" }),
    ).toBeInTheDocument();
    // The form is closed until Edit or Add is pressed.
    expect(screen.queryByRole("button", { name: "Save budget" })).not.toBeInTheDocument();
    const alerts = within(screen.getByRole("list", { name: "Budget alerts" })).getAllByRole(
      "listitem",
    );
    expect(alerts.map((a) => a.textContent)).toEqual([
      "Aug 9: Platform is projected to end the month at 11,800.00, above the 10,000.00 budget",
      "Aug 9: Platform crossed 80% (8,120.00 of 10,000.00)",
      "Aug 8: organization total crossed 80% (48,200.00 of 60,000.00)",
      "Aug 5: organization total crossed 50% (30,100.00 of 60,000.00)",
    ]);
    expect(screen.getAllByRole("meter", { name: "organization total budget" })).toHaveLength(1);

    const user = userEvent.setup();
    const edit = screen.getByRole("button", { name: "Edit the budget for Platform" });
    await user.click(edit);
    expect(
      screen.getByRole("dialog", { name: "Edit the budget for Platform" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Amount (USD)")).toHaveValue(10000);
    expect(screen.getByRole("button", { name: "Save changes" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(edit).toHaveFocus());

    // Add opens the same sheet with a Cancel button, and Escape dismisses it.
    await user.click(screen.getByRole("button", { name: "Add a budget" }));
    expect(screen.getByRole("dialog", { name: "New budget" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("answers a time frame across months with one block per month, newest first", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-09-20T12:00:00Z"));
    onTestFinished(() => {
      vi.useRealTimers();
    });
    page.view = {
      org: "default",
      month: "2026-09",
      scope: "anthropic",
      from: "2026-07-15",
      to: "2026-09-10",
    };
    mocked.budgets.mockResolvedValue({ budgets: fx.budgets });
    mocked.budgetStatuses.mockResolvedValue(fx.budgetStatuses);
    render(await BudgetsPage());

    expect(mocked.budgetStatuses.mock.calls.map((call) => call[2])).toEqual([
      "2026-09",
      "2026-08",
      "2026-07",
    ]);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Budgets from Jul 15 to Sep 10",
    );
    const blocks = screen.getByRole("region", { name: "Month by month" });
    expect(
      within(blocks)
        .getAllByRole("heading")
        .map((heading) => heading.textContent),
    ).toEqual(["September 2026", "August 2026", "July 2026"]);
    expect(screen.getByText(/Progress is for September 2026/)).toBeInTheDocument();
  });

  it("reads but does not edit when writes are off", async () => {
    mocked.budgets.mockResolvedValue({ budgets: fx.budgets });
    mocked.budgetStatuses.mockResolvedValue(fx.budgetStatuses);
    mocked.connection.mockResolvedValue({ ...fx.connection, writes_enabled: false });
    render(await BudgetsPage());

    expect(
      screen.getByText(/This Costura instance does not accept changes from the browser/),
    ).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Edit the budget/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Remove the budget/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add a budget" })).not.toBeInTheDocument();
  });

  it("says the sample's budgets are fixed where it has none", async () => {
    mocked.org.mockResolvedValue(fx.demoOrganization);
    page.organizations = [fx.demoOrganization];
    page.view = { ...page.view!, org: fx.demoOrganization.slug };
    render(await BudgetsPage());
    expect(screen.getByText(/The sample's budgets are fixed/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save budget" })).not.toBeInTheDocument();
  });

  it("posts the form to the scope's provider without a provider select", async () => {
    render(await BudgetsPage());
    expect(screen.queryByLabelText("Provider")).not.toBeInTheDocument();
    const form = screen.getByRole("button", { name: "Save budget" }).closest("form")!;
    expect(form.querySelector('input[name="provider"]')).toHaveAttribute("value", "anthropic");
    expect(screen.queryByText(/Anthropic Console/)).not.toBeInTheDocument();
  });

  describe("under all providers", () => {
    beforeEach(() => {
      page.view = { ...page.view!, scope: "all" };
    });

    it("unions the budgets with a provider badge and lets the form choose a connected provider", async () => {
      mocked.budgets.mockResolvedValue({ budgets: [...fx.budgets, fx.openRouterBudget] });
      mocked.budgetStatuses.mockResolvedValue({
        ...fx.budgetStatuses,
        statuses: [...fx.budgetStatuses.statuses, fx.openRouterBudgetStatus],
      });
      mocked.workspaces.mockResolvedValue({
        items: [
          ...fx.workspaces,
          { ...fx.workspaces[0], provider: "openrouter", external_id: "ws_or_1", name: "Default" },
        ],
      });
      render(await BudgetsPage());

      expect(mocked.budgetStatuses).toHaveBeenCalledWith("default", "all", "2026-08");
      expect(mocked.workspaces).toHaveBeenCalledWith("default", "all", false);
      expect(mocked.connection).not.toHaveBeenCalledWith("default", "all");
      const table = screen.getByRole("table");
      expect(within(table).getByRole("columnheader", { name: "provider" })).toBeInTheDocument();
      expect(within(table).getAllByText("Anthropic")).toHaveLength(2);
      expect(within(table).getAllByText("OpenRouter")).toHaveLength(1);
      // Remove posts to the budget's own provider.
      const remove = screen
        .getAllByRole("button", { name: /Remove the budget for organization total/ })[1]!
        .closest("form")!;
      expect(remove.querySelector('input[name="provider"]')).toHaveAttribute("value", "openrouter");

      fireEvent.click(screen.getByRole("button", { name: "Add a budget" }));
      const select = screen.getByLabelText("Provider");
      expect(
        within(select)
          .getAllByRole("option")
          .map((o) => o.textContent),
      ).toEqual(["Anthropic", "OpenRouter", "Every provider"]);
      // Scopes follow the chosen provider: Anthropic's workspace first, OpenRouter's after.
      expect(
        within(screen.getByLabelText("Scope"))
          .getAllByRole("option")
          .map((o) => o.textContent),
      ).toEqual(["Organization total (has a budget)", "Platform (has a budget)"]);
      fireEvent.change(select, { target: { value: "openrouter" } });
      expect(
        within(screen.getByLabelText("Scope"))
          .getAllByRole("option")
          .map((o) => o.textContent),
      ).toEqual(["Organization total (has a budget)", "Default"]);
      // Every provider: the organization total across providers first, then one person
      // each; service accounts are not people.
      fireEvent.change(select, { target: { value: "all" } });
      const [total, ...people] = within(screen.getByLabelText("Scope"))
        .getAllByRole("option")
        .map((o) => o.getAttribute("value"));
      expect(total).toBe("org:__org__");
      expect(people.length).toBeGreaterThan(0);
      expect(people.every((value) => value?.startsWith("person:") && value.includes("@"))).toBe(
        true,
      );
      expect(mocked.users).toHaveBeenCalledWith("default", "all", false);
    });

    it("offers only connected providers and explains when none is", async () => {
      mocked.providers.mockResolvedValue(fx.providersOneConnected);
      render(await BudgetsPage());
      // One connected provider: the select offers it and the person budget across providers.
      expect(
        within(screen.getByLabelText("Provider"))
          .getAllByRole("option")
          .map((o) => o.textContent),
      ).toEqual(["Anthropic", "Every provider"]);
      cleanup();

      // Without people in the inventory the all-provider total is still offered.
      mocked.users.mockResolvedValue({ items: [] });
      render(await BudgetsPage());
      expect(
        within(screen.getByLabelText("Provider"))
          .getAllByRole("option")
          .map((o) => o.textContent),
      ).toEqual(["Anthropic", "Every provider"]);
      cleanup();

      mocked.providers.mockResolvedValue(fx.providersNoneConnected);
      render(await BudgetsPage());
      expect(screen.queryByRole("button", { name: "Save budget" })).not.toBeInTheDocument();
      expect(
        screen.getByText(/Connect a provider key before setting a budget/),
      ).toBeInTheDocument();
    });
  });
});
