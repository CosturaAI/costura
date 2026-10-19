# Backup and restore

The production database is the `costura_prod_pgdata` volume of the `costura-prod` compose
project (`docker-compose.prod.yml`). A backup can be taken while the stack runs. A restore
stops every writer first.

Provider credentials in the dump stay encrypted. Copy `COSTURA_SECRET_KEY` to a separate
place from the dump. A restore without that same key starts the API and then fails when it
tries to decrypt a provider key; `just prod::restore` runs the check that catches this.

Commands run inside the Postgres container as the schema owner (`POSTGRES_USER`) and use
that container's `POSTGRES_DB`. Do not `source .env`.

## Backup

```
just prod::backup "costura-$(date -u +%Y%m%dT%H%M%SZ).dump"
```

That writes a custom-format dump with mode 0600 to `<dump>.partial`, lists it with
`pg_restore -l`, writes `<dump>.version` with the `COSTURA_VERSION` from `.env` and the
Alembic revision in the database, and only then moves both into place. A failed or
interrupted backup leaves no file at `<dump>`. Keep both files together: a restore needs the
release that wrote the dump or a later one.

The dump contains encrypted provider keys, hashed sessions, memberships and billing rows.
Without further setup it is not encrypted.

### Encrypted backups

Set `COSTURA_BACKUP_AGE_RECIPIENT` in `.env` to an [age](https://age-encryption.org) public
key (`age1...`, or an SSH public key). `mise install` installs the pinned `age`. Create the
key pair once, away from the host that keeps the dumps:

```
age-keygen -o costura-backup.key        # prints the public key: age1...
```

With the recipient set, name the dump `*.dump.age`:

```
just prod::backup "costura-$(date -u +%Y%m%dT%H%M%SZ).dump.age"
```

`pg_dump` streams straight into `age`, so no plaintext dump reaches the disk. The
`pg_restore -l` listing is skipped, because the host holds only the public key; the restore
checks the archive after decrypting it. Keep the private key (`costura-backup.key`) and
`COSTURA_SECRET_KEY` in two places other than the dumps.

### Scheduled backups off the host

A systemd timer that writes one encrypted dump a day, keeps the newest 14 and copies them
off the host. Adjust the paths, the user and the copy command:

```
# /etc/systemd/system/costura-backup.service
[Service]
Type=oneshot
User=costura
WorkingDirectory=/opt/costura
ExecStart=/bin/bash -c 'set -euo pipefail; d=/var/backups/costura; \
  just prod::backup "$d/costura-$(date -u +%%Y%%m%%dT%%H%%M%%SZ).dump.age"; \
  ls -1t "$d"/costura-*.dump.age | tail -n +15 | while read -r f; do rm -f "$f" "$f.version"; done; \
  rclone sync "$d" offsite:costura-backups'

# /etc/systemd/system/costura-backup.timer
[Timer]
OnCalendar=*-*-* 03:30:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
```

`systemctl enable --now costura-backup.timer` starts it; `systemctl list-timers` shows the
next run. `rclone` stands for any copy tool that reaches another machine or a bucket; the
dumps are already encrypted, so the destination needs no extra encryption.

## Restore

Set `COSTURA_VERSION` in `.env` to the release named in `<dump>.version` (or a later one),
then:

```
just prod::restore costura.dump
```

An encrypted dump needs the private key: set `COSTURA_BACKUP_AGE_IDENTITY` to the key file
and pass the `.dump.age` file. The recipe decrypts the first bytes and stops before asking
when the key does not open the dump or the result is not a `pg_dump` archive.

```
COSTURA_BACKUP_AGE_IDENTITY=/secure/costura-backup.key just prod::restore costura.dump.age
```

The recipe asks first. It stops the API, worker, scheduler, web app and proxy, converts the
dump to SQL inside the Postgres container, and then in one transaction drops the `public`
schema, recreates it, and loads the dump. A truncated or unreadable dump fails before the
drop or rolls back with it, and the database stays as it was. Grants from the source
database are not restored. The recipe then runs `migrate`, which upgrades the restored
schema to the image's revision when the dump is older and grants the runtime role
(`POSTGRES_APP_USER`) access to the restored tables. It starts the API and runs
`just prod::secret-check`, which prints how many stored secrets (provider credentials and
webhook URLs and signing secrets) decrypted and exits non-zero when the current
`COSTURA_SECRET_KEY` cannot read them. It does not print the keys.

Restore uses the images already named by `COSTURA_VERSION`; it does not rebuild them and
does not change `COSTURA_DEMO_REFRESH`. Start the rest of the stack with `just prod::up`
after the check passes.

A dump from a newer release than `COSTURA_VERSION` fails at `migrate` with an unknown
Alembic revision. Set the newer version and run the restore again.
