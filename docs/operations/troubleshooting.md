# Troubleshooting

Start with `just doctor`. It checks that the tools are on `PATH` at the versions in
`mise.toml`, that the Docker daemon answers, that ports 8000, 3000 and 5432 are free, and the
`.env` key, without printing a secret. An empty `COSTURA_SECRET_KEY` is a warning: `just dev`
runs without it. Then find the symptom below.

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
`COSTURA_WEB_PUBLIC_URL`. `docker compose -f docker-compose.prod.yml logs api` shows it.

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
