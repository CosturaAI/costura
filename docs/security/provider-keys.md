# Provider keys: what Costura asks for and what a stolen key can do

One section per provider: the credential Costura asks for, every request the client sends
(method and path; `tests/test_provider_keys_doc.py` checks this list against the client
modules), the narrowest credential the provider documents, and the blast radius if the key
leaks. Every client sends through `GuardedTransport` (`apps/api/costura/providers/http.py`),
which refuses any request outside the methods and paths listed here. That limits what
Costura sends, not what a stolen key can do. Researched 2026-10-15; "unconfirmed" marks a
claim no fetched official page settles.

## Anthropic (Claude Console)

- Asks for: an Admin API key (`sk-ant-admin01-`), header `x-api-key`.
- Requests (GET only):
  - `GET /v1/organizations/cost_report`
  - `GET /v1/organizations/usage_report/messages`
  - `GET /v1/organizations/workspaces`, `GET /v1/organizations/workspaces/{id}/members`
  - `GET /v1/organizations/users`
  - `GET /v1/organizations/api_keys`
  - `GET /v1/organizations/me`
- Narrowest credential: Console admin keys have no scopes; "every key carries full access to
  all endpoints that accept Admin API keys"
  ([admin API keys](https://platform.claude.com/docs/en/manage-claude/admin-api-keys)).
  Whether a service-account key with the billing role can read the reports is unconfirmed.
- If stolen: manages members, roles, invites, workspaces and the status of API keys (it can
  disable every inference key) and reads the compliance activity feed. It cannot create API
  keys in the Console or remove admins. Nothing documented returns message content
  ([Admin API](https://platform.claude.com/docs/en/api/administration-api)).

## Claude.ai (Enterprise Analytics)

- Asks for: an Analytics key with `read:analytics`, header `x-api-key`.
- Requests (GET only):
  - `GET /v1/organizations/analytics/cost_report`
  - `GET /v1/organizations/analytics/user_cost_report`
  - `GET /v1/organizations/analytics/user_usage_report`
  - `GET /v1/organizations/analytics/users`
- Narrowest credential: `read:analytics` alone, the read-only scope the primary owner selects
  ([Analytics API](https://platform.claude.com/docs/en/manage-claude/analytics-api)).
- If stolen: reads per-user activity, cost and usage for claude.ai and Claude Code. It cannot
  call the Admin API, and conversation content needs another scope.
- Created under claude.ai, Organization settings, API, by the primary owner; it starts with
  `sk-ant-api01-`. The connect form also accepts `sk-ant-admin` keys, which the docs say
  this API refuses; no live key has confirmed either form yet.

## OpenAI (API Platform)

- Asks for: an organization Admin key (`sk-admin-`), Bearer.
- Requests (GET only):
  - `GET /organization/costs`
  - `GET /organization/usage/completions`
  - `GET /organization/projects`, `GET /organization/projects/{id}/api_keys`,
    `GET /organization/projects/{id}/users`
  - `GET /organization/users`
- Narrowest credential: unconfirmed. The reference says only that admin keys serve the
  administration endpoints
  ([administration overview](https://developers.openai.com/api/reference/administration/overview));
  whether an admin key can be limited to read is not on a fetched page.
- If stolen: users, invites, projects, API keys and audit logs, per the same page. It cannot
  call inference directly; creating project keys is likely but unconfirmed.

## Codex (ChatGPT Enterprise analytics)

- Asks for: a workspace Admin key (`sk-admin-`) bound to a workspace UUID, Bearer.
- Requests: `GET /workspaces/{workspace_id}/usage` on `https://api.chatgpt.com/v1/analytics/codex`.
- Narrowest credential: a workspace-scoped key with only the Codex analytics read permission
  (`codex.enterprise.analytics.read`); keys are workspace-scoped
  ([analytics API](https://learn.chatgpt.com/docs/enterprise/analytics-api)). The exact
  dialog wording is unconfirmed.
- If stolen: aggregate usage and activity metrics of one workspace, no prompts.

## OpenRouter

- Asks for: a management key (`sk-or-v1-`), Bearer.
- Requests:
  - `GET /api/v1/key`
  - `GET /api/v1/keys`
  - `GET /api/v1/workspaces`, `GET /api/v1/workspaces/{id}/members`
  - `GET /api/v1/organization/members`
  - `POST /api/v1/analytics/query`, the only non-GET request the client allows
- Narrowest credential: a management key is the only key the analytics, keys, workspace and
  member routes accept, and it is unscoped across the account's workspaces
  ([management API keys](https://openrouter.ai/docs/features/provisioning-api-keys)).
- If stolen: creates, changes and deletes inference keys and their credit limits (spend),
  manages workspaces, members, budgets and BYOK keys, and can add an observability
  destination that receives future prompts and completions unless Privacy Mode is on
  ([Broadcast](https://openrouter.ai/docs/guides/features/broadcast)). Use a dedicated key
  and rotate it quickly after any exposure.

## Cursor

- Asks for: a team Admin API key, HTTP Basic auth.
- Requests:
  - `GET /teams/members`
  - `POST /teams/filtered-usage-events`
  - `POST /teams/daily-usage-data`
  - `POST /teams/spend`
- Narrowest credential: Admin API keys require `admin:*`
  ([Cursor API](https://cursor.com/docs/api)); whether a `read:*` key serves these four
  requests is unconfirmed ([Admin API](https://cursor.com/docs/account/teams/admin-api)).
- If stolen: every Admin API write, including spend limits, member removal, repository
  blocklists, model access policy and audit log reads. Usage endpoints return metrics, not
  prompts or code.

## GitHub Copilot (experimental)

- Asks for: a classic personal access token (`ghp_`) with `read:org`, Bearer.
- Requests (GET only):
  - `GET /organizations/{org}/settings/billing/usage`
  - `GET /organizations/{org}/settings/billing/ai_credit/usage`
  - `GET /orgs/{org}/copilot/billing/seats`
  - `GET /organizations/{org}/settings/billing/budgets`
  - `GET /users/{login}`
- Narrowest credential: seats accept `read:org` alone
  ([Copilot user management](https://docs.github.com/en/rest/copilot/copilot-user-management));
  `manage_billing:copilot` is not needed. A fine-grained token with organization
  Administration (read) and GitHub Copilot Business (read) matches the REST reference
  ([billing usage](https://docs.github.com/en/rest/billing/usage)), but a billing tutorial
  says those endpoints do not take fine-grained tokens
  ([automate usage reporting](https://docs.github.com/en/billing/tutorials/automate-usage-reporting));
  a live run settles which token type works.
- If stolen: a classic token reaches every organization its owner belongs to, and with
  `manage_billing:copilot` it can add or cancel paid seats.
