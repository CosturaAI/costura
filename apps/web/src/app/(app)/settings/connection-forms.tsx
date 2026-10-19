"use client";

import { useRouter } from "next/navigation";
import { useActionState, useEffect, useState } from "react";

import { SubmitButton } from "@/components/submit-button";
import { ConfirmSubmit, Feedback, FieldError, invalid } from "@/components/form-feedback";
import { RunStatusPill, SyncProgress } from "@/components/sync-progress";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useOnSuccess } from "@/lib/use-on-success";
import { idleAction, type ActionState } from "@/lib/action-errors";
import type { Account, CreditPrice, ProviderInfo, SchedulerRun } from "@/lib/api";
import { hasAccountLabel, providerLabel } from "@/lib/providers";
import { anyRunning, keyAccess } from "@/lib/setup";

import { getSetupAction } from "@/actions/welcome";

import {
  addCreditPriceAction,
  connectAction,
  deleteCreditPriceAction,
  disconnectAction,
  removeAccountAction,
  renameAccountAction,
  resetSetupAction,
  syncNowAction,
  type SyncState,
} from "./connection-actions";

const idleSync: SyncState = { ok: false, message: null, results: [] };
const POLL_MS = 2000;

type Progress = { source: SyncState; runs: SchedulerRun[]; error: string | null; done: boolean };

/** The organization comes from the view cookie; the card's provider is posted. */
type Scope = { provider: string };

function ScopeInputs({ provider }: Scope) {
  return <input type="hidden" name="provider" value={provider} />;
}

/** Which write the key field performs. */
type ConnectMode = "connect" | "add" | "replace";

/**
 * Key entry for one provider. The key goes to a server action, never to the API from the
 * browser; the registry prefix travels with it so the action can refuse the wrong kind of key.
 * Ids carry the provider and the account because the `all` scope renders one form per
 * provider and a provider may hold several accounts. `mode` picks the write: `connect` for the
 * provider's first key, `add` for one more account (with an optional name), `replace` for the
 * key of `account`. `onConnected` fires once per successful submit (the welcome page starts
 * polling from it); `compact` drops the help line when the surrounding card already explains
 * where the key comes from.
 */
