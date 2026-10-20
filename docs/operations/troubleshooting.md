# Troubleshooting

On a production host, start with `just prod::doctor`: Docker, memory, ports 80 and 443, DNS,
`COSTURA_VERSION`, the URL variables, sign-in, the passwords and the API settings, one line
each, without printing a secret. On a development checkout, start with `just doctor`. It
prints one line per problem, without printing a secret: a tool
missing from `PATH` or at another version than `mise.toml` (a different `just` is a warning),
the Docker daemon down, port 8000 or 3000 taken, port 5432 held by anything other than this
checkout's PostgreSQL, a `next dev` from this checkout still running, and an invalid
`COSTURA_SECRET_KEY`. `just dev` runs it before starting anything. Then find the symptom
below.

## Local development

`just dev` stops on the first `just doctor` error. Each message names its fix:

- `node is 22.x, mise.toml pins ...` (or `uv`, `pnpm`): the shell resolves tools outside
  mise. Activate mise (`eval "$(mise activate zsh)"`) or run `mise exec -- just dev`.
- `just: command not found`: mise is not active; `mise exec -- just dev` works without it.
- `port 8000 is already in use` or `port 3000`: another stack runs. `lsof -nP -iTCP:3000
  -sTCP:LISTEN` names the process.
- `a next dev server from this checkout is running at ... (pid N)`: Next.js allows one dev
  server per directory, whatever its port, so a second one exits and takes the stack down.
  Stop it with the `kill N` the message prints.
- `port 5432 is held by the container <name> (started from <path>)`: another checkout or
  worktree runs its PostgreSQL. Stop it with the `docker stop` the message prints, or give
  this checkout its own port: `COSTURA_DEV_DB_PORT=5433` in `.env`, and the same port in
  `DATABASE_URL` and `TEST_DATABASE_URL`. Each checkout's container is named after its
  directory (`<directory>-postgres-1`) and keeps its own data volume.
- `DATABASE_URL uses port 5432, the development PostgreSQL listens on 5433`: `.env` sets
  `COSTURA_DEV_DB_PORT` without the matching port in that URL.

## `just prod::up` stops before starting the stack

The password check runs first and prints one line naming the variable:
`POSTGRES_PASSWORD is the example value`, `must be at least 12 characters`, `contains a
character that breaks the database URL`. Use letters, digits and `_-.`, keep the two
passwords different, and run again. `just prod::init` generates values that pass.

## Docker answers "Pool overlaps with other one on this address space"

Another network on the host uses `172.28.0.0/24`. Set `COSTURA_SUBNET` in `.env` to a free
range, such as `172.29.0.0/24`, and run `just prod::up` again.

## Sign-in succeeds but the next page asks to sign in again

A named host sets a `Secure` session cookie, which browsers drop on plain HTTP. Either use
`http://localhost` for a local trial, or set `COSTURA_SITE_ADDRESS` to the hostname so Caddy
serves HTTPS. Check that `COSTURA_WEB_ORIGIN` and `COSTURA_WEB_PUBLIC_URL` name the same
origin as the address in the browser ([configuration](configuration.md#addresses)).

## The API refuses to start in production

The log line starts with `refusing to start:` and lists each problem: no sign-in method
(operator pair with a secret of at least 24 characters, or Google), a missing or invalid
`COSTURA_SECRET_KEY`, the example database password, or Google configured without an https
`COSTURA_WEB_PUBLIC_URL`. A value the settings cannot parse, such as `COSTURA_SCHEDULE_AT=6am`,
is refused the same way before anything starts, and the API, the worker, the scheduler and the
migration print it as one `error: refusing to start: ...` line that names the variable and
never its value. `docker compose -f docker-compose.prod.yml logs api` shows it.

## Connecting a key fails

- "rejected the key (HTTP 401/403)": the provider refused it. It is revoked, or it is a
  regular API key where the provider needs an admin, management or team key. The message
  names the expected key type and prefix.
- "accepted the key but ...": the key authenticates but cannot read what the import needs,
  such as an OpenRouter key that is not a management key.

The [configuration](configuration.md#provider-fallback-keys) table lists the key each
provider expects. Replace the key on its card in Settings, Connections.

## Nothing imports after a key is connected

The scheduler enqueues and the worker runs. If the connection card says no worker has
picked the import up, the worker is not running: `docker compose -f docker-compose.prod.yml
ps worker`. Sync now on the card runs one organization without waiting for the schedule.

## Reconciliation fails by a small amount

- Against the provider total: a recent day the provider has not finished reporting. The
  next import corrects it. Anthropic restates analytics for about 7 days after month end.
- Against the invoice: tax, credits and restatements live only on the bill. The delta and
  the note on the invoice are the information.

## Restore refuses a backup

A backup taken on a newer release carries a newer migration than the running images. Run
the release the backup's `.version` file names, then restore
([backup and restore](backup-restore.md)).

## The schema did not change after an upgrade

`migrate` runs with the image of `COSTURA_VERSION`. Pulling a new tag without changing
`COSTURA_VERSION` in `.env` keeps the old migration. Set it and run `just prod::up`
([upgrade](upgrade.md)).

## The API answered with an error code

Every refusal carries `code` next to `detail`; [errors](errors.md) lists each code with its
status and what to do. In the web app the code is under "Technical details", and "Copy
details" copies the whole reference for an issue.

## Still stuck

Open an issue with `just doctor` output and the failing command's last lines; never paste
`.env`. Security problems go to the private form in [SECURITY.md](../../SECURITY.md).
