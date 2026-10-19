import { Notice, WritesDisabledNotice } from "@/components/notice";
import { PageHeader } from "@/components/page-header";
import { newestSchedule } from "@/lib/scope";

import { loadSettings } from "./data";
import { SettingsNav, type SettingsNavItem } from "./nav";

/**
 * Shell of the Settings sections: the page title, the instance-level notices, and the section
 * navigation. Each section is its own route, grouped by whose setting it is: the organization
 * (connections, sync, anomaly detection, members, the reset) or the caller (alerts,
 * sessions). Navigation follows a scope-first settings layout.
 * Sections a caller cannot act in are left out of the rail and answer 404: Audit and Advanced
 * need the owner role, Account needs an organization of one's own (the sample one has no members).
 * The sample organization opens on how it is configured, then shows Connections, Sync and
 * Anomalies as read-only previews; it has no members and no name to change.
 */
export default async function SettingsLayout({ children }: { children: React.ReactNode }) {
  const settings = await loadSettings();
  const { scope, isDemo, canManage, writesOff } = settings;
  const keyError = scope.connections.some((connection) => connection.last_error !== null);
  const runFailed = newestSchedule(scope)?.status === "failed";

  const items: SettingsNavItem[] = isDemo
    ? [
        { segment: "sample", label: "How it is configured", group: "Sample" },
        { segment: "connections", label: "Connections", group: "Sample" },
        { segment: "sync", label: "Sync", group: "Sample" },
        { segment: "anomalies", label: "Anomalies", group: "Sample" },
      ]
    : [
        { segment: "organization", label: "Organization", group: "Organization" },
        {
          segment: "connections",
          label: "Connections",
          group: "Organization",
          attention: keyError,
        },
        { segment: "sync", label: "Sync", group: "Organization", attention: runFailed },
        { segment: "anomalies", label: "Anomalies", group: "Organization" },
        { segment: "members", label: "Members", group: "Organization" },
        { segment: "teams", label: "Teams", group: "Organization" },
      ];
  if (!isDemo && settings.isOwner) {
    items.push({ segment: "audit", label: "Audit", group: "Organization" });
  }
  if (canManage) {
    items.push({ segment: "advanced", label: "Advanced", group: "Organization" });
  }
  if (!isDemo) {
    items.push({ segment: "account", label: "Account", group: "You" });
  }

  return (
    <div className="space-y-5">
      <PageHeader title="Settings" />
      {isDemo ? (
        <Notice>
          This is the sample organization: these sections show how it is set up, and nothing here
          can be changed. Connect a provider in your own organization to see real spend.
        </Notice>
      ) : writesOff ? (
        <WritesDisabledNotice />
      ) : null}
      <div className="flex flex-col gap-5 lg:flex-row lg:gap-10">
        <SettingsNav items={items} />
        <div className="max-w-2xl min-w-0 flex-1 space-y-5">{children}</div>
      </div>
    </div>
  );
}