export function ConnectForm({
  info,
  mode = "connect",
  account,
  compact = false,
  onConnected,
}: {
  org: string;
  info: ProviderInfo;
  mode?: ConnectMode;
  /** The account whose key `replace` swaps. */
  account?: Pick<Account, "id" | "label">;
  compact?: boolean;
  onConnected?: () => void;
}) {
  const [state, action, pending] = useActionState(connectAction, idleAction);
  const bad = invalid(state, "admin_key");
  const badLabel = invalid(state, "label");
  const badWorkspace = invalid(state, "workspace_id");
  const badSeatPrice = invalid(state, "seat_price_usd");
  const suffix = account ? `_${account.id}` : mode === "add" ? "_new" : "";
  const id = `${info.provider}${suffix}_admin_key`;
  const labelId = `${info.provider}_new_label`;
  const keyLabel = info.key_label;
  useOnSuccess(state, onConnected);
  return (
    <form action={action} className="space-y-3">
      <ScopeInputs provider={info.provider} />
      <input type="hidden" name="key_prefix" value={info.key_prefix} />
      <input type="hidden" name="key_label" value={keyLabel} />
      <input type="hidden" name="mode" value={mode} />
      {account ? <input type="hidden" name="account_id" value={account.id} /> : null}
      {mode === "add" ? (
        <div>
          <label className="block text-sm font-medium text-secondary-foreground" htmlFor={labelId}>
            Account name <span className="font-normal text-muted-foreground">(optional)</span>
          </label>
          <Input
            id={labelId}
            name="label"
            type="text"
            maxLength={120}
            placeholder={`What ${info.label} calls it, unless named here`}
            className="mt-1 h-9 max-w-md"
            aria-invalid={badLabel || undefined}
            aria-describedby={badLabel ? `${labelId}_error` : undefined}
          />
          <FieldError state={state} field="label" id={`${labelId}_error`} />
        </div>
      ) : null}
      {info.provider === "cursor" && mode !== "replace" ? (
        <CursorSettingsFields
          seatPrice=""
          includeIncluded
          badSeatPrice={badSeatPrice}
          state={state}
          idSuffix={suffix || "_connect"}
        />
      ) : null}
      {info.provider === "copilot" && mode !== "replace" ? (
        <div>
          <label
            className="block text-sm font-medium text-secondary-foreground"
            htmlFor={`${info.provider}${suffix}_workspace_id`}
          >
            GitHub organization
          </label>
          <Input
            id={`${info.provider}${suffix}_workspace_id`}
            name="workspace_id"
            type="text"
            placeholder="acme-inc"
            className="mt-1 h-9 max-w-md font-mono"
            required
            aria-invalid={badWorkspace || undefined}
          />
          <FieldError
            state={state}
            field="workspace_id"
            id={`${info.provider}${suffix}_workspace_id_error`}
          />
        </div>
      ) : null}
      {info.provider === "codex" && mode !== "replace" ? (
        <div>
          <label
            className="block text-sm font-medium text-secondary-foreground"
            htmlFor={`${info.provider}${suffix}_workspace_id`}
          >
            Workspace ID
          </label>
          <Input
            id={`${info.provider}${suffix}_workspace_id`}
            name="workspace_id"
            type="text"
            placeholder="00000000-0000-0000-0000-000000000000"
            className="mt-1 h-9 max-w-md font-mono"
            required
            aria-invalid={badWorkspace || undefined}
          />
          <FieldError
            state={state}
            field="workspace_id"
            id={`${info.provider}${suffix}_workspace_id_error`}
          />
        </div>
      ) : null}
      <div>
        <label className="block text-sm font-medium text-secondary-foreground" htmlFor={id}>
          {mode === "replace"
            ? `New ${keyLabel}${account && hasAccountLabel(info.provider, account.label) ? ` for ${account.label}` : ""}`
            : mode === "add"
              ? `${keyLabel} of the account`
              : `${info.label} ${keyLabel}`}
        </label>
        <div className="mt-1 flex flex-wrap gap-2">
          <Input
            id={id}
            name="admin_key"
            type="password"
            autoComplete="off"
            placeholder={info.key_prefix ? `${info.key_prefix}...` : undefined}
            className="h-9 max-w-md flex-1 font-mono"
            required
            aria-invalid={bad || undefined}
            aria-describedby={bad ? `${id}_error` : compact ? undefined : `${id}_help`}
          />
          <SubmitButton size="lg" pending={pending}>
            {pending
              ? "Validating..."
              : mode === "replace"
                ? "Replace key"
                : mode === "add"
                  ? "Add account"
                  : "Connect"}
          </SubmitButton>
        </div>
        <FieldError state={state} field="admin_key" id={`${id}_error`} />
        {compact ? null : (
          <p id={`${id}_help`} className="mt-1 text-xs text-muted-foreground">
            Checked with one read-only request before it is stored encrypted
            {info.key_prefix ? (
              <>
                ; it starts with <code className="font-mono">{info.key_prefix}</code>
              </>
            ) : null}
            . {keyAccess(info.provider)?.risk ?? null}
          </p>
        )}
      </div>
      <Feedback state={state} />
    </form>
  );
}

