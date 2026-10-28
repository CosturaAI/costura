import { beforeEach, describe, expect, it, vi } from "vitest";

import { idleAction } from "@/lib/action-errors";
import { ApiError, type SignalRead } from "@/lib/api";
import * as fx from "@/test/fixtures";

const revalidatePath = vi.fn();

vi.mock("next/cache", () => ({ revalidatePath: (...args: unknown[]) => revalidatePath(...args) }));
vi.mock("next/navigation", () => ({
  redirect: (url: string) => {
    throw new Error(`NEXT_REDIRECT ${url}`);
  },
}));
vi.mock("@/lib/session-cookie", () => ({ readSessionToken: () => Promise.resolve("tok-1") }));
vi.mock("@/lib/view-cookie", () => ({
  readViewCookie: () => Promise.resolve({ org: "acme", month: "2026-09", scope: "all" }),
}));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      alerts: vi.fn(),
      assignOwner: vi.fn(),
      deleteBudget: vi.fn(),
      deleteTeam: vi.fn(),
      deleteTeamMember: vi.fn(),
      deleteInvoice: vi.fn(),
      dismissSetup: vi.fn(),
      markAlertsRead: vi.fn(),
      markPersonalKey: vi.fn(),
      setAlertSettings: vi.fn(),
      setAnomalyStatus: vi.fn(),
      setBudget: vi.fn(),
      setInvoice: vi.fn(),
      setTeam: vi.fn(),
      setTeamMember: vi.fn(),
      teams: vi.fn(),
      setup: vi.fn(),
      syncNow: vi.fn(),
      unassignOwner: vi.fn(),
      unmarkPersonalKey: vi.fn(),
    },
  };
});

const { api } = await import("@/lib/api");
const { ORG_SCOPE_ID } = await import("@/lib/budgets");
const budgets = await import("./(app)/budgets/actions");
const anomalies = await import("./(app)/anomalies/actions");
const overview = await import("./(app)/overview/actions");
const welcome = await import("@/actions/welcome");
const alerts = await import("@/actions/alerts");
const keys = await import("@/actions/keys");
const reconcile = await import("@/actions/reconcile");
const teams = await import("./(app)/settings/team-actions");

const formOf = (fields: Record<string, string | string[]>) => {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields)) {
    for (const item of Array.isArray(value) ? value : [value]) data.append(key, item);
  }
  return data;
};
const refused = new ApiError(403, "/orgs/demo", "this action needs the owner role");

beforeEach(() => {
  vi.clearAllMocks();
});

