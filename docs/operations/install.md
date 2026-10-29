# Install

Single-node. One replica of each unit: Postgres, the API, the worker, the scheduler,
the web app, and Caddy. `docker-compose.yml` is only the local development database.
This install is `docker-compose.prod.yml`.

## Prerequisites

- A Linux host (amd64 or arm64) with Docker Engine and Compose v2, 4 GB of memory, and the
  disk the database needs (a few hundred megabytes per year for a small team). The compose
  file caps the services at 3.8 GB together (Postgres 1 GB, worker 1 GB, migration, API,
  scheduler and web 512 MB each, Caddy 256 MB); the migration exits before the rest start,
  and a sync on a 2 GB host can be killed before reaching those caps.
- `git` to check out a release tag, or only `curl` and `tar` for the Docker-only bundle
  below, and `openssl` or the API image to generate secrets.
- `python3` for `scripts/prod-password.sh`, which `just prod::up`, `backup` and `restore`
  run first, and for `scripts/prod-init.sh` and `scripts/prod-doctor.sh`.
- For a public hostname: DNS pointing at the host and ports 80 and 443 open, so Caddy can
  obtain the certificate.
- `just` is optional; the compose commands below are the same thing.

<!-- x-release-please-start-version -->

Published images live at `ghcr.io/costuraai/costura-{api,web,proxy}`, one tag per release
(`0.4.0`). `latest` follows the newest release and is not a supported install: pin the
version.

<!-- x-release-please-end -->

## Limits

- One replica of each unit. The worker runs one sync at a time.
- The API port is not published. Do not publish port 8000.
- Provider clients are read-only.
- Raw pages and finished runs are deleted after 90 days (`0` keeps that class). The spend ledger stays.
- Production sign-in is the operator secret or Google. Any-email sign-in is development and test only.
- There is no supported Alembic downgrade. Restore a backup.

## Configure

### Docker only

