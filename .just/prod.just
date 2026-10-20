_root := justfile_directory()
# COSTURA_COMPOSE and COSTURA_ENV_FILE point the recipes at another project (the smoke uses them).
_compose := env("COSTURA_COMPOSE", "docker compose -f docker-compose.prod.yml")

# Write a production .env with generated secrets: just prod::init [--email you@example.com] [--host costura.example.com] [--google-client-id <id>]
init *args:
    cd "{{_root}}" && bash scripts/prod-init.sh {{args}}

# Docker, memory, ports 80 and 443, DNS, the release, the URLs, sign-in, passwords, API settings.
# Check the host and the production .env without changing anything or printing a secret.
doctor:
    bash "{{_root}}/scripts/prod-doctor.sh"

# Pull published images, apply migrations, and start the single-node stack.
up:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{_root}}"
    bash scripts/prod-password.sh
    {{_compose}} pull
    {{_compose}} up -d --wait postgres
    {{_compose}} run --rm migrate
    {{_compose}} up -d --wait --remove-orphans

# The local images are tagged COSTURA_VERSION from .env, or `local` when it is unset.
# Build images locally, apply migrations, and start the stack (no registry pull).
up-local:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{_root}}"
    export COSTURA_VERSION="${COSTURA_VERSION:-local}"
    bash scripts/prod-password.sh
    {{_compose}} up -d --wait postgres
    {{_compose}} run --rm --build migrate
    {{_compose}} up -d --build --wait --remove-orphans

# Runs prod::doctor, a backup next to .env, the COSTURA_VERSION change, prod::up and
# secret-check. Check out the new tag first. Asks once; COSTURA_ASSUME_YES=1 skips it.
# Move to the release this checkout is at (version.txt).
upgrade:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{_root}}"
    source scripts/prod.sh
    env_file="${COSTURA_ENV_FILE:-.env}"
    [[ -f "$env_file" ]] || { echo "error: $env_file does not exist; write it with just prod::init" >&2; exit 1; }
    from=$(sed -n 's/^COSTURA_VERSION=//p' "$env_file" | tail -n 1)
    to=$(tr -d '[:space:]' < version.txt)
    if [[ "$from" == "$to" ]]; then
      echo "COSTURA_VERSION is already $to; check out a newer tag first (git fetch --tags && git checkout vX.Y.Z)"
      exit 0
    fi
    if [[ -n "$from" && "$(printf '%s\n%s\n' "$from" "$to" | sort -V | tail -n 1)" != "$to" ]]; then
      echo "error: $to is older than $from; there is no downgrade, restore a backup instead (docs/operations/upgrade.md#rollback)" >&2
      exit 1
    fi
    names() { sed -n 's/^\([A-Z][A-Z0-9_]*\)=.*/\1/p' "$1" | sort -u; }
    known() { sed -n 's/^#\{0,1\} \{0,1\}\([A-Z][A-Z0-9_]*\)[=:].*/\1/p' "$1" | sort -u; }
    added=$(comm -13 <(known "$env_file") <(names .env.example) | tr '\n' ' ')
    [[ -z "$added" ]] || echo "variables in .env.example that $env_file does not set (read CHANGELOG.md): $added"
    bash scripts/prod-doctor.sh
    confirm_or_exit "Upgrade from ${from:-an unknown release} to $to? A backup is taken first."
    recipient="${COSTURA_BACKUP_AGE_RECIPIENT:-$(sed -n 's/^COSTURA_BACKUP_AGE_RECIPIENT=//p' "$env_file" | tail -n 1)}"
    dump="$(dirname "$env_file")/costura-${from:-unknown}-$(date -u +%Y%m%dT%H%M%SZ).dump${recipient:+.age}"
    just prod::backup "$dump"
    trap 'echo "the upgrade stopped; to roll back set COSTURA_VERSION=$from in $env_file, check out v$from and run: just prod::restore $dump" >&2' ERR
    sed -i.bak "s/^COSTURA_VERSION=.*/COSTURA_VERSION=$to/" "$env_file"
    rm -f "$env_file.bak"
    export COSTURA_VERSION="$to"
    just prod::up
    just prod::secret-check
    echo "upgraded from ${from:-an unknown release} to $to; backup $dump"

# Apply Alembic migrations against the production database.
migrate:
    cd "{{_root}}" && {{_compose}} run --rm migrate

# Stop the stack. The database volume is kept.
down:
    cd "{{_root}}" && {{_compose}} down

# Follow logs for every service.
logs:
    cd "{{_root}}" && {{_compose}} logs -f

# Show service status.
ps:
    cd "{{_root}}" && {{_compose}} ps

# `--create` creates the organization first, which is how the operator opens the COSTURA_ORG
# organization the web app refuses.
# First owner of an organization with no members: just prod::claim-owner default me@example.com --create
claim-owner slug email *args:
    cd "{{_root}}" && {{_compose}} run --rm --no-deps api python -m costura.ops.claim_owner {{slug}} {{email}} {{args}}

# Load the sample organization. Asks before writing; COSTURA_ASSUME_YES=1 skips the question.
demo-seed:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{_root}}"
    source scripts/prod.sh
    confirm_or_exit "Load the sample organization into this production database?"
    {{_compose}} run --rm --no-deps api python -m costura.ops.demo_seed seed

# Rebuild the sample organization through today and swap it in. Asks first.
demo-refresh:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{_root}}"
    source scripts/prod.sh
    confirm_or_exit "Rebuild the sample organization in this production database?"
    {{_compose}} run --rm --no-deps api python -m costura.ops.demo_seed refresh

# Print the published sample's dataset version and freshness; exits 1 when stale.
demo-status:
    cd "{{_root}}" && {{_compose}} run --rm --no-deps api python -m costura.ops.demo_seed status