describe("budget actions", () => {
  it("sets the organization total under the reserved scope id", async () => {
    vi.mocked(api.setBudget).mockResolvedValue(fx.orgBudget);
    await expect(
      budgets.setBudgetAction(
        idleAction,
        formOf({ scope: "org:", amount: " 60000 ", thresholds: "50, 80,100", provider: "openai" }),
      ),
    ).resolves.toEqual({
      ok: true,
      message: "Budget for organization total set to 60000.00 USD a month.",
    });
    expect(api.setBudget).toHaveBeenCalledWith(
      "acme",
      "openai",
      "org",
      ORG_SCOPE_ID,
      "60000",
      [50, 80, 100],
      "month",
    );
    expect(revalidatePath).toHaveBeenCalledWith("/budgets");
    expect(revalidatePath).not.toHaveBeenCalledWith("/", "layout");
  });

  it("sets a person budget across every provider", async () => {
    vi.mocked(api.setBudget).mockResolvedValue({
      ...fx.orgBudget,
      provider: "all",
      scope_kind: "person",
      scope_id: "ana@acme.com",
      label: "ana@acme.com",
    });
    await expect(
      budgets.setBudgetAction(
        idleAction,
        formOf({ scope: "person:ana@acme.com", amount: "300", provider: "all" }),
      ),
    ).resolves.toMatchObject({ ok: true });
    expect(api.setBudget).toHaveBeenCalledWith(
      "acme",
      "all",
      "person",
      "ana@acme.com",
      "300",
      null,
      "month",
    );
  });

  it("sets a daily budget and says so", async () => {
    vi.mocked(api.setBudget).mockResolvedValue({ ...fx.orgBudget, period: "day" });
    await expect(
      budgets.setBudgetAction(
        idleAction,
        formOf({ scope: "org:", amount: "200", period: "day", provider: "openai" }),
      ),
    ).resolves.toEqual({
      ok: true,
      message: "Budget for organization total set to 60000.00 USD a day.",
    });
    expect(api.setBudget).toHaveBeenCalledWith(
      "acme",
      "openai",
      "org",
      ORG_SCOPE_ID,
      "200",
      null,
      "day",
    );
  });

  it("keeps a workspace id that contains colons", async () => {
    vi.mocked(api.setBudget).mockResolvedValue(fx.workspaceBudget);
    await budgets.setBudgetAction(
      idleAction,
      formOf({ scope: "workspace:ws:a", amount: "10", thresholds: "" }),
    );
    expect(api.setBudget).toHaveBeenCalledWith(
      "acme",
      "all",
      "workspace",
      "ws:a",
      "10",
      null,
      "month",
    );
  });

  it.each([
    [{ scope: "squad:x", amount: "1" }, "scope"],
    [{ scope: "org:", amount: "0" }, "amount"],
    [{ scope: "org:", amount: "5", thresholds: "0, 300" }, "thresholds"],
    [{ scope: "person:ana@acme.com", amount: "5", period: "day" }, "period"],
  ])("refuses %o on the %s field", async (fields, field) => {
    await expect(budgets.setBudgetAction(idleAction, formOf(fields))).resolves.toMatchObject({
      ok: false,
      field,
    });
    expect(api.setBudget).not.toHaveBeenCalled();
  });

  it("deletes a budget and refuses an unknown scope", async () => {
    vi.mocked(api.deleteBudget).mockResolvedValue(undefined);
    await expect(
      budgets.deleteBudgetAction(idleAction, formOf({ scope_kind: "workspace", scope_id: "w1" })),
    ).resolves.toEqual({ ok: true, message: "Budget removed with its alerts." });
    expect(api.deleteBudget).toHaveBeenCalledWith("acme", "all", "workspace", "w1");

    await expect(
      budgets.deleteBudgetAction(idleAction, formOf({ scope_kind: "squad" })),
    ).resolves.toEqual({ ok: false, message: "Unknown budget scope." });
  });

  it("reports an API refusal as a message", async () => {
    vi.mocked(api.deleteBudget).mockRejectedValue(refused);
    await expect(
      budgets.deleteBudgetAction(idleAction, formOf({ scope_kind: "org", scope_id: "x" })),
    ).resolves.toMatchObject({ ok: false });
  });
});

