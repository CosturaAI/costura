# Upgrade

One node, one replica of each unit. Releases are listed in [CHANGELOG.md](../../CHANGELOG.md)
and on the GitHub releases page; read the entry for every release you skip.

Skipping releases is supported: the migrations form one linear chain
(`just api::migration-check` enforces one head), so moving from `0.1.0` straight to a later
release applies every revision in between. No CI job upgrades a running install from one
release to another. CI applies the whole chain to an empty database
(`just api::migration-check`), starts the current checkout from scratch, and round-trips a
backup through `just prod::restore` on the same release (`just prod::smoke`). Take a backup
first and read every skipped entry for steps that are not migrations, such as a new
required variable.

From the repository root, check out the release and run one recipe:

<!-- x-release-please-start-version -->

```
git fetch --tags && git checkout v0.3.0
just prod::upgrade
```

<!-- x-release-please-end -->

`just prod::upgrade` reads the target release from the checkout's `version.txt` and refuses
an older one. In order, it:

1. Lists the variables `.env.example` names that `.env` does not set (read the changelog
   for each) and checks the passwords.
2. Pulls the new release's images while the old stack keeps running.
3. Runs `just prod::doctor` with the API settings check in the new release's image
   (`COSTURA_TARGET_VERSION`).
4. Asks once (`COSTURA_ASSUME_YES=1` skips the question; without a terminal and without
   that variable it stops with an error).
5. Writes a backup next to `.env` (`.dump.age` when `COSTURA_BACKUP_AGE_RECIPIENT` is set).
   With an external PostgreSQL (`COSTURA_DATABASE_HOST` set to a server other than
   `postgres`) it takes no backup: it prints that line before the question, so take a
   snapshot with the provider's backups first.
6. Sets `COSTURA_VERSION` in `.env`.
7. Stops the API, the worker, the scheduler and the web app, so no process of the old
   release writes while the schema changes. The worker gets up to 120 seconds to finish
   its sync (`stop_grace_period`). The site is down from here until step 8 ends.
8. Runs `just prod::up` (Postgres, the migration, then every service) and
   `just prod::secret-check`, and prints the backup's path.

When a step after the backup fails it prints the rollback: the previous `COSTURA_VERSION`,
its tag, the `just prod::restore` command for that backup (or the provider snapshot), and
`just prod::up`.

The same steps by hand, with the provenance check the recipe does not run:

<!-- x-release-please-start-version -->

```
# 1. Note the release you are leaving, and take a backup.
grep '^COSTURA_VERSION=' .env
just prod::backup "costura-$(date -u +%Y%m%dT%H%M%SZ).dump"

# 2. Check out the new release's compose file and recipes.
git fetch --tags && git checkout v0.3.0

# 3. Verify that GitHub Actions in this repository built the published images.
for image in api web proxy; do
  gh attestation verify "oci://ghcr.io/costuraai/costura-$image:0.3.0" --owner CosturaAI
done

# 4. Set the release you are moving to in .env, stop the old writers, then pull,
#    migrate and restart.
#    COSTURA_VERSION=0.3.0
docker compose -f docker-compose.prod.yml stop api worker scheduler web
just prod::up
```

<!-- x-release-please-end -->

`gh attestation verify` checks the provenance that
[`publish-images.yml`](../../.github/workflows/publish-images.yml) attached to each image
against the repository's signing identity; it needs the `gh` CLI signed in to GitHub and
exits non-zero when an image was not built by that workflow. Skipping it does not change
what `just prod::up` does.

Keep `COSTURA_SECRET_KEY` in a separate place from the dump
([backup and restore](backup-restore.md)). Compare `.env.example` with your `.env` after
the checkout: a release that adds a required variable fails at `just prod::up` with the
variable's name.

Stored provider keys and webhook URLs written before key binding still read, but they are
not tied to their row yet. After an upgrade, `just prod::secret-check` reports how many are
"not yet bound"; `just prod::secret-rotate` binds them (with `COSTURA_SECRET_KEY_PREVIOUS`
unset and nothing on stdin it re-encrypts under the current key).

`just prod::up` pulls `ghcr.io/costuraai/costura-*:${COSTURA_VERSION}`, waits for Postgres,
runs Alembic `upgrade head` and re-applies the runtime role's grants on every run
(`compose run --rm migrate`), and restarts the stack. The migration comes from the image
`COSTURA_VERSION` names, so a new schema needs `COSTURA_VERSION` changed first; on the same
release the migration finds nothing to apply. By hand, `just prod::up` does not stop the old
API, worker and scheduler before it migrates; stop them first, as step 4 of the commands
below does.

Order that matters: Postgres is healthy, then the migration, then the API, worker,
scheduler, and web app. Caddy waits until the API and the web app are healthy. The worker and the scheduler start only after the migration container exits 0.
They do not need the operator secret or Google credentials. An upgrade keeps
`COSTURA_DEMO_REFRESH` at the value in `.env`. `docker-compose.prod.yml` defaults it to
`false`, so the daily pass rebuilds a stale public sample only when that variable is `true`.

Check:

```
docker compose -f docker-compose.prod.yml ps
curl -fsS "http://localhost:${COSTURA_HTTP_PORT:-80}/live"
docker compose -f docker-compose.prod.yml exec -T api \
  python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/ready", timeout=3)'
just prod::secret-check
```

Use `https://<hostname>/live` when `COSTURA_SITE_ADDRESS` is a public hostname. `/ready`
checks the database and is reachable only inside the Compose network.

## Rollback

If the new API or worker fails before `migrate` has run, set `COSTURA_VERSION` in `.env`
back to the release you noted in step 1, check out that tag, and run `just prod::up`.
That pulls the previous images and does not invent an Alembic downgrade.

If `migrate` has already run against the newer schema, set `COSTURA_VERSION` back to the
previous release and restore the backup taken in step 1 with `just prod::restore`, then
start the rest of the stack with `just prod::up`. With an external PostgreSQL, restore the
provider snapshot instead. Do not guess an Alembic downgrade.
