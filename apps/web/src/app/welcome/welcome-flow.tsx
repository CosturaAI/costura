"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ConnectForm } from "@/app/(app)/settings/connection-forms";
import { CardHeading } from "@/components/card-heading";
import { WritesDisabledNotice } from "@/components/notice";
import { SampleEntry } from "@/components/sample-entry";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
import type { ProviderInfo, Setup } from "@/lib/api";
import { formatMonth } from "@/lib/format";
import { keyAccess, keyHint, openOrgHref, overviewHref } from "@/lib/setup";

/**
 * The connect step: a picker of the providers without a key and one card for the chosen one,
 * with where the key is created and what it must be allowed to read. An accepted key sends
 * the browser to the overview, where the sync banner follows the first import. An
 * organization that already has a key (or data) keeps the picker for the remaining providers
 * under a header that says so and links to the overview.
 */
export function WelcomeFlow({
  org,
  setup,
  demoOrg,
  canConnect = true,
}: {
  org: string;
  setup: Setup;
  /** Only an owner stores keys; members and viewers get a note instead of the forms. */
  canConnect?: boolean;
  /** Slug of the read-only sample organization, or null when none is seeded. */
  demoOrg: string | null;
}) {
  const router = useRouter();
  const fresh = setup.state === "connect";
  const overview = overviewHref();
  const unconnected = setup.providers.filter((p) => !p.connected);
  const connected = setup.providers.filter((p) => p.connected);
  const onConnected = () => router.push(overviewHref());
  const [chosen, setChosen] = useState(unconnected[0]?.provider ?? "");
  const current = unconnected.find((p) => p.provider === chosen) ?? unconnected[0];

  return (
    <main id="main" tabIndex={-1} className="mx-auto w-full max-w-xl space-y-6 px-4 py-10 sm:py-16">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          {fresh
            ? "See your LLM spend in about two minutes."
            : setup.state === "ready"
              ? `This organization already has data: ${
                  setup.first_month ? formatMonth(setup.first_month) : "its first month"
                } is in.`
              : "This organization is already importing."}
        </h1>
        <p className="text-sm text-muted-foreground">
          {fresh
            ? "Costura checks each key with one read-only request and stores it encrypted; it never writes to the provider."
            : connected.length > 0
              ? `${connected.map((p) => p.label).join(" and ")} ${connected.length === 1 ? "is" : "are"} connected. Add another provider below, or open the overview.`
              : "Open the overview to see it."}
        </p>
        {!fresh ? (
          <p className="pt-2">
            <Button asChild size="lg">
              <Link href={overview}>Open overview</Link>
            </Button>
          </p>
        ) : null}
      </header>

      {!setup.writes_enabled ? <WritesDisabledNotice /> : null}
      {setup.secret_ready === false ? (
        <p className="text-sm text-muted-foreground">
          This deployment has no COSTURA_SECRET_KEY, so a key typed here cannot be stored. Generate
          one with <span className="font-medium">just api::secret-generate</span> and restart the
          API.
        </p>
      ) : null}
      {setup.needs_pricing ? (
        <p className="text-sm text-muted-foreground">
          Codex is connected and still needs a credit price. Until that price is saved, imported
          lines stay unpriced. Set it under Settings, Connections.
        </p>
      ) : null}

      {setup.writes_enabled && canConnect && current ? (
        <div className="space-y-3">
          {unconnected.length > 1 ? (
            <div className="space-y-1">
              <label htmlFor="welcome-provider" className="text-sm font-medium text-foreground">
                Provider to connect
              </label>
              <NativeSelect
                id="welcome-provider"
                value={current.provider}
                onChange={(event) => setChosen(event.target.value)}
                className="w-full"
              >
                {unconnected.map((info) => (
                  <option key={info.provider} value={info.provider}>
                    {info.label}
                  </option>
                ))}
              </NativeSelect>
            </div>
          ) : null}
          <ConnectCard key={current.provider} org={org} info={current} onConnected={onConnected} />
        </div>
      ) : null}
      {setup.writes_enabled && !canConnect && unconnected.length > 0 ? (
        <p className="text-sm text-muted-foreground">
          Only an owner of this organization can connect a provider key. Ask one to add it under
          Settings, Connections.
        </p>
      ) : null}
      {setup.writes_enabled && canConnect && unconnected.length === 0 ? (
        <p className="text-sm text-muted-foreground">Every registered provider is connected.</p>
      ) : null}

      {demoOrg !== null ? (
        <SampleEntry
          href={openOrgHref(demoOrg)}
          title="Explore with sample data first"
          description="A fictional company's thirteen months of synthetic spend: anomalies, budgets, reconciliation and import runs, read-only."
        />
      ) : null}
      <div className="space-y-2 text-sm">
        {fresh ? (
          <p>
            <Link href={overview} className="text-primary hover:underline">
              Skip for now, look around
            </Link>
          </p>
        ) : null}
      </div>
    </main>
  );
}

/** One provider's key entry: console link, the two-line hint, and the shared form. */
function ConnectCard({
  org,
  info,
  onConnected,
}: {
  org: string;
  info: ProviderInfo;
  onConnected: () => void;
}) {
  const [where, how] = keyHint(info);
  const access = keyAccess(info.provider);
  return (
    <Card>
      <CardHeader>
        <CardHeading className="flex items-center gap-3">
          {info.label}
          {info.experimental ? <StatusBadge tone="warning">experimental</StatusBadge> : null}
        </CardHeading>
        <CardDescription>
          Paste the {info.key_label}; the import of recent months starts as soon as it is accepted.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1 text-sm text-muted-foreground">
          <p>{where}</p>
          <p>{how}</p>
          {info.experimental ? (
            <p>
              Experimental connector: it has not run against a live organization yet, so check its
              first month on the Reconciliation page.
            </p>
          ) : null}
          {info.console_url ? (
            <p>
              <a
                href={info.console_url}
                target="_blank"
                rel="noreferrer"
                className="font-medium text-primary hover:underline"
              >
                Open {info.console_label}
              </a>
            </p>
          ) : null}
        </div>
        {access ? (
          <dl className="grid gap-x-3 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
            <dt className="font-medium text-foreground">Spend</dt>
            <dd className="text-muted-foreground">{access.spend}</dd>
            <dt className="font-medium text-foreground">Inventory</dt>
            <dd className="text-muted-foreground">{access.inventory}</dd>
            <dt className="font-medium text-foreground">Key posture</dt>
            <dd className="text-muted-foreground">{access.posture}</dd>
            <dt className="font-medium text-foreground">If it leaks</dt>
            <dd className="text-muted-foreground">{access.risk}</dd>
          </dl>
        ) : null}
        <ConnectForm org={org} info={info} compact onConnected={onConnected} />
      </CardContent>
    </Card>
  );
}