describe("invoice actions", () => {
  it("saves an invoice total and refuses a bad amount, account or month", async () => {
    vi.mocked(api.setInvoice).mockResolvedValue({
      provider: "openai",
      account_id: 3,
      account_label: "OpenAI",
      month: "2026-09",
      amount: "1234.56",
      currency: "USD",
      note: null,
      entered_by: null,
      updated_at: "2026-10-01T00:00:00Z",
    });
    await expect(
      reconcile.setInvoiceAction(
        idleAction,
        formOf({ provider: "openai", account_id: "3", month: "2026-09", amount: " 1,234.56 " }),
      ),
    ).resolves.toEqual({ ok: true, message: "Invoice total for 2026-09 saved." });
    expect(api.setInvoice).toHaveBeenCalledWith("acme", "openai", 3, "2026-09", "1234.56", null);

    await expect(
      reconcile.setInvoiceAction(
        idleAction,
        formOf({ account_id: "3", month: "2026-09", amount: "12.345" }),
      ),
    ).resolves.toMatchObject({ ok: false, field: "amount" });
    await expect(
      reconcile.setInvoiceAction(idleAction, formOf({ account_id: "x", month: "2026-09" })),
    ).resolves.toEqual({ ok: false, message: "Unknown account or month." });
    await expect(
      reconcile.setInvoiceAction(idleAction, formOf({ account_id: "3", month: "2026-13" })),
    ).resolves.toEqual({ ok: false, message: "Unknown account or month." });
    expect(api.setInvoice).toHaveBeenCalledTimes(1);
  });

  it("removes an invoice total and reports a refusal", async () => {
    vi.mocked(api.deleteInvoice).mockResolvedValue(undefined);
    await expect(
      reconcile.deleteInvoiceAction(idleAction, formOf({ account_id: "3", month: "2026-09" })),
    ).resolves.toEqual({ ok: true, message: "Invoice total removed." });
    expect(api.deleteInvoice).toHaveBeenCalledWith("acme", "all", 3, "2026-09");
    vi.mocked(api.deleteInvoice).mockRejectedValue(refused);
    await expect(
      reconcile.deleteInvoiceAction(idleAction, formOf({ account_id: "3", month: "2026-09" })),
    ).resolves.toMatchObject({ ok: false });
  });
});

describe("personal key actions", () => {
  it("marks a key for a person and refuses a missing key or e-mail", async () => {
    vi.mocked(api.markPersonalKey).mockResolvedValue({
      provider: "openai",
      api_key_id: "key_1",
      label: "gateway",
      email: "ana@acme.com",
      assigned_by: null,
      updated_at: "2026-10-11T00:00:00Z",
    });
    await expect(
      keys.markPersonalKeyAction(
        idleAction,
        formOf({ provider: "openai", api_key_id: "key_1", email: " ana@acme.com " }),
      ),
    ).resolves.toEqual({ ok: true, message: "This key's spend now counts under ana@acme.com." });
    expect(api.markPersonalKey).toHaveBeenCalledWith("acme", "openai", "key_1", "ana@acme.com");
    expect(revalidatePath).toHaveBeenCalledWith("/keys/[id]", "page");

    await expect(
      keys.markPersonalKeyAction(idleAction, formOf({ email: "ana@acme.com" })),
    ).resolves.toEqual({ ok: false, message: "Unknown key." });
    await expect(
      keys.markPersonalKeyAction(idleAction, formOf({ api_key_id: "key_1", email: "ana" })),
    ).resolves.toMatchObject({ ok: false, field: "email" });
    expect(api.markPersonalKey).toHaveBeenCalledTimes(1);
  });

  it("reports a refused address and removes a mark", async () => {
    vi.mocked(api.markPersonalKey).mockRejectedValue(
      new ApiError(422, "/x", "no provider account in this organization uses that e-mail"),
    );
    await expect(
      keys.markPersonalKeyAction(
        idleAction,
        formOf({ api_key_id: "key_1", email: "stranger@acme.com" }),
      ),
    ).resolves.toMatchObject({ ok: false });

    vi.mocked(api.unmarkPersonalKey).mockResolvedValue(undefined);
    await expect(
      keys.unmarkPersonalKeyAction(idleAction, formOf({ api_key_id: "key_1" })),
    ).resolves.toEqual({
      ok: true,
      message: "Mark removed; the key counts as a service key again.",
    });
    expect(api.unmarkPersonalKey).toHaveBeenCalledWith("acme", "all", "key_1");
    await expect(keys.unmarkPersonalKeyAction(idleAction, formOf({}))).resolves.toEqual({
      ok: false,
      message: "Unknown key.",
    });
  });
});

