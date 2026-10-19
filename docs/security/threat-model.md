# Threat model

Single-node install. This is the trust boundary of `docker-compose.prod.yml`.

## Boundaries

- Caddy is the only published listener. It terminates HTTP or HTTPS and forwards `/api/v1`
  and `/live` to the API, with HSTS on those responses. `/ready`, `/health` and `/metrics`
  answer 404 there: the first two query the database without a rate limit. Compose and
  `scripts/smoke-prod.sh` reach them inside the containers.
- The web process calls the API on the Compose network. It forwards the browser's
  `X-Forwarded-For`. The API trusts that header only from `COSTURA_TRUSTED_PROXIES`, which
  defaults to the Compose subnet (`COSTURA_SUBNET`, `172.28.0.0/24` unless set). Inventory search
  (`apps/web/src/app/api/inventory/search/route.ts`) is a same-origin GET: the server reads
  the session and the view cookie, forwards the bearer, and answers `private, no-store`.
  The browser sends the literal query and does not receive the API address or the bearer.
  The organization and provider come from the view cookie. CSV exports
  (`apps/web/src/app/api/exports/query/route.ts`) work the same way: the server forwards an
  allowlisted set of query keys with the session's bearer and answers `private, no-store`.
- The API is the only process that holds the operator secret and the Google client secret.
  The API, the worker and the scheduler all receive the database URL, `COSTURA_SECRET_KEY`,
  and the optional provider fallback keys (`x-runtime` in `docker-compose.prod.yml`); the API
  reads a fallback key to report that organization's connection. Those keys serve only the organization whose slug is
  `COSTURA_ORG`. `POST /orgs` refuses that slug, `demo`, `demo-staging-*` and `demo-retired-*` with 409, so a
  signed-in user cannot create the organization that receives them; the operator creates
  it with `claim_owner --create` from the host.
- Postgres holds the data. A connection to it can read encrypted provider keys and webhook
  URLs (Fernet under `COSTURA_SECRET_KEY`) and session token hashes. It cannot read a
  provider key without that secret. Session hashes are unkeyed SHA-256 of 256-bit random
  tokens: the secret does not protect them, the token's entropy does, so a hash cannot be
  turned back into a usable token. A database writer can still insert a session hash it
  chose; treat write access to the database as full access.
- The API, the worker and the scheduler connect as `POSTGRES_APP_USER`, which reads and
  writes rows and cannot create, alter or drop anything. Only the one-shot `migrate` job
  connects as the schema owner (`POSTGRES_USER`); it receives no provider key, no
  `COSTURA_SECRET_KEY` and no sign-in secret, and it re-applies the runtime role's grants
  after each upgrade.
  Production startup refuses a database URL whose password is the example `costura`.
- The worker is the process that calls providers. It runs one organization at a time.
- The worker is also the only process that posts outside the stack on its own: signals go to
  an organization's webhook only when its host is in `COSTURA_WEBHOOK_HOSTS`, which is empty
  by default. The URL must be HTTPS on port 443, redirects are not followed, and the API's
  test post uses the same allowlist.

## Who can create an organization

A signed-in user can create an organization and becomes its owner. In production, Google
sign-up is invitation-only unless `COSTURA_SIGN_UP=open` or the address's domain is listed
in `COSTURA_ALLOWED_EMAIL_DOMAINS`. A pending invitation always allows that address.
The deployment administrator sign-in is not a public sign-up.

## What the sample organization publishes

The sample organization is readable without a session. Seeding it on a reachable host publishes
that organization's spend to anyone who can open the site. The spend is generated: no provider
credential is stored, and every write answers 403 once a session exists. A refresh builds the
next dataset aside and swaps it in; a failed build leaves the published sample unchanged.
`COSTURA_DEMO_REFRESH` (off by default) rebuilds a stale sample on the daily scheduler pass.

## What a database backup contains

Encrypted credentials and webhook URLs, hashed sessions, memberships, and spend. Treat the
dump as secret.
`just prod::backup` writes it with mode 0600 next to a `.version` file naming the release
and revision. With `COSTURA_BACKUP_AGE_RECIPIENT` set it streams the dump through `age` to
that public key, so the host never holds a plaintext dump or the key that opens it
([Backup and restore](../operations/backup-restore.md)). Without it, encrypt any copy that
leaves the host. Keep `COSTURA_SECRET_KEY` and the age private key apart from the dump. `just prod::restore` replaces the schema in one transaction, so a
truncated dump leaves the database as it was.
Rotating `COSTURA_SECRET_KEY` requires re-encrypting stored keys and webhook URLs (`just prod::secret-rotate`,
or `just api::secret-rotate` in development; see [SECURITY.md](../../SECURITY.md)). With
`COSTURA_SECRET_KEY_PREVIOUS` set, every process reads rows under either key while the
rotation rewrites them, so nothing stops; new ciphertext always uses the current key.
Rotating `COSTURA_OPERATOR_SECRET` is a change in `.env` and a restart of the API.
Report a vulnerability through the private form described in [SECURITY.md](../../SECURITY.md).

