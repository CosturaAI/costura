# Configuration

Every variable Costura reads, grouped by the process that reads it. Values come from `.env`
next to `docker-compose.prod.yml`; the compose file passes each one to the services listed.
`just prod::init` writes a working `.env` ([install](install.md#configure)). The source of
truth for the API is `apps/api/costura/config.py`; for the web app, `apps/web/src/lib`.

"Compose default" is what `docker-compose.prod.yml` substitutes when `.env` leaves the
variable empty or unset. "Required" means production refuses to start without it.

## Release and database

| Variable                      | Read by                            | Compose default | Notes                                                                                                                    |
| ----------------------------- | ---------------------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `COSTURA_VERSION`             | compose (image tags)               | required        | Release to run, without the `v`; `.env.example` holds the checkout's own release. `latest` is not supported.                                                              |
| `POSTGRES_DB`                 | postgres, migrate, compose         | required        | Database name.                                                                                                           |
| `POSTGRES_USER`               | postgres, migrate, backup, restore | required        | Schema owner; used only by the migration and by backup and restore.                                                      |
| `POSTGRES_PASSWORD`           | postgres, migrate                  | required        | Owner password. Letters, digits, `_-.`; not `costura`.                                                                   |
| `POSTGRES_APP_USER`           | migrate, api, worker, scheduler    | required        | Runtime role: rows only, no DDL. Lowercase, differs from the owner.                                                      |
| `POSTGRES_APP_PASSWORD`       | migrate, api, worker, scheduler    | required        | At least 12 characters; differs from the owner password. Set again by every migration.                                   |
| `COSTURA_SECRET_KEY`          | api, worker, scheduler             | required        | Fernet key that encrypts stored provider keys. Keep a copy off the host: without it no stored key or backup can be read. |
| `COSTURA_SECRET_KEY_PREVIOUS` | api, worker, scheduler             | empty           | Only during a rotation: the old key, still accepted for reads. Remove it after `secret-check` shows no row on it.        |

`COSTURA_ENV` is forced to `production` and `DATABASE_URL` is built from the variables
above by the compose file; do not set them in a production `.env`.

## Sign-in

At least one method is required in production.

| Variable                        | Read by | Compose default             | Notes                                                                            |
| ------------------------------- | ------- | --------------------------- | -------------------------------------------------------------------------------- |
| `COSTURA_OPERATOR_EMAIL`        | api     | empty                       | Deployment administrator address.                                                |
| `COSTURA_OPERATOR_SECRET`       | api     | empty                       | At least 24 characters. Retire both once a Google account owns the organization. |
| `GOOGLE_CLIENT_ID`              | api     | empty                       | Google OAuth web application.                                                    |
| `GOOGLE_CLIENT_SECRET`          | api     | empty                       | Both Google values, or neither.                                                  |
| `COSTURA_SIGN_UP`               | api     | `invite_only` in production | `open` lets anyone with a verified Google account sign up.                       |
| `COSTURA_ALLOWED_EMAIL_DOMAINS` | api     | empty                       | Comma-separated domains that may sign up without an invitation.                  |

## Addresses

The three URL variables must name the same origin. `just prod::init` sets them together.

| Variable                  | Read by         | Compose default    | Notes                                                                                                   |
| ------------------------- | --------------- | ------------------ | ------------------------------------------------------------------------------------------------------- |
| `COSTURA_SITE_ADDRESS`    | proxy (Caddy)   | `http://localhost` | A bare hostname (`costura.example.com`) turns on automatic HTTPS.                                       |
| `COSTURA_WEB_ORIGIN`      | api             | `http://localhost` | Browser origin the API allows (CORS).                                                                   |
| `COSTURA_WEB_PUBLIC_URL`  | api             | empty              | Origin browsers use; the Google callback is `{this}/api/auth/google/callback`. HTTPS outside localhost. |
| `COSTURA_HTTP_PORT`       | compose (proxy) | `80`               | Host port for HTTP.                                                                                     |
| `COSTURA_HTTPS_PORT`      | compose (proxy) | `443`              | Host port for HTTPS.                                                                                    |
| `COSTURA_SUBNET`          | compose         | `172.28.0.0/24`    | Compose network; change it when Docker reports an overlapping pool.                                     |
| `COSTURA_TRUSTED_PROXIES` | api             | `COSTURA_SUBNET`   | Peers allowed to set `X-Forwarded-For`: IPs, CIDRs or `*`.                                              |

| Variable                   | Read by                         | Compose default  | Notes                                                                   |
| -------------------------- | ------------------------------- | ---------------- | ----------------------------------------------------------------------- |
| `COSTURA_DATABASE_HOST`    | migrate, api, worker, scheduler | `postgres`       | A managed PostgreSQL; see [install](install.md).                        |
| `COSTURA_DATABASE_PORT`    | migrate, api, worker, scheduler | `5432`           |                                                                         |
| `COSTURA_DATABASE_OPTIONS` | migrate, api, worker, scheduler | `sslmode=prefer` | libpq options after `?`, such as `sslmode=verify-full&sslrootcert=...`. |

`COSTURA_API_URL` is fixed to `http://api:8000` inside the web container.

## Scheduling, retention and limits

| Variable                          | Read by         | Compose default | Notes                                                                   |
| --------------------------------- | --------------- | --------------- | ----------------------------------------------------------------------- |
| `COSTURA_SCHEDULE_AT`             | scheduler       | `06:00`         | Daily sync time, UTC, `HH:MM`.                                          |
| `COSTURA_DEMO_REFRESH`            | scheduler       | `false`         | Rebuild a stale public sample on the daily pass.                        |
| `COSTURA_DEMO_CACHE_MB`           | api             | `64`            | Memory for anonymous sample reads, per dataset and UTC day. `0`: off.   |
| `COSTURA_DEMO_WARM_URL`           | api             | empty           | Web address (`http://web:3000`) the API renders sample pages through.   |
| `COSTURA_BACKFILL_MONTHS`         | worker          | `3`             | Months a new connection imports, current included; daily runs read two. |
| `COSTURA_WEBHOOK_HOSTS`           | api, worker     | empty           | Hosts a signal webhook may post to (`hooks.slack.com`). Empty: off.     |
| `COSTURA_RAW_PAGE_RETENTION_DAYS` | worker          | `90`            | Days to keep raw provider pages. `0` keeps them.                        |
| `COSTURA_RUN_RETENTION_DAYS`      | worker          | `90`            | Days to keep finished runs nothing references. `0` keeps them.          |
| `COSTURA_RATE_LIMIT_AUTH`         | api             | `20`            | Sign-in requests per minute per client. `0` turns the bucket off.       |
| `COSTURA_RATE_LIMIT_WRITE`        | api             | `120`           | Writes per minute per client.                                           |
| `COSTURA_BACKUP_AGE_RECIPIENT`    | `prod::backup`  | empty           | age public key; when set, backups are written encrypted (`*.dump.age`). |
| `COSTURA_BACKUP_AGE_IDENTITY`     | `prod::restore` | empty           | Path to the age private key that opens a `*.dump.age` dump.             |
| `COSTURA_RATE_LIMIT_DEMO`         | api             | `3000`          | Public sample reads per minute per client.                              |
| `COSTURA_RATE_LIMIT_READ`         | api             | `1200`          | Member reads per minute per session.                                    |
| `COSTURA_RATE_LIMIT_CONNECT`      | api             | `10`            | Provider key stores per minute per organization.                        |
| `COSTURA_LOG_LEVEL`               | all three       | `INFO`          | `DEBUG`, `INFO`, `WARNING` or `ERROR` for the `costura` loggers.        |

Rate limits and HTTP metrics are kept in the API process; run one API replica. "All three"
means the api, the worker and the scheduler. Logs and metrics: [monitoring](monitoring.md).

## Provider fallback keys

Optional. They apply only to the organization named by `COSTURA_ORG`, and only while it
stores no key of its own. Keys added in Settings, Connections need none of these.

| Variable                                | Read by                | Notes                                                                                                                         |
| --------------------------------------- | ---------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `COSTURA_ORG`                           | api, scheduler, worker | Organization that may use the keys below; default `default`. Create it with `just prod::claim-owner <slug> <email> --create`. |
| `ANTHROPIC_ADMIN_KEY`                   | api, scheduler, worker | Anthropic Admin API key (`sk-ant-admin01-...`).                                                                               |
| `CLAUDE_AI_API_KEY`                     | api, scheduler, worker | Claude.ai Enterprise Analytics key with `read:analytics`.                                                                     |
| `OPENAI_ADMIN_KEY`                      | api, scheduler, worker | OpenAI admin key with read access to usage and the organization.                                                              |
| `CODEX_ADMIN_KEY`, `CODEX_WORKSPACE_ID` | api, scheduler, worker | Codex Admin API key and the ChatGPT workspace UUID; both required.                                                            |
| `OPENROUTER_ADMIN_KEY`                  | api, scheduler, worker | OpenRouter management key (`sk-or-v1-...`).                                                                                   |
| `CURSOR_API_KEY`                        | api, scheduler, worker | Cursor team API key.                                                                                                          |
| `COPILOT_GITHUB_TOKEN`, `COPILOT_ORG`   | api, scheduler, worker | Experimental: classic token of an organization owner or billing manager, and the organization login.                          |

Each provider also reads `<PROVIDER>_BASE_URL` (`ANTHROPIC_BASE_URL`, `CLAUDE_AI_BASE_URL`,
`OPENAI_BASE_URL`, `CODEX_BASE_URL`, `OPENROUTER_BASE_URL`, `CURSOR_BASE_URL`,
`COPILOT_BASE_URL`). Leave them unset outside tests or a data-residency endpoint. In
production each one must start with `https://`, or every process refuses to start.

## Appearance

| Variable                   | Read by | Compose default | Notes                                                                   |
| -------------------------- | ------- | --------------- | ----------------------------------------------------------------------- |
| `COSTURA_THEME`            | web     | `costura`       | Theme file stem in `apps/web/src/themes`.                               |
| `COSTURA_COLOR_SCHEME`     | web     | `light`         | `light`, `dark` or `system`.                                            |
| `COSTURA_BRAND_NAME`       | web     | `Costura`       | Name in the sidebar and the document title.                             |
| `COSTURA_PUBLIC_DEMO_HOME` | web     | `false`         | `true`: `/` without a session opens the sample; a band links to GitHub. |

## Development only

`COSTURA_ENV` (`development`, `test`), `DATABASE_URL`, `TEST_DATABASE_URL` and
`COSTURA_API_URL` are set by `.env.example` for `just dev` and `just test`. Development
accepts any e-mail at `/sign-in` on a loopback stack; production refuses that.
`COSTURA_DEV_DB_PORT` (default `5432`) is the host port of the development PostgreSQL in
`docker-compose.yml`; a second checkout that runs its own sets another one and the same port
in `DATABASE_URL` and `TEST_DATABASE_URL`.
