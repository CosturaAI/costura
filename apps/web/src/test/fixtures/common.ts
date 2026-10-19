/** Shared constants of the fixtures: the organization, providers, month and day helpers. */

export const ORG = "default";

export const PROVIDER = "anthropic";

export const OTHER_PROVIDER = "openrouter";

export const MONTH = "2026-08";

export const noSearch = Promise.resolve({});

export const tokens = (n: number) => ({
  uncached_input_tokens: n,
  cache_creation_5m_tokens: 0,
  cache_creation_1h_tokens: 0,
  cache_read_tokens: 0,
  output_tokens: n / 2,
});

export const DAYS = Array.from(
  { length: 31 },
  (_, i) => `2026-08-${String(i + 1).padStart(2, "0")}`,
);

export const zeros = () => DAYS.map(() => "0.00");

export const ZERO_TOKENS: Record<string, number> = {
  uncached_input_tokens: 0,
  cache_creation_5m_tokens: 0,
  cache_creation_1h_tokens: 0,
  cache_read_tokens: 0,
  output_tokens: 0,
  reasoning_tokens: 0,
};