## What Costura logs and what it does not

- A provider error is stored as one sentence: `sanitize_stored_error` in
  `apps/api/costura/providers/http.py` drops everything from ` body=` on, replaces bearer
  values, `sk-`, `rk-`, `key_`, `crsr_`, `gh*_`, `github_pat_` tokens and Fernet blobs with
  `[redacted]`, and cuts the text at 500 characters. That sentence is what
  `provider_sync_runs.error` (`apps/api/costura/sync_cycle.py`) and a credential's
  `last_error` (`apps/api/costura/credentials.py`) hold, and what the API returns. No
  provider error body is stored.
- The server log is wider than the database: a failed provider request logs the status, the
  request id, the path and the first 300 characters of the response body, after the same
  token redaction (`apps/api/costura/providers/http.py`). Treat the API and worker logs as
  operator data. Production logs are one JSON object per line with a `request_id`
  (`apps/api/costura/telemetry.py`); that module configures process logging and sends
  nothing anywhere.
- Successful provider pages are stored as received: `provider_report_pages` holds the
  endpoint, the page index, the request parameters and the payload of every page a sync
  read (`apps/api/costura/models/sync.py`). `COSTURA_RAW_PAGE_RETENTION_DAYS` (default 90,
  `0` keeps forever) bounds them; the worker purges about once an hour, and
  `just api::purge`, `just prod::purge` or `python -m costura.ops.purge` run one pass
  (`apps/api/costura/ops/purge.py`).
- Credential events (a key connected, replaced or removed, a role changed, a member or
  invitation added or removed) are rows in `audit_events` with the actor, the target and the
  request id, and no key, key hint or invitee e-mail. Owners read them at
  `GET /orgs/{org}/audit` (`apps/api/costura/api/routers/audit.py`); the runtime role can
  insert and select them, not update or delete them.
- Nothing leaves the host for the maintainers: no usage statistics, error reports or update
  checks. The web image sets `NEXT_TELEMETRY_DISABLED=1` (`apps/web/Dockerfile`). The only
  outbound calls are the provider reads, the optional Google sign-in and the optional signal
  webhook.

## Assets and protections

What each provider key can do if it leaks, and the narrowest key each provider documents, is in
[provider keys](provider-keys.md).

