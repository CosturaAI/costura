import type { Schema } from "./schema";
/**
 * Provider inventory (keys, workspaces, users), people, owner assignments and personal keys.
 */

import { get, scope, send } from "./transport";

export type ApiKey = Schema<"ApiKeyOut">;

export type Workspace = Schema<"WorkspaceOut">;

type InventorySearchKind = "person" | "service" | "api_key" | "workspace";

/** One current inventory resource. A person is one e-mail and may list several providers. */
export type InventorySearchItem = {
  kind: InventorySearchKind;
  id: string;
  label: string;
  providers: string[];
  provider_account_id?: number | null;
  provider_account_label?: string | null;
  hint?: string | null;
};

export type User = Schema<"UserOut">;

/** One provider account of a person: the inventory row carrying the e-mail. */
type PersonIdentity = {
  provider: string;
  external_id: string;
  role: string;
  added_at: string | null;
  missing: boolean;
  keys_created: number;
};

/** One e-mail across the providers in scope. */
export type Person = Omit<Schema<"PersonOut">, "identities"> & {
  identities: PersonIdentity[];
};

/** Who to contact about an anomaly, most specific first. `source` names the key or workspace
 * that led to the person, or "Costura organization" for the organization owners. `note` is the
 * free text of a contact assigned in Costura; null for owners read from the inventory. */
export type Owner = {
  email: string;
  role:
    | "assigned in Costura"
    | "created the key"
    | "used their own login"
    | "workspace admin"
    | "organization owner";
  source: string;
  note?: string | null;
};

export type AssignmentKind = "api_key" | "workspace";

/** A key a member marked as one person's own; its spend counts under that e-mail. */
type PersonalKey = Schema<"PersonalKeyOut">;

/** A contact a member recorded for a key or a workspace the inventory names nobody for. */
type OwnerAssignment = Omit<Schema<"OwnerAssignmentOut">, "kind"> & {
  kind: AssignmentKind;
};

const LIST_PAGE = 2000;

async function everyPage<T>(path: string, includeMissing: boolean): Promise<{ items: T[] }> {
  const items: T[] = [];
  for (;;) {
    const page = await get<{ items?: T[]; total?: number }>(path, {
      include_missing: includeMissing,
      limit: LIST_PAGE,
      offset: items.length,
    });
    const rows = page.items ?? [];
    items.push(...rows);
    if (rows.length === 0 || items.length >= (page.total ?? items.length)) break;
  }
  return { items };
}

export const inventoryApi = {
  apiKeys: (org: string, provider: string, includeMissing = true) =>
    everyPage<ApiKey>(`${scope(org, provider)}/inventory/api-keys`, includeMissing),
  workspaces: (org: string, provider: string, includeMissing = true) =>
    everyPage<Workspace>(`${scope(org, provider)}/inventory/workspaces`, includeMissing),
  users: (org: string, provider: string, includeMissing = true) =>
    everyPage<User>(`${scope(org, provider)}/inventory/users`, includeMissing),
  /** Current resources matching a literal substring. Each kind returns at most `limit` rows. */
  inventorySearch: (org: string, provider: string, q: string, limit?: number) =>
    get<{ items: InventorySearchItem[] }>(`${scope(org, provider)}/inventory/search`, {
      q,
      limit,
    }),
  apiKey: (org: string, provider: string, id: string, account?: number) =>
    get<ApiKey>(`${scope(org, provider)}/inventory/api-keys/${encodeURIComponent(id)}`, {
      account,
    }),
  workspace: (org: string, provider: string, id: string, account?: number) =>
    get<Workspace>(`${scope(org, provider)}/inventory/workspaces/${encodeURIComponent(id)}`, {
      account,
    }),
  user: (org: string, provider: string, id: string, account?: number) =>
    get<User>(`${scope(org, provider)}/inventory/users/${encodeURIComponent(id)}`, { account }),
  /** The accounts of one e-mail on the providers in scope; 404 when none carries it. */
  person: (org: string, provider: string, month: string, email: string) =>
    get<Person>(`${scope(org, provider)}/months/${month}/people/${encodeURIComponent(email)}`),
  ownerAssignments: (org: string, provider: string) =>
    get<OwnerAssignment[]>(`${scope(org, provider)}/owners`),
  assignOwner: (
    org: string,
    provider: string,
    kind: AssignmentKind,
    externalId: string,
    email: string,
    note: string | null,
  ) =>
    send<OwnerAssignment>(
      "PUT",
      `${scope(org, provider)}/owners/${kind}/${encodeURIComponent(externalId)}`,
      { email, note },
    ),
  unassignOwner: (org: string, provider: string, kind: AssignmentKind, externalId: string) =>
    send<void>(
      "DELETE",
      `${scope(org, provider)}/owners/${kind}/${encodeURIComponent(externalId)}`,
    ),
  personalKeys: (org: string, provider: string) =>
    get<PersonalKey[]>(`${scope(org, provider)}/personal-keys`),
  markPersonalKey: (org: string, provider: string, apiKeyId: string, email: string) =>
    send<PersonalKey>(
      "PUT",
      `${scope(org, provider)}/personal-keys/${encodeURIComponent(apiKeyId)}`,
      { email },
    ),
  unmarkPersonalKey: (org: string, provider: string, apiKeyId: string) =>
    send<void>("DELETE", `${scope(org, provider)}/personal-keys/${encodeURIComponent(apiKeyId)}`),
};