describe("anomaly actions", () => {
  it("sets a known status and refuses anything else", async () => {
    vi.mocked(api.setAnomalyStatus).mockResolvedValue(fx.anomaly);
    await expect(
      anomalies.setStatusAction(idleAction, formOf({ id: "7", status: "ignored" })),
    ).resolves.toEqual({ ok: true, message: "Marked ignored." });
    expect(api.setAnomalyStatus).toHaveBeenCalledWith("acme", "all", 7, "ignored", null);
    await anomalies.setStatusAction(
      idleAction,
      formOf({ id: "7", status: "acknowledged", reason: " expected: backfill " }),
    );
    expect(api.setAnomalyStatus).toHaveBeenLastCalledWith(
      "acme",
      "all",
      7,
      "acknowledged",
      "expected: backfill",
    );

    await expect(
      anomalies.setStatusAction(idleAction, formOf({ id: "x", status: "open" })),
    ).resolves.toEqual({ ok: false, message: "Unknown anomaly or status." });
  });

  it("marks only integer ids read and swallows a refusal", async () => {
    vi.mocked(api.markAlertsRead).mockRejectedValue(refused);
    await expect(anomalies.markReadAction([1, 2.5, 3])).resolves.toBeUndefined();
    expect(api.markAlertsRead).toHaveBeenCalledWith("acme", { ids: [1, 3] });

    vi.mocked(api.markAlertsRead).mockClear();
    await anomalies.markReadAction([Number.NaN]);
    expect(api.markAlertsRead).not.toHaveBeenCalled();
  });

  it("assigns a contact to a key and validates the form first", async () => {
    vi.mocked(api.assignOwner).mockResolvedValue({
      kind: "api_key",
      external_id: "key_1",
      email: "ana@acme.com",
      note: null,
    } as Awaited<ReturnType<typeof api.assignOwner>>);
    await expect(
      anomalies.assignOwnerAction(
        idleAction,
        formOf({ kind: "api_key", external_id: "key_1", email: " ana@acme.com ", note: " " }),
      ),
    ).resolves.toEqual({ ok: true, message: "ana@acme.com now answers for this key." });
    expect(api.assignOwner).toHaveBeenCalledWith(
      "acme",
      "all",
      "api_key",
      "key_1",
      "ana@acme.com",
      null,
    );

    await expect(
      anomalies.assignOwnerAction(idleAction, formOf({ kind: "model", external_id: "m" })),
    ).resolves.toEqual({ ok: false, message: "Unknown key or workspace." });
    await expect(
      anomalies.assignOwnerAction(
        idleAction,
        formOf({ kind: "workspace", external_id: "w1", email: "ana" }),
      ),
    ).resolves.toMatchObject({ ok: false, field: "email" });
  });

  it("removes an assigned contact", async () => {
    vi.mocked(api.unassignOwner).mockResolvedValue(undefined);
    await expect(
      anomalies.unassignOwnerAction(idleAction, formOf({ kind: "workspace", external_id: "w1" })),
    ).resolves.toEqual({
      ok: true,
      message: "Assigned contact removed; the inventory decides again.",
    });
    await expect(
      anomalies.unassignOwnerAction(idleAction, formOf({ kind: "workspace" })),
    ).resolves.toEqual({ ok: false, message: "Unknown key or workspace." });
  });

  it("applies a bulk transition and stops at the first refusal", async () => {
    vi.mocked(api.setAnomalyStatus)
      .mockResolvedValueOnce(fx.anomaly)
      .mockRejectedValueOnce(new TypeError("fetch failed"));
    await expect(
      anomalies.bulkStatusAction(
        idleAction,
        formOf({ status: "acknowledged", ids: ["1", "2", "3"] }),
      ),
    ).resolves.toEqual({
      ok: false,
      message: "1 of 3 marked acknowledged; then: Costura did not answer. Retry in a moment.",
    });
    expect(api.setAnomalyStatus).toHaveBeenCalledTimes(2);
    expect(revalidatePath).toHaveBeenCalledWith("/anomalies");

    vi.mocked(api.setAnomalyStatus).mockResolvedValue(fx.anomaly);
    await expect(
      anomalies.bulkStatusAction(idleAction, formOf({ status: "open", ids: ["4", "5"] })),
    ).resolves.toEqual({ ok: true, message: "2 marked open." });
    await expect(
      anomalies.bulkStatusAction(idleAction, formOf({ status: "open" })),
    ).resolves.toEqual({ ok: false, message: "Select at least one anomaly." });
    await expect(
      anomalies.bulkStatusAction(idleAction, formOf({ status: "gone", ids: ["1"] })),
    ).resolves.toEqual({ ok: false, message: "Unknown status." });
  });
});