Releases from 0.3.0 on attach `costura-X.Y.Z.tar.gz` to the
[GitHub Release](https://github.com/CosturaAI/costura/releases): the production compose
file, `.env.example`, `LICENSE`, and the init, doctor and password scripts. The images come
from GHCR, so the host needs no clone, no `just` and no development tools:

<!-- x-release-please-start-version -->

```
v=0.4.0
curl -fsSLO "https://github.com/CosturaAI/costura/releases/download/v$v/costura-$v.tar.gz"
curl -fsSLO "https://github.com/CosturaAI/costura/releases/download/v$v/costura-$v.tar.gz.sha256"
sha256sum -c "costura-$v.tar.gz.sha256" && tar -xzf "costura-$v.tar.gz" && cd "costura-$v"
bash scripts/prod-init.sh --email you@example.com --host costura.example.com
bash scripts/prod-doctor.sh
```

<!-- x-release-please-end -->

Then start it with the compose commands under [Start](#start) ("Without `just`"). Every
`just prod::*` recipe in these pages is a `docker compose -f docker-compose.prod.yml`
command, listed in [`.just/prod.just`](../../.just/prod.just).

### From a checkout

From a checkout of the release tag, used only for production. `just dev` and the
`just prod::*` recipes read the same `.env` at the repository root, and `prod::init` refuses
to overwrite one, so a development checkout cannot also be the production one:

<!-- x-release-please-start-version -->

```
git clone https://github.com/CosturaAI/costura.git && cd costura
git checkout v0.4.0
just prod::init --email you@example.com                          # http://localhost trial
just prod::init --email you@example.com --host costura.example.com
```

<!-- x-release-please-end -->

`prod::init` (`scripts/prod-init.sh`, needs only `python3`) writes `.env` from
`.env.example` with mode 600: it generates the four secrets below, sets the deployment
administrator to that e-mail, sets `COSTURA_WEB_ORIGIN`, `COSTURA_WEB_PUBLIC_URL` and
`COSTURA_SITE_ADDRESS` to one consistent origin, leaves `COSTURA_ENV`, `DATABASE_URL`,
`TEST_DATABASE_URL` and `COSTURA_API_URL` commented out because the compose file sets them,
prints the administrator secret once, and refuses to overwrite an existing `.env`. With
`--google-client-id <id>` it also writes the Google client; the secret comes from
`GOOGLE_CLIENT_SECRET` in the environment or a hidden prompt, so it stays out of the shell
history. Then go to [Start](#start). The rest of this section
is what it does, for a `.env` written by hand (`cp .env.example .env`).

`COSTURA_VERSION` in `.env.example` is already the release of that tag. Generate the
secrets (`just api::secret-generate` needs the development toolchain; these do not):

```
openssl rand -base64 32 | tr '+/' '-_'   # COSTURA_SECRET_KEY (a Fernet key)
openssl rand -hex 16                     # POSTGRES_PASSWORD
openssl rand -hex 16                     # POSTGRES_APP_PASSWORD
openssl rand -hex 24                     # COSTURA_OPERATOR_SECRET, if you use it
```

Put them in `.env`. Keep a copy of `COSTURA_SECRET_KEY` outside the host: without it no
stored provider key can be read, including from a backup.

The database has two roles. `POSTGRES_USER` / `POSTGRES_PASSWORD` own the schema and are used
only by the migration and by backup and restore. `POSTGRES_APP_USER` /
`POSTGRES_APP_PASSWORD` are the role the API, worker, and scheduler connect as: it reads
and writes rows and cannot change the schema. The migration creates that role and sets its
password on every run, so changing `POSTGRES_APP_PASSWORD` takes effect at the next
`just prod::up`. Use letters, digits, `_`, `-` and `.` in both passwords (the compose file
places them in a URL). They must differ and must not be the example value `costura`; the app
password is at least 12 characters. `just prod::up` refuses a short or shared password and
any space, quote or `\ $ : @ / % ? #`. The recipes that replace or delete data ask first;
`COSTURA_ASSUME_YES=1` answers yes for them in scripts.

The compose file forces `COSTURA_ENV=production` and points `DATABASE_URL` at the Postgres
service. It does not publish the API port.

### A managed PostgreSQL instead of the bundled one

Set `COSTURA_DATABASE_HOST` (and `COSTURA_DATABASE_PORT` when it is not 5432) to the server,
and `COSTURA_DATABASE_OPTIONS` to the connection options, for example
`sslmode=verify-full&sslrootcert=/run/costura/db-ca.crt`. Mount the provider's CA bundle at
that path in the `migrate`, `api`, `worker` and `scheduler` services with the override file in
[examples/external-postgres](../../examples/external-postgres/README.md), and point the
recipes at both files:

```
COSTURA_COMPOSE="docker compose -f docker-compose.prod.yml -f examples/external-postgres/docker-compose.external-postgres.yml" \
  just prod::up
```

Every `just prod::*` recipe passes `-f docker-compose.prod.yml`, so Compose does not read a
`docker-compose.override.yml` on its own. Requirements:

- PostgreSQL 18, the version CI tests.
- TLS with certificate verification (`sslmode=verify-full`).
- `POSTGRES_USER` can create and alter roles; the migration creates `POSTGRES_APP_USER` with
  it.
- Direct connections, or a pooler in session mode. Transaction pooling breaks the advisory
  locks the worker holds.

The bundled `postgres` service still starts and stays empty. `just prod::backup` and
`prod::restore` refuse to run while `COSTURA_DATABASE_HOST` names another server, because
they reach only the bundled service; back up and restore a managed database with the
provider's own backups. `just prod::upgrade` takes no backup in that case: it says so before
it asks, so take a provider snapshot first ([upgrade](upgrade.md)). `just prod::smoke-external-db` runs the stack against a second
PostgreSQL over verified TLS. `COSTURA_TRUSTED_PROXIES` defaults to
the Compose network, `COSTURA_SUBNET` (`172.28.0.0/24` unless set). Set `COSTURA_SUBNET` to a
free range when Docker answers "Pool overlaps with other one on this address space". Do not
publish port 8000.

Pick one sign-in method. Production refuses to start without one.

- Deployment administrator, the simple first login, including a local HTTP trial. Set
  `COSTURA_OPERATOR_EMAIL` and `COSTURA_OPERATOR_SECRET` (at least 24 characters;
  `just api::operator-secret` prints one). Set `COSTURA_SITE_ADDRESS=http://localhost`,
  `COSTURA_WEB_ORIGIN=http://localhost`, and `COSTURA_WEB_PUBLIC_URL=http://localhost`.
  Sign in with that e-mail and secret, then create the organization. This is not a public
  sign-up.
- Google. `just prod::init --host <name> --google-client-id <id>` sets all of this. By hand:
  set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `COSTURA_WEB_PUBLIC_URL` to the
  https origin browsers use (`https://costura.example.com`). The callback is
  `{COSTURA_WEB_PUBLIC_URL}/api/auth/google/callback`. Set `COSTURA_SITE_ADDRESS` to that
  hostname with no scheme. Caddy obtains the certificate itself. `COSTURA_WEB_ORIGIN` is the
  same origin. Sign-up defaults to invitation-only, and a fresh database has nobody who can
  send the first invitation. Keep the operator pair above for the first login, or set
  `COSTURA_SIGN_UP=open` only when you mean that, or list domains in
  `COSTURA_ALLOWED_EMAIL_DOMAINS`.

When both are set, the API logs a warning at startup: the administrator secret is a second
identity, as strong as `.env`, that keeps its memberships and roles. Once a Google account owns the
organization, retire it. Signed in as the administrator, open Settings, Account and choose
Sign out everywhere. Then remove `COSTURA_OPERATOR_EMAIL` and `COSTURA_OPERATOR_SECRET` from
`.env` and restart the API (`docker compose -f docker-compose.prod.yml up -d api`).

Plain HTTP is for `http://localhost` only. A named host sets a `Secure` cookie, which browsers
drop on plain HTTP. `.env.example` sets `COSTURA_WEB_ORIGIN=http://127.0.0.1:3000` for
development, which overrides the compose default; set it as above.

Provider keys in `.env` (`ANTHROPIC_ADMIN_KEY` and the others) are an optional fallback.
GitHub Copilot takes two: `COPILOT_GITHUB_TOKEN` (a classic token of an organization owner or
billing manager) and `COPILOT_ORG` (the organization login). The connector is experimental: it imports
one day per request and one request per seat holder per day, and GitHub returns no e-mail for
a seat, so an owner maps logins to e-mails with
`PUT /api/v1/orgs/{org}/providers/copilot/accounts/{account_id}/logins`. A day's seat cost is
split among the logins whose seat covered that day: assigned on or before it (GitHub's seat
creation date) and not yet gone from the inventory.
They apply only to the organization whose slug is `COSTURA_ORG` (`default` unless set), and
only while that organization stores no key of its own. The web app refuses that slug, so a
signed-in user cannot create it and receive the keys. To use the fallback, create it from
the host: `just prod::claim-owner default you@example.com --create`. Keys added in
Settings, Connections are stored encrypted per organization and need none of this.

## Start

```
just prod::doctor
just prod::up
```

`just prod::doctor` (`scripts/prod-doctor.sh`, needs only Docker and `python3`) prints one
line per problem and changes nothing: Docker, Compose v2 and at least 4 GB of memory, ports
80 and 443 free, the public hostname resolving, `COSTURA_VERSION` set to a release, the three
URL variables naming the origin Caddy serves, a sign-in method someone can use first, the
database passwords, `docker compose config`, and, once the API image is pulled, the settings
the API itself refuses to start with. It never prints a secret.

`just prod::up` checks the database passwords, pulls the published images for `COSTURA_VERSION`,
migrates, grants the runtime role, and starts the stack. To build from this checkout
instead: `just prod::up-local`.

Without `just` (Compose reads `COSTURA_VERSION` from `.env`):

```
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d --wait postgres
docker compose -f docker-compose.prod.yml run --rm migrate
docker compose -f docker-compose.prod.yml up -d --wait
```

The migration creates an empty database. Sign in, then create an organization; its address
cannot be the `COSTURA_ORG` slug, `demo`, or start with `demo-staging-` or `demo-retired-`. There is no
seeded `default` organization. `just prod::claim-owner <slug> <email>` makes the first owner
of an organization with no members; `--create` also creates it, which the `.env` provider
keys need (see above).

Open the site (`http://localhost`, or the https hostname). Sign in with the deployment
administrator secret or with Google. In Settings, Connections, add a provider key. The daily
scheduler enqueues syncs; the worker runs them. Sync now on the connection page runs one
organization without waiting for the schedule.

The sample organization is optional and public. `just prod::demo-seed` publishes it;
`just prod::demo-status` prints the dataset version and whether it is current;
`just prod::demo-refresh` rebuilds it through today. Anyone who can open the site can read
it without signing in, so seed it only when that is what you want. The company is fictional
and every figure is synthetic: thirteen months for Anthropic, OpenRouter, OpenAI and Cursor,
with no provider credential stored. It shows a key stuck in a retry loop, a Claude Code
login running a large migration, a gateway that loses traffic for four days, budgets that
are healthy, near the limit and exceeded, one provider whose control total counts late
usage, a failed import and a step that retried, and keys that are expired, archived or
disabled. Sign in links to it. Writes are refused. A failed rebuild leaves the published
sample in place and the next refresh deletes the abandoned build. Set
`COSTURA_DEMO_REFRESH=true` to rebuild a stale sample on the daily scheduler pass.

The API keeps anonymous reads of the sample in memory (`COSTURA_DEMO_CACHE_MB`, 64 by
default) until the dataset, its members or the UTC day change, and serves the next identical
read from there; the response carries `X-Costura-Cache: hit` or `miss`. A signed-in read
never uses it. With `COSTURA_DEMO_WARM_URL=http://web:3000`, the API renders the sample's
main pages through the web app when it starts, then checks every 30 seconds and renders them
again when one of those three changes, so the first visitor reads a filled cache. A host
that exists to show the sample sets `COSTURA_PUBLIC_DEMO_HOME=true`: `/` without a session
then opens the sample instead of the sign-in page, and a band pinned above every page links
to the GitHub repository.

`just prod::tieout-report --org <slug> [--months N]` prints each provider's reconciliation
verdicts for the newest months as percentages, with no amount, key, workspace or e-mail, so
it can be shared where the figures cannot.

`GET /live` on the API is the process. `GET /ready` and `GET /health` also check the database.
Caddy forwards `/live` and `/api/v1` to the API and every other path to the web app.
`/ready`, `/health`, and `/metrics` answer 404 through Caddy and stay on the Compose
network; the API container's healthcheck uses them. Point an external uptime check at
`/live`.

Next: [configuration](configuration.md), [upgrade](upgrade.md),
[backup and restore](backup-restore.md), [monitoring](monitoring.md),
[webhooks](webhooks.md), [troubleshooting](troubleshooting.md).
[examples/](../../examples/README.md) holds the external PostgreSQL override and a webhook
receiver as runnable files.
