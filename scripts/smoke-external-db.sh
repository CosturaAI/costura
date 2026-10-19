#!/usr/bin/env bash
# Run the production stack against a second PostgreSQL reached over verified TLS, then remove it.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"
project="${COSTURA_SMOKE_PROJECT:-costura-smoke-external-db}"
work=$(mktemp -d)
env_file="$work/env"
override="$work/external-db.yml"
compose=(docker compose --env-file "$env_file" -p "$project" -f docker-compose.prod.yml -f "$override")
cleanup() {
  "${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT

openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=smoke-ca" \
  -keyout "$work/ca.key" -out "$work/ca.crt" 2>/dev/null
openssl req -newkey rsa:2048 -nodes -subj "/CN=external-db" \
  -keyout "$work/server.key" -out "$work/server.csr" 2>/dev/null
printf 'subjectAltName=DNS:external-db\n' > "$work/san.ext"
openssl x509 -req -in "$work/server.csr" -CA "$work/ca.crt" -CAkey "$work/ca.key" \
  -CAcreateserial -days 1 -extfile "$work/san.ext" -out "$work/server.crt" 2>/dev/null
chmod 644 "$work"/*.crt "$work"/*.key

smoke_names=$(bash scripts/smoke-env.sh "$env_file")
# shellcheck disable=SC2086
unset $smoke_names COSTURA_DATABASE_HOST COSTURA_DATABASE_PORT COSTURA_DATABASE_OPTIONS || true
cat >> "$env_file" <<EOF
COSTURA_DATABASE_HOST=external-db
COSTURA_DATABASE_PORT=5432
COSTURA_DATABASE_OPTIONS=sslmode=verify-full&sslrootcert=/run/costura/db-ca.crt
EOF
image=$(sed -n 's/^    image: \(postgres:.*\)$/\1/p' docker-compose.prod.yml | head -n 1)
cat > "$override" <<EOF
services:
  external-db:
    image: $image
    environment:
      POSTGRES_DB: \${POSTGRES_DB}
      POSTGRES_USER: \${POSTGRES_USER}
      POSTGRES_PASSWORD: \${POSTGRES_PASSWORD}
    volumes:
      - $work:/certs:ro
    command:
      - sh
      - -c
      - >-
        cp /certs/server.crt /certs/server.key /tmp/ &&
        chown postgres /tmp/server.key && chmod 600 /tmp/server.key &&
        exec docker-entrypoint.sh postgres -c ssl=on
        -c ssl_cert_file=/tmp/server.crt -c ssl_key_file=/tmp/server.key
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U \$\$POSTGRES_USER -d \$\$POSTGRES_DB"]
      interval: 2s
      timeout: 3s
      retries: 30
  migrate:
    volumes: ["$work/ca.crt:/run/costura/db-ca.crt:ro"]
    depends_on:
      external-db:
        condition: service_healthy
  api:
    volumes: ["$work/ca.crt:/run/costura/db-ca.crt:ro"]
  worker:
    volumes: ["$work/ca.crt:/run/costura/db-ca.crt:ro"]
  scheduler:
    volumes: ["$work/ca.crt:/run/costura/db-ca.crt:ro"]
EOF

"${compose[@]}" up -d --wait postgres external-db
"${compose[@]}" build api
"${compose[@]}" run --rm migrate
"${compose[@]}" up -d --no-build --wait --wait-timeout 180 api worker scheduler
# Every runtime connection is TLS to external-db; the bundled service holds no table.
"${compose[@]}" exec -T api python -c '
from sqlalchemy import text
from costura.db import get_engine
with get_engine().connect() as conn:
    ssl = conn.execute(text("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")).scalar_one()
    user = conn.execute(text("SELECT current_user")).scalar_one()
    tables = conn.execute(text("SELECT count(*) FROM pg_tables WHERE schemaname = :s"), {"s": "public"}).scalar_one()
    assert ssl is True, "connection is not TLS"
    assert user == "costura_app", user
    assert tables > 10, tables
print("external database over TLS ok")
'
bundled=$("${compose[@]}" exec -T postgres psql -X -tA -U costura -d costura \
  -c "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
[[ "$bundled" == 0 ]] || { echo "error: the bundled postgres holds $bundled tables" >&2; exit 1; }
"${compose[@]}" exec -T api python -m costura.ops.worker --once
"${compose[@]}" exec -T api python -m costura.ops.secret check
echo "external database smoke ok"