| asset | protection | where |
| --- | --- | --- |
| provider admin keys | Fernet with `COSTURA_SECRET_KEY` (plus `COSTURA_SECRET_KEY_PREVIOUS` for reads during a rotation), one row per provider account, the plaintext bound to `organization|provider|account` so a ciphertext copied to another row fails to decrypt (rows written before binding read until `secret-rotate` binds them; `secret-check` counts them), never returned by the API (hint only; a submitted key is trimmed, at most 512 visible ASCII characters, and a 422 never echoes the value), a SHA-256 `key_digest` unique per organization and provider so one key cannot connect two accounts; read-only sync transports over https only in production (`*_BASE_URL` checked at startup), with provider ids percent-encoded into one path segment: Anthropic and Claude.ai `x-api-key` (Claude.ai needs `read:analytics`), OpenAI, OpenRouter and Codex Bearer (Codex bound to a workspace UUID), Cursor Basic auth, GitHub Copilot Bearer (the organization must be a GitHub login, `^[A-Za-z0-9-]{1,39}$`) (a classic token bound to an organization login; `gh*_` and `github_pat_` values are redacted from logs and stored errors) | `apps/api/costura/secrets.py`, `credentials.py`, `accounts.py`, `providers/*/client.py`, `api/schemas/connections.py`, `main.py` |
| Google identity | authorization code exchanged server-side; one-use database-backed state, nonce and PKCE with a 10-minute TTL; RS256 signature verified against Google JWKS plus issuer, audience, expiry, nonce and `email_verified` | `apps/api/costura/google_oidc.py`, `apps/web/src/app/api/auth/google/` |
| organization data | session per user, membership per organization, three roles: `owner` for keys and accounts, budgets, the organization name, roles, invitations and reset; `owner` or `member` for imports (Sync now), Codex credit prices, anomaly triage, owner assignments and the getting-started card; `viewer` reads. Every role sets its own inbox opt-in and read markers, and anyone may leave. At least one owner at all times, 404 for foreign organizations, the sample organization refuses every write | `apps/api/costura/api/deps.py`, `apps/api/costura/members.py`, `apps/api/costura/api/routers/` |
| invitations | owner-only, bound to one lowercased address, link token stored as a sha256 digest, 14-day expiry, revocable; accepting requires the signed-in address and answers 410 without naming the invited address when it does not match | `apps/api/costura/members.py`, `apps/api/costura/models/invitation.py` |
| write routes | Google-verified session, or a development session for `COSTURA_OPERATOR_EMAIL` when `COSTURA_OPERATOR_SECRET` is set, plus the tenant and role dependencies in production; other development sessions only on a development/test loopback stack; per-address rate limits on sign-in, writes and the public sample, per-session limits on member reads, and per-organization limits on provider key stores, each of which calls the provider; the limiter keeps at most 10,000 clients and drops idle ones first, so random keys cannot grow its memory. Ranges on the public sample span at most 400 days, and every date must fall between 2000 and 2099. The address is the TCP peer unless that peer is listed in `COSTURA_TRUSTED_PROXIES` (IP, CIDR, or `*`), in which case it is the rightmost `X-Forwarded-For` hop that is not itself trusted (`*` takes the rightmost hop). An untrusted forwarded header still refuses a development write, unless the TCP peer and every forwarded hop are loopback, as the local Next.js server sends them | `apps/api/costura/api/guard.py`, `ratelimit.py` |
| browser session | opaque token in an `HttpOnly`, `SameSite=Lax` cookie (`__Host-` over HTTPS; off localhost the unprefixed name is never read, so a planted cookie cannot sign a browser in), 30-day absolute and 7-day idle expiry, revoke-all | `apps/web/src/lib/session-cookie.ts`, `apps/api/costura/auth.py` |
| active view (organization, provider scope, dates, interval) | second `HttpOnly`, `SameSite=Lax` cookie `costura_view` (`__Host-` over HTTPS) holding only the slug, scope, the month a link without dates opens, dates and interval; every read is re-checked against the membership on the API, so the cookie grants nothing by itself; cleared at sign-out | `apps/web/src/lib/view-cookie.ts`; `apps/web/src/lib/view.ts` resolves it; `apps/web/src/app/o/[org]/route.ts` |
| audit trail | `audit_events` stores who connected, replaced or removed a provider key or account, changed a role, removed or added a member, created or revoked an invitation, renamed, reset or deleted the organization, triaged an anomaly, snoozed or brought back a key gap, changed anomaly settings, invoices, personal keys, Copilot logins or the webhook, with the actor, the target and the request id; no key, key hint or e-mail of an invitee is stored; the runtime role may insert and select, not update, delete or truncate; a reset and a deletion keep the rows; owners read it at `GET /orgs/{org}/audit` | `apps/api/costura/audit.py`, `models/audit.py`, `api/routers/audit.py`, `ops/db_roles.py` |
| CSV exports | cells that start with `=`, `+`, `-` or `@` are neutralized so a provider-supplied name cannot run as a spreadsheet formula | `apps/api/costura/api/presenters/spend.py` |
| signal webhook | owner-only save, test, resend and removal; the URL and a per-organization signing secret are Fernet ciphertext under `COSTURA_SECRET_KEY`; responses show the host only and the signing secret once, on save; errors and stored delivery failures name the HTTP status or the exception class, never the URL; posts are signed (`X-Costura-Signature`, HMAC-SHA256 of `{timestamp}.{body}`); one post per signal | `apps/api/costura/delivery.py`, `models/delivery.py`, `api/routers/webhooks.py` |
| raw pages and run history | `COSTURA_RAW_PAGE_RETENTION_DAYS` (default 90, `0` keeps forever) deletes old `provider_report_pages`. `COSTURA_RUN_RETENTION_DAYS` (default 90, `0` keeps forever) deletes terminal `scheduler_runs` and completed `provider_sync_runs` that spend, inventory and allocation no longer reference. The worker runs this about once an hour; `python -m costura.ops.purge` runs one pass and logs the counts | `apps/api/costura/ops/purge.py` |
| web responses | CSP per request (`default-src 'self'`, `frame-ancestors 'none'`; `script-src 'self' 'nonce-…' 'strict-dynamic'` with a fresh 128-bit nonce, so injected inline scripts and event handlers do not run; `style-src` allows `'unsafe-inline'` because Tailwind and Recharts emit inline styles), `nosniff`, `Referrer-Policy`, COOP, HSTS in production | `apps/web/src/proxy.ts`, `apps/web/src/lib/csp.ts`, `apps/web/next.config.ts` |
| dependencies | SHA-pinned actions, exact versions with lockfiles, Dependabot daily for GitHub Actions, uv, npm, the API, web and proxy Dockerfiles and `docker-compose.prod.yml` (including major updates), dependency review on pull requests (high and critical), CodeQL for JavaScript/TypeScript and Python, Trivy filesystem scan on pull requests and on `main`, image scans on main and on pull requests that touch `apps/api/**`, `apps/web/**`, `deploy/**`, compose, the mise pins, the production smoke scripts, or `.just/prod.just` | `.github/workflows/`, `.github/dependabot.yml`, `apps/api/pyproject.toml`, `apps/web/pnpm-workspace.yaml` |
| secrets in git | betterleaks on pre-commit (skipped with a warning when the binary is not on `PATH`) and in `just check`, which CI runs on pull requests and on `main` | `scripts/betterleaks-pre-commit.sh`, `.betterleaksignore` |

A fresh database holds organizations, identity, provider accounts and credentials,
inventory, spend, allocation, anomalies, projections, budgets, webhook deliveries, signal
history and the audit trail.