function CursorSettingsFields({
  seatPrice,
  includeIncluded,
  badSeatPrice,
  state,
  idSuffix,
}: {
  seatPrice: string;
  includeIncluded: boolean;
  badSeatPrice: boolean;
  state: ActionState;
  idSuffix: string;
}) {
  const priceId = `cursor${idSuffix}_seat_price`;
  return (
    <fieldset className="grid gap-3 rounded-md border border-border p-3 sm:grid-cols-2">
      <legend className="px-1 text-sm font-medium text-secondary-foreground">
        Cursor billing settings
      </legend>
      <div>
        <label className="block text-sm text-secondary-foreground" htmlFor={priceId}>
          Monthly seat price (USD)
        </label>
        <Input
          id={priceId}
          name="seat_price_usd"
          type="number"
          min="0"
          step="0.01"
          defaultValue={seatPrice}
          required
          className="mt-1 h-9"
          aria-invalid={badSeatPrice || undefined}
        />
        <FieldError state={state} field="seat_price_usd" id={`${priceId}_error`} />
      </div>
      <label className="flex items-center gap-2 self-end pb-2 text-sm text-secondary-foreground">
        <input
          name="include_included_in_business"
          type="checkbox"
          defaultChecked={includeIncluded}
        />
        Include Included in Business usage
      </label>
    </fieldset>
  );
}

export function CursorSettingsForm({
  account,
}: {
  account: Pick<
    Account,
    "id" | "label" | "seat_price_usd" | "include_included_in_business" | "settings_effective_from"
  >;
}) {
  const [state, action, pending] = useActionState(renameAccountAction, idleAction);
  return (
    <form action={action} className="space-y-2 rounded-md bg-background p-3">
      <ScopeInputs provider="cursor" />
      <input type="hidden" name="account_id" value={account.id} />
      <input type="hidden" name="label" value={account.label} />
      <CursorSettingsFields
        seatPrice={account.seat_price_usd ?? "0"}
        includeIncluded={account.include_included_in_business ?? true}
        badSeatPrice={invalid(state, "seat_price_usd")}
        state={state}
        idSuffix={`_${account.id}_edit`}
      />
      <p className="text-xs text-muted-foreground">
        Seat price changes take effect tomorrow. Existing seat lines keep their stored price.
      </p>
      <SubmitButton size="sm" pending={pending}>
        {pending ? "Saving..." : "Save billing settings"}
      </SubmitButton>
      <Feedback state={state} />
    </form>
  );
}

export function CodexCreditPriceSchedule({
  account,
  prices,
  canOperate,
}: {
  account: Pick<Account, "id" | "label">;
  prices: CreditPrice[];
  canOperate: boolean;
}) {
  const [state, action, pending] = useActionState(addCreditPriceAction, idleAction);
  const dateId = `codex_${account.id}_effective_from`;
  const priceId = `codex_${account.id}_price_per_credit`;
  return (
    <section
      className="space-y-3 rounded-md border border-border p-3"
      aria-label={`${account.label} credit price schedule`}
    >
      <div>
        <p className="text-sm font-medium text-foreground">Credit price schedule</p>
        <p className="text-xs text-muted-foreground">
          Codex credit costs use the rate effective on each usage day.
        </p>
      </div>
      {prices.length === 0 ? (
        <div
          role="alert"
          className="rounded-md border border-severity-warning/30 bg-severity-warning-bg p-3 text-sm text-secondary-foreground"
        >
          Pricing required. Usage can sync, but Costura will not create USD cost rows until a credit
          rate covers the usage date.
        </div>
      ) : (
        <ul className="divide-y divide-border" aria-label="Effective credit rates">
          {prices.map((price) => (
            <CodexCreditPriceRow
              key={price.id}
              accountId={account.id}
              price={price}
              canOperate={canOperate}
            />
          ))}
        </ul>
      )}
      <form action={action} className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
        <div>
          <label className="block text-xs font-medium text-secondary-foreground" htmlFor={dateId}>
            Effective from
          </label>
          <Input
            id={dateId}
            name="effective_from"
            type="date"
            required
            disabled={!canOperate}
            aria-invalid={invalid(state, "effective_from") || undefined}
          />
          <FieldError state={state} field="effective_from" id={`${dateId}_error`} />
        </div>
        <div>
          <label className="block text-xs font-medium text-secondary-foreground" htmlFor={priceId}>
            USD per credit
          </label>
          <Input
            id={priceId}
            name="price_per_credit"
            type="number"
            min="0.00000001"
            step="0.00000001"
            inputMode="decimal"
            required
            disabled={!canOperate}
            aria-invalid={invalid(state, "price_per_credit") || undefined}
          />
          <FieldError state={state} field="price_per_credit" id={`${priceId}_error`} />
        </div>
        <input type="hidden" name="account_id" value={account.id} />
        {canOperate ? (
          <SubmitButton size="sm" className="self-end" pending={pending}>
            {pending ? "Adding..." : "Add rate"}
          </SubmitButton>
        ) : null}
        <Feedback state={state} className="sm:col-span-3" />
      </form>
      {!canOperate ? (
        <p className="text-xs text-muted-foreground">
          An owner or member of this organization manages credit rates.
        </p>
      ) : null}
    </section>
  );
}

