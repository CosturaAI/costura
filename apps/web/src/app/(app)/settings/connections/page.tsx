import type { Metadata } from "next";
import { CardHeading } from "@/components/card-heading";
import { CouldNotLoad } from "@/components/could-not-load";
import { RemovalFeedback } from "@/components/form-feedback";
import { KeyStorageNotice } from "@/components/notice";
import { StatusBadge } from "@/components/status-badge";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { api, type Account, type Connection, type ProviderInfo } from "@/lib/api";
import { formatMinute, formatRelative } from "@/lib/format";
import type { ScopeConnections } from "@/lib/scope";

import {
  AddAccountForm,
  CodexCreditPriceSchedule,
  ConnectForm,
  CursorSettingsForm,
  DisconnectForm,
  RemoveAccountForm,
  RenameAccountForm,
  ReplaceKeyForm,
} from "../connection-forms";
import { loadSettings } from "../data";

export const metadata: Metadata = { title: "Connections" };

/**
 * Connections section: one card per provider in scope, the place where this organization
 * hands Costura an access it did not have. A connected provider shows
 * its accounts, each with its key hint and when it was last checked; the field that replaces
 * a key opens on demand; "Add account" connects one more console of the same
 * provider. Under `all` every registered provider gets a card.
 */
export default async function ConnectionsSettingsPage() {
  const settings = await loadSettings();
  const { org, scope, isDemo, isOwner, canOperate, canManage, hasSecret, writesOff } = settings;
  if (isDemo) return <SampleConnections scope={scope} />;
  const providerGroups = [
    ...scope.providers
      .map((info, index) => ({ info, connection: scope.connections[index]! }))
      .reduce((groups, entry) => {
        const entries = groups.get(entry.info.vendor) ?? [];
        entries.push(entry);
        groups.set(entry.info.vendor, entries);
        return groups;
      }, new Map<string, { info: ProviderInfo; connection: Connection }[]>()),
  ];
  const codexAccounts =
    scope.connections.find((connection) => connection.provider === "codex")?.accounts ?? [];
  const codexPriceEntries = await Promise.all(
    codexAccounts
      .filter((account) => account.connected)
      .map(
        async (account) =>
          [account.id, await api.creditPrices(org, account.id).catch(() => null)] as const,
      ),
  );
  const codexPrices = new Map(codexPriceEntries);

  return (
    <>
      {canManage && !hasSecret ? <KeyStorageNotice /> : null}

      {providerGroups.map(([vendor, entries]) => (
        <section key={vendor} className="space-y-3" aria-labelledby={`vendor-${vendor}`}>
          <p id={`vendor-${vendor}`} className="text-sm font-semibold text-secondary-foreground">
            {vendor}
          </p>
          {entries.map(({ info, connection }) => (
            <ConnectionCard
              key={info.provider}
              org={org}
              info={info}
              connection={connection}
              canWrite={canManage && hasSecret}
              canOperate={canOperate}
              codexPrices={codexPrices}
              isOwner={isOwner}
              isDemo={isDemo}
              writesOff={writesOff}
            />
          ))}
        </section>
      ))}
    </>
  );
}

/**
 * The sample organization's connections: the providers it holds data for and their accounts,
 * with no key and nothing to connect. Providers outside the sample are named once at the end.
 */
