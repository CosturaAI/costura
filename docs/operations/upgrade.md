# Upgrade

One node, one replica of each unit. Releases are listed in [CHANGELOG.md](../../CHANGELOG.md)
and on the GitHub releases page; read the entry for every release you skip.

Skipping releases is supported: the migrations form one linear chain
(`just api::migration-check` enforces one head), so moving from `0.1.0` straight to a later
release applies every revision in between. Each release is tested only from the release
before it, so take a backup first and read every skipped entry for steps that are not
migrations, such as a new required variable.

From the repository root, check out the release and run one recipe:

<!-- x-release-please-start-version -->

```
git fetch --tags && git checkout v0.2.1
just prod::upgrade
```

<!-- x-release-please-end -->

`just prod::upgrade` reads the target release from the checkout's `version.txt` and refuses
an older one. It lists the variables `.env.example` names that `.env` does not set (read
the changelog for each), runs `just prod::doctor`, asks once (`COSTURA_ASSUME_YES=1` skips
the question), writes a backup next to `.env` (`.dump.age` when
`COSTURA_BACKUP_AGE_RECIPIENT` is set), sets `COSTURA_VERSION`, runs `just prod::up` and
`just prod::secret-check`, and prints the backup's path. When a step after the backup fails
it prints the rollback: the previous `COSTURA_VERSION`, its tag and the `just prod::restore`
command for that backup.

The same steps by hand, with the provenance check the recipe does not run:

<!-- x-release-please-start-version -->

```
# 1. Note the release you are leaving, and take a backup.
grep '^COSTURA_VERSION=' .env
just prod::backup "costura-$(date -u +%Y%m%dT%H%M%SZ).dump"

# 2. Check out the new release's compose file and recipes.
git fetch --tags && git checkout v0.2.1

# 3. Verify that GitHub Actions in this repository built the published images.
for image in api web proxy; do
  gh attestation verify "oci://ghcr.io/costuraai/costura-$image:0.2.1" --owner CosturaAI
done

# 4. Set the release you are moving to in .env, then pull, migrate and restart.
#    COSTURA_VERSION=0.2.1
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
runs Alembic `upgrade head` and re-applies the runtime role's grants, and restarts the
stack. `up` alone does not re-run a migration container that already exited successfully
on the same image; change `COSTURA_VERSION` (or run `just prod::migrate` after a local
rebuild).

Order that matters: Postgres is healthy, then the migration, then the API, worker,
scheduler, and web app. Caddy waits until the API is healthy and the web container has
started. The worker and the scheduler start only after the migration container exits 0.
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
previous release and restore the backup taken in step 1 with `just prod::restore`. Do not
guess an Alembic downgrade.