function CodexCreditPriceRow({
  accountId,
  price,
  canOperate,
}: {
  accountId: number;
  price: CreditPrice;
  canOperate: boolean;
}) {
  const [state, action, pending] = useActionState(deleteCreditPriceAction, idleAction);
  const formId = `delete-credit-price-${accountId}-${price.id}`;
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 py-2">
      <p className="text-sm text-secondary-foreground">
        <time dateTime={price.effective_from}>{price.effective_from}</time>
        {" - "}
        <span className="font-mono text-foreground">{price.price_per_credit} USD</span>
      </p>
      {canOperate ? (
        <form id={formId} action={action} className="flex items-center gap-2">
          <input type="hidden" name="account_id" value={accountId} />
          <input type="hidden" name="price_id" value={price.id} />
          <ConfirmSubmit
            formId={formId}
            title="Delete this credit rate?"
            description="Usage on or after this date will fall back to the previous rate. Days with no earlier rate will have no USD cost."
            confirmLabel="Delete rate"
            pending={pending}
          >
            {pending ? "Deleting..." : "Delete"}
          </ConfirmSubmit>
          <Feedback state={state} />
        </form>
      ) : null}
    </li>
  );
}

/**
 * The key field of a connected account, behind a button. A working connection needs no input,
 * so the form that replaces the key stays out of the way until it is asked for;
 * the field itself is the same `ConnectForm` the welcome page uses. `children` (Disconnect,
 * Rename, Remove) sit beside the button and step aside while the field is open, so replacing
 * a key is one task at a time.
 */
export function ReplaceKeyForm({
  org,
  info,
  account,
  children,
}: {
  org: string;
  info: ProviderInfo;
  account: Pick<Account, "id" | "label" | "source">;
  children?: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const stored = account.source === "stored";
  if (!open) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" variant="outline" size="sm" onClick={() => setOpen(true)}>
          {stored ? "Replace key" : "Connect a key"}
        </Button>
        {children}
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <ConnectForm org={org} info={info} mode={stored ? "replace" : "connect"} account={account} />
      <Button type="button" variant="ghost" size="sm" onClick={() => setOpen(false)}>
        Cancel
      </Button>
    </div>
  );
}

/**
 * "Add account" for a provider that already has one: the field (with the optional name) opens
 * on demand, since most organizations hold one console per provider.
 */
export function AddAccountForm({ org, info }: { org: string; info: ProviderInfo }) {
  const [open, setOpen] = useState(false);
  if (!open) {
    return (
      <Button type="button" variant="outline" size="sm" onClick={() => setOpen(true)}>
        Add account
      </Button>
    );
  }
  return (
    <div className="space-y-2 rounded-md border border-border p-3">
      <ConnectForm org={org} info={info} mode="add" />
      <Button type="button" variant="ghost" size="sm" onClick={() => setOpen(false)}>
        Cancel
      </Button>
    </div>
  );
}

