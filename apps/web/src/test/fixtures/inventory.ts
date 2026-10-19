/** Inventory fixtures: API keys, workspaces, users and a person. */

import type { ApiKey, Person, User, Workspace } from "@/lib/api";

import { OTHER_PROVIDER, PROVIDER } from "./common";

export const apiKeys: ApiKey[] = [
  {
    provider: PROVIDER,
    provider_account_id: 1,
    provider_account_label: "Anthropic",
    external_id: "apikey_redacted_2",
    name: "batch-ingest",
    partial_key_hint: "sk-ant-api03-...bbbb",
    workspace_external_id: "wrkspc_redacted_a",
    workspace: "Platform (wrkspc_redacted_a)",
    created_by_external_id: "user_bob",
    created_by: "bob@example.com",
    status: "active",
    created_at: "2026-01-02T00:00:00+00:00",
    expires_at: null,
    last_seen_at: "2026-09-14T12:00:00+00:00",
    missing_since: null,
    missing: false,
    limit_reported: false,
    creator_left: false,
  },
  {
    provider: PROVIDER,
    provider_account_id: 1,
    provider_account_label: "Anthropic",
    external_id: "apikey_redacted_9",
    name: "retired",
    partial_key_hint: null,
    workspace_external_id: null,
    workspace: "(default workspace)",
    created_by_external_id: null,
    created_by: "",
    status: "inactive",
    created_at: null,
    expires_at: null,
    last_seen_at: "2026-09-01T12:00:00+00:00",
    missing_since: "2026-09-10T12:00:00+00:00",
    missing: true,
    limit_reported: false,
    creator_left: false,
  },
];

export const workspaces: Workspace[] = [
  {
    provider: PROVIDER,
    provider_account_id: 1,
    provider_account_label: "Anthropic",
    external_id: "wrkspc_redacted_a",
    name: "Platform",
    archived_at: null,
    admins: ["alice@example.com"],
    api_keys: 3,
    created_at: "2026-01-01T00:00:00+00:00",
    last_seen_at: "2026-09-14T12:00:00+00:00",
    missing_since: null,
    missing: false,
  },
];

export const users: User[] = [
  {
    provider: PROVIDER,
    external_id: "user_alice",
    email: "alice@example.com",
    role: "admin",
    kind: "user",
    added_at: "2026-01-01T00:00:00+00:00",
    last_seen_at: "2026-09-14T12:00:00+00:00",
    missing_since: null,
    missing: false,
    limit_reported: false,
  },
];

/** alice@example.com on two providers: the aggregated person page shows both. */
export const person: Person = {
  email: "alice@example.com",
  identities: [
    {
      provider: PROVIDER,
      external_id: "user_alice",
      role: "admin",
      added_at: "2026-01-01T00:00:00+00:00",
      missing: false,
      keys_created: 2,
    },
    {
      provider: "openai",
      external_id: "user-alice",
      role: "owner",
      added_at: "2026-03-01T00:00:00+00:00",
      missing: false,
      keys_created: 1,
    },
  ],
  providers: [PROVIDER, "openai"],
};

export const openRouterKey: ApiKey = {
  ...apiKeys[0]!,
  provider: OTHER_PROVIDER,
  external_id: "orkey_hash_1",
  name: "router-prod",
  partial_key_hint: "prod",
  workspace_external_id: "ws_or_1",
  workspace: "Default (ws_or_1)",
  created_by_external_id: null,
  created_by: "",
};