describe("setup and inbox actions", () => {
  it("dismisses the getting-started card for the active organization", async () => {
    vi.mocked(api.dismissSetup).mockResolvedValue(fx.setupReady);
    await expect(overview.dismissSetupAction()).resolves.toEqual({
      ok: true,
      message: "Dismissed.",
    });
    expect(api.dismissSetup).toHaveBeenCalledWith("acme");

    vi.mocked(api.dismissSetup).mockRejectedValue(refused);
    await expect(overview.dismissSetupAction()).resolves.toMatchObject({ ok: false });
  });

  it("polls the setup state without throwing", async () => {
    vi.mocked(api.setup).mockResolvedValueOnce(fx.setupSyncing);
    await expect(welcome.getSetupAction("acme")).resolves.toEqual({
      setup: fx.setupSyncing,
      error: null,
    });
    vi.mocked(api.setup).mockRejectedValueOnce(new TypeError("fetch failed"));
    await expect(welcome.getSetupAction("acme")).resolves.toEqual({
      setup: null,
      error: "Costura did not answer. Retry in a moment.",
    });
  });

  it("starts a sync and surfaces a skipped run", async () => {
    vi.mocked(api.syncNow).mockResolvedValueOnce({
      results: [
        {
          provider: "openai",
          provider_account_id: 1,
          run_id: 4,
          status: "queued",
          error: null,
          steps: [],
        },
      ],
    });
    await expect(welcome.startSyncAction("acme", "openai")).resolves.toEqual({
      ok: true,
      message: "Sync started.",
    });

    vi.mocked(api.syncNow).mockResolvedValueOnce({
      results: [
        {
          provider: "openai",
          provider_account_id: null,
          run_id: 5,
          status: "skipped",
          error: null,
          steps: [],
        },
      ],
    });
    await expect(welcome.startSyncAction("acme", "openai")).resolves.toEqual({
      ok: false,
      message: "Nothing to sync.",
    });

    vi.mocked(api.syncNow).mockRejectedValueOnce(refused);
    await expect(welcome.startSyncAction("acme", "openai")).resolves.toMatchObject({ ok: false });
  });

  it("reads the inbox and marks everything read", async () => {
    vi.mocked(api.alerts).mockResolvedValueOnce(fx.alerts);
    await expect(alerts.getAlertsAction()).resolves.toEqual({
      alerts: fx.alerts,
      error: null,
    });
    vi.mocked(api.alerts).mockRejectedValueOnce(refused);
    await expect(alerts.getAlertsAction()).resolves.toMatchObject({ alerts: null });

    vi.mocked(api.markAlertsRead).mockResolvedValueOnce(fx.alertsOff);
    await expect(alerts.markAllReadAction()).resolves.toEqual({
      alerts: fx.alertsOff,
      error: null,
    });
    expect(api.markAlertsRead).toHaveBeenCalledWith("acme", { all: true });
    vi.mocked(api.markAlertsRead).mockRejectedValueOnce(refused);
    await expect(alerts.markAllReadAction()).resolves.toMatchObject({ alerts: null });
  });

  it("marks one opened signal read and ignores a malformed one", async () => {
    vi.mocked(api.markAlertsRead).mockClear().mockResolvedValueOnce(fx.alertsOff);
    const signal = { kind: "no_owner", provider: "openrouter", read_reference: "orkey_hash_1" };
    await alerts.markSignalReadAction(signal as SignalRead);
    expect(api.markAlertsRead).toHaveBeenCalledWith("acme", { signals: [signal] });

    vi.mocked(api.markAlertsRead).mockClear();
    await alerts.markSignalReadAction({ ...signal, kind: "anomaly" } as unknown as SignalRead);
    expect(api.markAlertsRead).not.toHaveBeenCalled();

    vi.mocked(api.markAlertsRead).mockRejectedValueOnce(refused);
    await expect(alerts.markSignalReadAction(signal as SignalRead)).resolves.toBeUndefined();
  });

  it("switches the inbox opt-in with a sentence for each direction", async () => {
    vi.mocked(api.setAlertSettings).mockResolvedValue(fx.alerts);
    await expect(
      alerts.setAlertSettingsAction(idleAction, formOf({ opted_in: "true" })),
    ).resolves.toEqual({
      ok: true,
      message:
        "You will see new anomalies, budget alerts and key gaps of this organization in the bell.",
    });
    expect(api.setAlertSettings).toHaveBeenCalledWith("acme", true);
    await expect(alerts.setAlertSettingsAction(idleAction, formOf({}))).resolves.toEqual({
      ok: true,
      message: "Alerts are off for this organization.",
    });

    vi.mocked(api.setAlertSettings).mockRejectedValue(refused);
    await expect(
      alerts.setAlertSettingsAction(idleAction, formOf({ opted_in: "true" })),
    ).resolves.toMatchObject({ ok: false });
  });
});

