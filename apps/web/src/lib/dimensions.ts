export const DIMENSION_LABELS: Record<string, string> = {
  api_key: "API key",
  account: "Account",
  creator: "Key creator",
  workspace: "Workspace",
  model: "Model",
  provider: "Provider",
  origin: "Origin",
  provider_account: "Provider account",
  person: "Person",
  team: "Team",
  model_brand: "Model brand",
  model_family: "Model family",
  model_name: "Canonical model",
  model_channel: "Model channel",
  model_lifecycle: "Model lifecycle",
  token_type: "Token type",
  cost_type: "Cost type",
  none: "Total",
};

/**
 * Token counters in display order, shared by the attribution table and the token mix bar.
 * A column renders only when some row carries a non-zero value, so Anthropic rows do not show
 * an empty reasoning column and OpenRouter rows do not show empty cache-write columns.
 */
export const TOKEN_TYPES: { key: string; label: string; short: string }[] = [
  { key: "uncached_input_tokens", label: "Uncached input", short: "Input" },
  { key: "cache_creation_5m_tokens", label: "Cache write 5m", short: "Cache 5m" },
  { key: "cache_creation_1h_tokens", label: "Cache write 1h", short: "Cache 1h" },
  { key: "cache_read_tokens", label: "Cache read", short: "Cache read" },
  { key: "output_tokens", label: "Output", short: "Output" },
  { key: "reasoning_tokens", label: "Reasoning", short: "Reasoning" },
];

/** Token types with a non-zero value in at least one of the token maps. */
export function activeTokenTypes(rows: Record<string, number>[]): typeof TOKEN_TYPES {
  return TOKEN_TYPES.filter((type) => rows.some((tokens) => (tokens[type.key] ?? 0) > 0));
}

export function dimensionLabel(dimension: string): string {
  return DIMENSION_LABELS[dimension] ?? dimension.replace("_", " ");
}

/**
 * API labels for keys and workspaces read "name (provider_id)". The name is what people
 * recognise; the id moves to a secondary line or a tooltip.
 */
export function splitLabel(label: string): { name: string; id: string | null } {
  const match = /^(.*) \(([A-Za-z0-9_-]+)\)$/.exec(label);
  if (!match) return { name: label, id: null };
  return { name: match[1] ?? label, id: match[2] ?? null };
}

/** Ids longer than a readable token (OpenRouter's 64-hex key hash) shrink to their last four
 * characters; the full id goes in the tooltip. Short ids (`apikey_01`, `ws_1`) stay whole. */
const LONG_ID = 24;
export function idHint(id: string): string {
  return id.length > LONG_ID ? `...${id.slice(-4)}` : id;
}

/** The next natural question for each dimension: a key -> its models, a workspace -> its people. */
export const NEXT_DIMENSION: Record<string, { filter: string; by: string }> = {
  api_key: { filter: "api_key", by: "model" },
  account: { filter: "account", by: "model" },
  creator: { filter: "account", by: "model" },
  workspace: { filter: "workspace", by: "person" },
  model: { filter: "model", by: "person" },
  provider: { filter: "provider", by: "person" },
  origin: { filter: "origin", by: "provider" },
  provider_account: { filter: "provider_account", by: "person" },
  person: { filter: "person", by: "provider" },
  model_brand: { filter: "model_brand", by: "model_family" },
  model_family: { filter: "model_family", by: "model_name" },
  model_name: { filter: "model_name", by: "model_channel" },
  model_channel: { filter: "model_channel", by: "model_name" },
  model_lifecycle: { filter: "model_lifecycle", by: "model_name" },
  token_type: { filter: "token_type", by: "model_name" },
};

/**
 * Explore filtered to one row and grouped by the next natural dimension. Used by the "Open in
 * Explore" button on entity pages and by the organization-wide anomaly. Sentinel rows (no
 * provider id) return null.
 */
export function drillDownHref(by: string, key: string | null, groupedBy?: string): string | null {
  if (key === null) return null;
  const target = NEXT_DIMENSION[by];
  if (!target) return null;
  const params = new URLSearchParams({ by: groupedBy ?? target.by });
  params.append("f", `${target.filter}:is:${key}`);
  return `/explore?${params.toString()}`;
}

/** URL segment of the entity page for each dimension; `creator` rows are accounts. */
const ENTITY_SEGMENTS: Record<string, string> = {
  api_key: "keys",
  account: "accounts",
  creator: "accounts",
  workspace: "workspaces",
  model: "models",
  person: "people",
};

/** The person page of one e-mail; the view's scope (`all` or one provider) decides which
 * provider accounts it covers. */
export function personHref(email: string): string {
  return `/people/${encodeURIComponent(email)}`;
}

/**
 * Where a click on a row of dimension `by` leads: the entity page of that key, account,
 * workspace or model. Sentinel rows and dimensions without an entity page return null. The
 * address names no provider: the entity page resolves the provider of the id
 * through the API's lookup route, so a row of the aggregated table opens as itself. Account
 * and creator rows whose `person` is known, and rows of the `person` dimension, lead to the
 * person page across providers instead.
 */
export function entityHref(by: string, key: string | null, person?: string | null): string | null {
  if (key === null) return null;
  if (person && (by === "account" || by === "creator" || by === "person")) {
    return personHref(person);
  }
  // A person row without an e-mail is an account the inventory ties to nobody (service
  // account, unknown id): it keeps the provider account page.
  const segment = ENTITY_SEGMENTS[by === "person" ? "account" : by];
  if (!segment) return null;
  return `/${segment}/${encodeURIComponent(key)}`;
}

/** Key of an inventory spend map: provider plus external id, since ids are unique per provider. */
export function spendKey(provider: string, id: string): string {
  return `${provider}:${id}`;
}
