/**
 * Provider slugs in the URL. `all` is the aggregated scope: every registered provider's rows
 * together, with the provider as a dimension, a filter and a badge. Labels of concrete
 * providers come from `api.providers(org)`; this table is the fallback for copy rendered
 * before that call resolves (breadcrumb, not-found pages).
 */
export const ALL = "all";
const ALL_LABEL = "All providers";

const PROVIDER_LABELS: Record<string, string> = {
  anthropic: "Anthropic",
  claude_ai: "Claude.ai",
  openrouter: "OpenRouter",
  openai: "OpenAI",
  codex: "Codex",
  cursor: "Cursor",
  copilot: "GitHub Copilot",
};

/** Concrete providers the registry knows; `all` is not one of them. */
export const PROVIDERS = Object.keys(PROVIDER_LABELS);

export function isAll(provider: string): boolean {
  return provider === ALL;
}

export function providerLabel(provider: string): string {
  if (provider === ALL) return ALL_LABEL;
  return PROVIDER_LABELS[provider] ?? provider;
}

/**
 * Whether an account label says more than the provider's name. The default account of a
 * provider carries the provider's name, so a badge for it would repeat the provider.
 */
export function hasAccountLabel(
  provider: string,
  accountLabel: string | null | undefined,
): boolean {
  return Boolean(accountLabel) && accountLabel !== providerLabel(provider);
}

/** "OpenAI - Acme" when the account has a name of its own, else "OpenAI". An account name that
 * already starts with the provider ("OpenAI - Acme") is not prefixed again. */
export function sourceLabel(provider: string, accountLabel: string | null | undefined): string {
  const label = providerLabel(provider);
  if (!hasAccountLabel(provider, accountLabel) || accountLabel == null) return label;
  const prefix = `${label} - `;
  const own = accountLabel.startsWith(prefix) ? accountLabel.slice(prefix.length) : accountLabel;
  return own ? `${label} - ${own}` : label;
}