# Print pass/fail and percent deltas per provider and month, no amounts: just prod::tieout-report --org <slug>
tieout-report *args:
    cd "{{_root}}" && {{_compose}} run --rm --no-deps api python -m costura.ops.tieout {{args}}

# Delete raw pages and finished runs past retention. Asks first.
purge:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{_root}}"
    source scripts/prod.sh
    confirm_or_exit "Delete expired raw pages and finished runs in production?"
    {{_compose}} run --rm --no-deps api python -m costura.ops.purge

# Re-encrypt stored credentials and webhook URLs. Old key from COSTURA_SECRET_KEY_PREVIOUS or stdin.
secret-rotate:
    cd "{{_root}}" && {{_compose}} run --rm --no-deps -T api python -m costura.ops.secret rotate

# Decrypt every stored credential and webhook URL and print only the count.
secret-check:
    cd "{{_root}}" && {{_compose}} run --rm --no-deps api python -m costura.ops.secret check

# Write a custom-format dump readable only by this user, and `<dest>.version` with the
# release and Alembic revision it came from. With COSTURA_BACKUP_AGE_RECIPIENT set the dump
# is encrypted to that age recipient on the way out and no plaintext reaches the disk.
# Usage: just prod::backup costura.dump (costura.dump.age when encrypted)
backup dest:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{_root}}"
    umask 077
    bash scripts/prod-password.sh
    partial="{{dest}}.partial"
    trap 'rm -f "$partial" "$partial.version"' EXIT
    recipient="${COSTURA_BACKUP_AGE_RECIPIENT:-$(sed -n 's/^COSTURA_BACKUP_AGE_RECIPIENT=//p' "${COSTURA_ENV_FILE:-.env}" | tail -n 1)}"
    if [[ -n "$recipient" ]]; then
      command -v age >/dev/null || { echo "error: age is not installed; run: mise install" >&2; exit 1; }
      [[ "{{dest}}" == *.age ]] || { echo "error: an encrypted dump is named *.dump.age" >&2; exit 1; }
      {{_compose}} exec -T postgres \
        sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' | age -r "$recipient" > "$partial"
    else
      {{_compose}} exec -T postgres \
        sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$partial"
      {{_compose}} exec -T postgres pg_restore -l < "$partial" >/dev/null
    fi
    revision=$({{_compose}} exec -T postgres \
      sh -c 'psql -X -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT version_num FROM alembic_version"')
    version=$(sed -n 's/^COSTURA_VERSION=//p' "${COSTURA_ENV_FILE:-.env}" | tail -n 1)
    printf 'COSTURA_VERSION=%s\nalembic_revision=%s\n' "${version:-unknown}" "$revision" > "$partial.version"
    mv "$partial.version" "{{dest}}.version"
    mv "$partial" "{{dest}}"
    echo "backup written to {{dest}} (release ${version:-unknown}, revision $revision)"
    echo "keep a separate copy of COSTURA_SECRET_KEY${recipient:+ and of the age identity}"
    [[ -n "$recipient" ]] || echo "encrypt the dump before it leaves this host (COSTURA_BACKUP_AGE_RECIPIENT)"

# Replace the production database from a dump in one transaction, then re-apply the
# migration and the runtime role's grants. A *.age dump is decrypted with the identity file in
# COSTURA_BACKUP_AGE_IDENTITY.
# Usage: just prod::restore costura.dump (or costura.dump.age)
restore dump:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{_root}}"
    bash scripts/prod-password.sh
    source scripts/prod.sh
    identity=""
    if [[ "{{dump}}" == *.age ]]; then
      command -v age >/dev/null || { echo "error: age is not installed; run: mise install" >&2; exit 1; }
      identity="${COSTURA_BACKUP_AGE_IDENTITY:-$(sed -n 's/^COSTURA_BACKUP_AGE_IDENTITY=//p' "${COSTURA_ENV_FILE:-.env}" | tail -n 1)}"
      [[ -r "$identity" ]] || { echo "error: set COSTURA_BACKUP_AGE_IDENTITY to a readable age identity file" >&2; exit 1; }
      magic=$(age -d -i "$identity" "{{dump}}" 2>/dev/null | head -c 5 || true)
      [[ "$magic" == PGDMP ]] \
        || { echo "error: {{dump}} does not decrypt to a pg_dump archive with that identity" >&2; exit 1; }
    fi
    confirm_or_exit "Replace the production database from {{dump}}?"
    {{_compose}} up -d --wait postgres
    {{_compose}} stop api worker scheduler web proxy
    {{_compose}} exec -T postgres sh -c '
      set -eu
      umask 077
      dump=$(mktemp)
      sql=$(mktemp)
      trap "rm -f \"$dump\" \"$sql\"" EXIT
      cat > "$dump"
      pg_restore --no-owner --no-acl --exit-on-error -f "$sql" "$dump"
      psql -X -q -o /dev/null -v ON_ERROR_STOP=1 --single-transaction -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -c "DROP SCHEMA public CASCADE" -c "CREATE SCHEMA public" -f "$sql"
    ' < <(if [[ -n "$identity" ]]; then age -d -i "$identity" "{{dump}}"; else cat "{{dump}}"; fi)
    {{_compose}} run --rm migrate
    {{_compose}} up -d --wait api
    {{_compose}} run --rm --no-deps api python -m costura.ops.secret check

# Build the full production stack with synthetic credentials, check it, and delete the volumes.
smoke:
    bash "{{_root}}/scripts/smoke-prod.sh"

# Run the API, worker and scheduler against a second PostgreSQL over verified TLS, then delete it.
smoke-external-db:
    bash "{{_root}}/scripts/smoke-external-db.sh"
