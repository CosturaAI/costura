_root := justfile_directory()

# Start PostgreSQL and wait for the healthcheck.
up:
    cd "{{_root}}" && docker compose up -d --wait postgres

# Stop PostgreSQL (data volume is kept).
down:
    cd "{{_root}}" && docker compose down

# Follow PostgreSQL logs.
logs:
    cd "{{_root}}" && docker compose logs -f postgres

# Open psql on the application database.
psql:
    cd "{{_root}}" && docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"

# Stop PostgreSQL and delete its data volume (asks for confirmation).
reset:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{_root}}"
    source scripts/prod.sh
    confirm_or_exit "This deletes the local PostgreSQL volume. Continue?"
    docker compose down -v
