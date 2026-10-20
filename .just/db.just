_root := justfile_directory()

# Start PostgreSQL and wait for the healthcheck.
up:
    cd "{{_root}}" && docker compose up -d --wait postgres

# Set COSTURA_DEV_DB_PORT and the port of DATABASE_URL and TEST_DATABASE_URL in .env.
# Give this checkout's development PostgreSQL another host port: just db::port 5433
port number:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{_root}}"
    port="{{number}}"
    if [[ ! "$port" =~ ^[0-9]+$ ]] || ((port < 1024 || port > 65535)); then
      echo "error: the port is a number from 1024 to 65535" >&2
      exit 1
    fi
    [[ -f .env ]] || { echo "error: no .env; run just setup first" >&2; exit 1; }
    if grep -q '^COSTURA_DEV_DB_PORT=' .env; then
      sed -i.bak "s/^COSTURA_DEV_DB_PORT=.*/COSTURA_DEV_DB_PORT=$port/" .env
    else
      echo "COSTURA_DEV_DB_PORT=$port" >> .env
    fi
    sed -i.bak -E "s#^((TEST_)?DATABASE_URL=.*@(localhost|127\.0\.0\.1):)[0-9]+/#\1$port/#" .env
    rm -f .env.bak
    echo "COSTURA_DEV_DB_PORT, DATABASE_URL and TEST_DATABASE_URL use port $port; just dev starts PostgreSQL there"

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