describe("team actions", () => {
  it("derives the slug from the name and maps a chosen entity", async () => {
    vi.mocked(api.teams).mockResolvedValue({ teams: [] });
    vi.mocked(api.setTeam).mockResolvedValue({ teams: [] });
    await expect(
      teams.setTeamAction(idleAction, formOf({ name: " Data Platform " })),
    ).resolves.toEqual({ ok: true, message: "Team Data Platform saved." });
    expect(api.setTeam).toHaveBeenCalledWith("acme", "data-platform", "Data Platform");

    vi.mocked(api.setTeamMember).mockResolvedValue({ teams: [] });
    await teams.addTeamMemberAction(
      idleAction,
      formOf({ team: "data-platform", member: "workspace|anthropic|ws|1" }),
    );
    expect(api.setTeamMember).toHaveBeenCalledWith(
      "acme",
      "data-platform",
      "workspace",
      "anthropic",
      "ws|1",
    );
  });

  it("refuses a name whose slug another team holds instead of renaming that team", async () => {
    vi.mocked(api.teams).mockResolvedValue({
      teams: [{ slug: "data-platform", name: "Data platform", members: [] }],
    });
    await expect(
      teams.setTeamAction(idleAction, formOf({ name: "Data  Platform!" })),
    ).resolves.toEqual({
      ok: false,
      message: "The team Data platform already uses this name; choose another one.",
      field: "name",
    });
    expect(api.setTeam).not.toHaveBeenCalled();
  });

  it("refuses a write posted from a tab that showed another organization", async () => {
    await expect(
      teams.deleteTeamAction(idleAction, formOf({ org: "other", team: "growth" })),
    ).resolves.toEqual({
      ok: false,
      message:
        "This tab shows other but acme was opened in another tab; reload before changing anything.",
    });
    expect(api.deleteTeam).not.toHaveBeenCalled();
  });

  it("refuses a name without letters or digits and an empty choice", async () => {
    await expect(teams.setTeamAction(idleAction, formOf({ name: "---" }))).resolves.toMatchObject({
      ok: false,
      field: "name",
    });
    await expect(
      teams.addTeamMemberAction(idleAction, formOf({ team: "x", member: "" })),
    ).resolves.toMatchObject({ ok: false, field: "member" });
    expect(api.setTeamMember).not.toHaveBeenCalled();
  });
});
