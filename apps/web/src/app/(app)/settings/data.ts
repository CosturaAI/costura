import { api, type Setup } from "@/lib/api";
import { canManage, canOperate, type Role } from "@/lib/roles";
import {
  loadScopeConnections,
  secretKeyConfigured,
  writesEnabled,
  type ScopeConnections,
} from "@/lib/scope";
import { requireView } from "@/lib/view";

/**
 * What every Settings section needs before it renders: the connections of the scope, the
 * first-run state, and the permissions that decide whether a form appears at all. The
 * sections are separate routes,
 * so this is loaded once per section instead of once for a single long page.
 */
type SettingsScope = {
  org: string;
  provider: string;
  scope: ScopeConnections;
  setup: Setup;
  isDemo: boolean;
  isOwner: boolean;
  /** The caller's role, or null on the sample organization and when the read failed. */
  role: Role | null;
  /** The API accepts browser writes and this is not the read-only sample organization. */
  canWrite: boolean;
  /** `canWrite` plus `owner` or `member`: a viewer changes nothing. */
  canOperate: boolean;
  /** `canWrite` plus the owner role: keys, members and the reset answer 403 below it. */
  canManage: boolean;
  hasSecret: boolean;
  /** The instance itself refuses browser writes (the sentence, not the sample organization). */
  writesOff: boolean;
};

/** An hour past the due time with no run means no daily cycle happened at all. */
const OVERDUE_MS = 60 * 60 * 1000;

/**
 * Whether the automatic import that was due did not run, which is what a scheduler process
 * that is not running looks like from the browser.
 */
export function importOverdue(
  nextRunAt: string | null | undefined,
  now: Date = new Date(),
): boolean {
  if (!nextRunAt) return false;
  return now.getTime() - new Date(nextRunAt).getTime() > OVERDUE_MS;
}

/**
 * The organization comes from the view; the connections and the setup state are
 * required, as the scope layout already treats them.
 */
export async function loadSettings(): Promise<SettingsScope> {
  const { org, provider, organization, registry } = await requireView();
  const [scope, setup] = await Promise.all([
    loadScopeConnections(org, provider, registry),
    api.setup(org),
  ]);
  const isDemo = organization.is_demo;
  const role = organization?.role ?? null;
  const isOwner = canManage(role);
  const canWrite = writesEnabled(scope) && !isDemo;
  return {
    org,
    provider,
    scope,
    setup,
    isDemo,
    isOwner,
    role,
    canWrite,
    canOperate: canWrite && canOperate(role),
    canManage: canWrite && isOwner,
    hasSecret: secretKeyConfigured(scope),
    writesOff: !writesEnabled(scope),
  };
}