function SampleConnections({ scope }: { scope: ScopeConnections }) {
  const entries = scope.providers.map((info, index) => ({
    info,
    connection: scope.connections[index],
  }));
  const shown = entries.filter(({ connection }) => connection!.accounts.length > 0);
  const absent = entries.filter(({ connection }) => connection!.accounts.length === 0);
  return (
    <>
      {shown.map(({ info, connection }) => (
        <Card key={info.provider}>
          <CardHeader>
            <CardHeading className="flex items-center gap-3">
              {info.label}
              <StatusBadge tone="info">sample</StatusBadge>
              {info.experimental ? <StatusBadge tone="warning">experimental</StatusBadge> : null}
            </CardHeading>
            <CardDescription>
              In your organization this card holds the {info.key_label} Costura reads costs, usage
              and inventory with. Here the data is generated: no key is stored.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="divide-y divide-border text-sm" aria-label={`${info.label} accounts`}>
              {connection!.accounts.map((account) => (
                <li
                  key={account.id}
                  className="flex flex-wrap items-center gap-2 py-2 first:pt-0 last:pb-0"
                >
                  <span className="font-medium text-foreground">{account.label}</span>
                  {account.external_id ? (
                    <span className="font-mono text-xs text-muted-foreground">
                      {account.external_id}
                    </span>
                  ) : null}
                  {account.schedule.last_run_at ? (
                    <span className="text-muted-foreground">
                      refreshed{" "}
                      <time dateTime={account.schedule.last_run_at}>
                        {formatRelative(account.schedule.last_run_at)} (
                        {formatMinute(account.schedule.last_run_at)})
                      </time>
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ))}
      {absent.length > 0 ? (
        <p className="text-sm text-muted-foreground">
          {absent.map(({ info }) => info.label).join(" and ")} {absent.length === 1 ? "is" : "are"}{" "}
          supported but not part of the sample.
        </p>
      ) : null}
    </>
  );
}

/**
 * One provider connection. The card answers three questions in order: is it working, which
 * key is it using, and what can be done about it. A provider is one card whatever the number
 * of accounts behind it: each account is a row with its own key, state and
 * actions, and "Add account" connects one more console. The key field is not one of the
 * questions while a key works, so it lives behind "Replace key".
 */
function ConnectionCard({
  org,
  info,
  connection,
  canWrite,
  canOperate,
  codexPrices,
  isOwner,
  isDemo,
  writesOff,
}: {
  org: string;
  info: ProviderInfo;
  connection: Connection;
  /** Whether the forms render: writes on, secret configured, owner, not the sample. */
  canWrite: boolean;
  canOperate: boolean;
  /** Null for an account whose rates did not load; that row says so and the rest renders. */
  codexPrices: Map<number, Awaited<ReturnType<typeof api.creditPrices>> | null>;
  isOwner: boolean;
  isDemo: boolean;
  /** Whether the instance itself refuses browser writes (the sentence, not the forms). */
  writesOff: boolean;
}) {
  const accounts = connection.accounts;
  const several = accounts.length > 1;
  return (
    <Card>
      <CardHeader>
        <CardHeading
          id={`connection-${info.provider}-heading`}
          tabIndex={-1}
          className="flex items-center gap-3"
        >
          {info.label}
          {info.experimental ? <StatusBadge tone="warning">experimental</StatusBadge> : null}
          {connection.connected ? (
            <StatusBadge tone={connection.last_error ? "critical" : "success"}>
              {connection.last_error ? "error" : "connected"}
            </StatusBadge>
          ) : (
            <StatusBadge tone="neutral">not connected</StatusBadge>
          )}
          {several ? (
            <span className="text-sm font-normal text-muted-foreground">
              {accounts.length} accounts
            </span>
          ) : null}
        </CardHeading>
        <CardDescription>
          The {info.key_label} Costura reads costs, usage and inventory with. Read-only at the
          provider; stored encrypted.
          {info.console_url ? (
            <>
              {" "}
              Create one in the{" "}
              <a
                href={info.console_url}
                target="_blank"
                rel="noreferrer"
                className="text-primary hover:underline"
              >
                {info.console_label}
              </a>
              .
            </>
          ) : null}
          {several
            ? ` Rows from ${info.label} carry the account they came from, and Analyze can group or filter by it.`
            : null}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <RemovalFeedback headingId={`connection-${info.provider}-heading`}>
          {connection.last_error && !accounts.some((a) => a.last_error) ? (
            <p className="text-sm text-severity-critical">{connection.last_error}</p>
          ) : null}
          {accounts.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No {info.label} key for this organization. Nothing syncs from {info.label} until one
              is connected here.
              {isDemo
                ? " The sample organization is read-only. Sign in to your own organization to connect a provider."
                : writesOff
                  ? " Changes from the browser are turned off on this instance."
                  : null}
            </p>
          ) : (
            <ul className="divide-y divide-border" aria-label={`${info.label} accounts`}>
              {accounts.map((account) => (
                <AccountRow
                  key={account.id}
                  org={org}
                  info={info}
                  account={account}
                  canWrite={canWrite}
                  canOperate={canOperate}
                  creditPrices={codexPrices.has(account.id) ? codexPrices.get(account.id)! : []}
                  removable={several}
                  showName={several || account.label !== info.label}
                  showStatus={several}
                />
              ))}
            </ul>
          )}
          {canWrite ? (
            <div className="border-t border-border pt-4">
              {accounts.length === 0 ? (
                <ConnectForm org={org} info={info} />
              ) : (
                <AddAccountForm org={org} info={info} />
              )}
            </div>
          ) : isDemo || isOwner ? null : (
            <p className="text-xs text-muted-foreground">
              An owner of this organization manages this key.
            </p>
          )}
        </RemovalFeedback>
      </CardContent>
    </Card>
  );
}

/**
 * One account of the provider: its name (when it differs from the provider's), the state of
 * its key and the actions on it. Remove is offered only while another account remains.
 */
function AccountRow({
  org,
  info,
  account,
  canWrite,
  canOperate,
  creditPrices,
  removable,
  showName,
  showStatus,
}: {
  org: string;
  info: ProviderInfo;
  account: Account;
  canWrite: boolean;
  canOperate: boolean;
  creditPrices: Awaited<ReturnType<typeof api.creditPrices>> | null;
  removable: boolean;
  showName: boolean;
  showStatus: boolean;
}) {
  const stored = account.source === "stored";
  return (
    <li className="space-y-3 py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-2">
        {showName ? (
          <span className="text-sm font-medium text-foreground">{account.label}</span>
        ) : null}
        {showStatus ? (
          account.connected ? (
            <StatusBadge tone={account.last_error ? "critical" : "success"}>
              {account.last_error ? "error" : "connected"}
            </StatusBadge>
          ) : (
            <StatusBadge tone="neutral">not connected</StatusBadge>
          )
        ) : null}
        {account.external_id ? (
          <span className="font-mono text-xs text-muted-foreground">{account.external_id}</span>
        ) : null}
      </div>
      {account.connected ? (
        <p className="text-sm text-secondary-foreground">
          Key <span className="font-mono">...{account.key_hint}</span>{" "}
          {stored ? "(stored)" : "(provided by the instance configuration)"}, checked{" "}
          {account.last_validated_at ? (
            <time dateTime={account.last_validated_at}>
              {formatRelative(account.last_validated_at)} ({formatMinute(account.last_validated_at)}
              )
            </time>
          ) : (
            "never"
          )}
          .
        </p>
      ) : (
        <p className="text-sm text-muted-foreground">
          No key stored for this account; its data stays as last synced.
        </p>
      )}
      {account.last_error ? (
        <p className="text-sm text-severity-critical">{account.last_error}</p>
      ) : null}
      {info.provider === "cursor" && canWrite ? (
        <CursorSettingsForm org={org} account={account} />
      ) : null}
      {info.provider === "codex" && account.connected ? (
        creditPrices === null ? (
          <CouldNotLoad what={`the credit rates of ${account.label}`} />
        ) : (
          <CodexCreditPriceSchedule
            org={org}
            account={account}
            prices={creditPrices}
            canOperate={canOperate}
          />
        )
      ) : null}
      {canWrite ? (
        <ReplaceKeyForm org={org} info={info} account={account}>
          <RenameAccountForm org={org} provider={info.provider} account={account} />
          {stored ? <DisconnectForm org={org} provider={info.provider} account={account} /> : null}
          {removable ? (
            <RemoveAccountForm org={org} provider={info.provider} account={account} />
          ) : null}
        </ReplaceKeyForm>
      ) : null}
    </li>
  );
}