/** Forgets the key of one account (or of the provider's only account when none is named). */
export function DisconnectForm({ provider, account }: Scope & { account?: number }) {
  const [state, action, pending] = useActionState(disconnectAction, idleAction);
  const formId = `disconnect-form-${provider}${account === undefined ? "" : `-${account}`}`;
  return (
    <form id={formId} action={action} className="flex flex-wrap items-center gap-3">
      <ScopeInputs provider={provider} />
      {account === undefined ? null : <input type="hidden" name="account_id" value={account} />}
      <ConfirmSubmit
        formId={formId}
        title="Remove the stored key?"
        description="The daily sync of this account stops until another key is connected. Data already synced stays."
        confirmLabel="Remove key"
        pending={pending}
        size="lg"
      >
        {pending ? "Removing..." : "Disconnect"}
      </ConfirmSubmit>
      <Feedback state={state} />
    </form>
  );
}

/** Renames one account; the name is what rows show after the provider ("OpenAI - Acme"). */
export function RenameAccountForm({
  provider,
  account,
}: Scope & { account: Pick<Account, "id" | "label"> }) {
  const [openedFor, setOpenedFor] = useState<typeof idleAction | null>(null);
  const [state, action, pending] = useActionState(renameAccountAction, idleAction);
  const id = `${provider}_${account.id}_label`;
  const bad = invalid(state, "label");
  // The field stays open until the action answers ok: a success closes it, an error keeps it.
  const open = openedFor !== null && !(state.ok && openedFor !== state);
  const setOpen = (next: boolean) => setOpenedFor(next ? state : null);
  if (!open) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" variant="ghost" size="sm" onClick={() => setOpen(true)}>
          Rename
        </Button>
        <Feedback state={state} />
      </div>
    );
  }
  return (
    <form action={action} className="flex flex-wrap items-end gap-2">
      <ScopeInputs provider={provider} />
      <input type="hidden" name="account_id" value={account.id} />
      <div>
        <label className="block text-sm font-medium text-secondary-foreground" htmlFor={id}>
          Account name
        </label>
        <Input
          id={id}
          name="label"
          type="text"
          defaultValue={account.label}
          maxLength={120}
          required
          className="mt-1 h-9 w-64"
          aria-invalid={bad || undefined}
          aria-describedby={bad ? `${id}_error` : undefined}
        />
        <FieldError state={state} field="label" id={`${id}_error`} />
      </div>
      <SubmitButton size="sm" pending={pending}>
        {pending ? "Saving..." : "Save"}
      </SubmitButton>
      <Button type="button" variant="ghost" size="sm" onClick={() => setOpen(false)}>
        Cancel
      </Button>
      <Feedback state={state} />
    </form>
  );
}

/** Removes an account with every row synced under it; only offered once the provider has
 * another account, so a provider never loses its last console by accident. */
export function RemoveAccountForm({
  provider,
  account,
}: Scope & { account: Pick<Account, "id" | "label"> }) {
  const [state, action, pending] = useActionState(removeAccountAction, idleAction);
  const formId = `remove-account-form-${provider}-${account.id}`;
  return (
    <form id={formId} action={action} className="flex flex-wrap items-center gap-3">
      <ScopeInputs provider={provider} />
      <input type="hidden" name="account_id" value={account.id} />
      <ConfirmSubmit
        formId={formId}
        title={`Remove the account ${account.label}?`}
        description="Its key and every record synced from it go: spend, usage, inventory, runs, anomalies and projections. The other accounts of the provider stay."
        confirmLabel="Remove account"
        variant="destructive"
        pending={pending}
        size="lg"
      >
        {pending ? "Removing..." : "Remove"}
      </ConfirmSubmit>
      <Feedback state={state} />
    </form>
  );
}

/**
 * Starts the organization over from the welcome screen. The dialog names what goes; on
 * success the action redirects, so the form only ever renders a refusal. `syncActive` holds
 * the button while a run is queued or running because reset never waits for the lock.
 */
