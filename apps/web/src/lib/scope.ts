import { api, type Connection, type ProviderInfo, type Schedule } from "@/lib/api";
import { isAll, providerLabel } from "@/lib/providers";

/**
 * Connection facts behind a scope. The connection route refuses `all` (400: choose a
 * provider), so the aggregated scope reads one connection per registered provider and the
 * pages derive what they need from the list: whether any key is connected, whether the API
 * accepts writes (the same answer for every provider) and the newest scheduler run.
 */
export type ScopeConnections = {
  /** Registry entries the scope covers: one under a concrete provider, every one under `all`. */
  providers: ProviderInfo[];
  /** Same order as `providers`. */
  connections: Connection[];
};

/** Registry entries a scope covers; a concrete provider absent from the registry gets a stub
 * so the page still renders its name. */
function providersInScope(provider: string, all: ProviderInfo[]): ProviderInfo[] {
  if (isAll(provider)) return all;
  const match = all.filter((p) => p.provider === provider);
  if (match.length > 0) return match;
  return [
    {
      provider,
      connection_type: "provider_api",
      label: providerLabel(provider),
      vendor: providerLabel(provider),
      surface: providerLabel(provider),
      key_label: "admin key",
      key_prefix: "",
      console_label: "provider console",
      console_url: "",
      env_var: "",
      attribution: "token_share",
      experimental: false,
      connected: false,
      source: null,
      key_hint: null,
      last_validated_at: null,
      last_error: null,
      last_run: null,
      accounts: [],
    },
  ];
}

export async function loadScopeConnections(
  org: string,
  provider: string,
  all?: ProviderInfo[],
): Promise<ScopeConnections> {
  const registry = all ?? (await api.providers(org));
  const providers = providersInScope(provider, registry);
  const connections = await Promise.all(providers.map((p) => api.connection(org, p.provider)));
  return { providers, connections };
}

export function anyConnected(scope: ScopeConnections): boolean {
  return scope.connections.some((c) => c.connected);
}

/** Write policy is a property of the API process, so the first connection answers for all. */
export function writesEnabled(scope: ScopeConnections): boolean {
  return scope.connections[0]?.writes_enabled ?? false;
}

export function secretKeyConfigured(scope: ScopeConnections): boolean {
  return scope.connections[0]?.secret_key_configured ?? false;
}

/** The schedule with the newest last run; the first one when nothing has run yet. */
export function newestSchedule(scope: ScopeConnections): Schedule | undefined {
  let best: Schedule | undefined;
  for (const connection of scope.connections) {
    const schedule = connection.schedule;
    if (!best) {
      best = schedule;
      continue;
    }
    if ((schedule.last_run_at ?? "") > (best.last_run_at ?? "")) best = schedule;
  }
  return best;
}