export function ResetSetupForm({ syncActive = false }: { syncActive?: boolean }) {
  const [state, action, pending] = useActionState(resetSetupAction, idleAction);
  return (
    <form id="reset-setup-form" action={action} className="space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <ConfirmSubmit
          formId="reset-setup-form"
          title="Reset the onboarding of this organization?"
          description="Removes the stored provider keys and every synced record for this organization: spend, inventory, runs, anomalies, projections and budgets. The next visit starts at the welcome screen."
          confirmLabel="Reset everything"
          variant="destructive"
          size="lg"
          pending={pending}
          disabled={syncActive}
          aria-describedby={syncActive ? "reset-setup-wait" : undefined}
        >
          {pending ? "Resetting..." : "Reset onboarding"}
        </ConfirmSubmit>
        <Feedback state={state} />
      </div>
      {syncActive ? (
        <p id="reset-setup-wait" className="text-xs text-muted-foreground">
          Wait for the queued or running import to finish.
        </p>
      ) : null}
    </form>
  );
}

/**
 * Starts a run for every provider in scope (the API answers 202 at once) and follows the runs
 * through `setup` every two seconds until none is queued or running, one table per provider. The
 * page data is refreshed at the end so the "Last run" rows pick the result up.
 */
export function SyncNowForm({ org, provider, hint }: Scope & { org: string; hint?: string }) {
  const router = useRouter();
  const [state, action, pending] = useActionState(syncNowAction, idleSync);
  // Keyed by the action result that started it, so a new submit starts from a clean table.
  const [progress, setProgress] = useState<Progress | null>(null);
  const current = progress?.source === state ? progress : null;
  const runs = current?.runs ?? [];
  const started = state.results.some((r) => r.status === "queued" || r.status === "running");
  const tracking = started && !current?.done;

  useEffect(() => {
    if (!tracking) return;
    const ids = state.results
      .filter((r) => r.status === "queued" || r.status === "running")
      .map((r) => r.run_id);
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      const result = await getSetupAction(org);
      if (cancelled) return;
      if (result.error !== null) {
        setProgress((prev) => ({
          source: state,
          runs: prev?.source === state ? prev.runs : [],
          error: result.error,
          done: false,
        }));
        timer = setTimeout(() => void poll(), POLL_MS);
        return;
      }
      // `setup.runs` keeps the latest run per provider: a run that vanished was superseded by
      // a newer one (scheduler tick), so there is nothing left to follow.
      const own = result.setup.runs.filter((run) => ids.includes(run.id));
      const done = own.length === 0 || !anyRunning(own);
      setProgress({ source: state, runs: own, error: null, done });
      if (done) router.refresh();
      else timer = setTimeout(() => void poll(), POLL_MS);
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [state, tracking, org, router]);

  const busy = pending || tracking;
  const pollError = current?.error ?? null;
  return (
    <div className="space-y-3">
      <form action={action} className="flex flex-wrap items-center gap-3">
        <ScopeInputs provider={provider} />
        <Button type="submit" variant="secondary" size="lg" disabled={busy}>
          {pending ? "Starting..." : tracking ? "Syncing..." : "Sync now"}
        </Button>
        <Feedback state={state} />
      </form>
      {hint && !busy ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      {tracking ? (
        <p className="text-xs text-muted-foreground">
          Fetching the recent months of reports; this takes from seconds to a few minutes. Steps
          appear as they finish.
        </p>
      ) : null}
      {pollError ? <p className="text-sm text-severity-critical">{pollError}</p> : null}
      {runs.map((run) => (
        <section
          key={run.id}
          className="space-y-2"
          aria-label={`${providerLabel(run.provider)} sync`}
        >
          <div className="flex items-center gap-2 text-sm">
            {runs.length > 1 || state.results.length > 1 ? (
              <span className="font-medium">{providerLabel(run.provider)}</span>
            ) : null}
            <RunStatusPill status={run.status} />
          </div>
          <SyncProgress run={run} caption={`${providerLabel(run.provider)} steps`} />
        </section>
      ))}
    </div>
  );
}
