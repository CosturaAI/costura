#!/usr/bin/env bash
# Build and start the production Compose stack with synthetic credentials, then remove it.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"
project="${COSTURA_SMOKE_PROJECT:-costura-smoke-prod}"
env_file=$(mktemp)
cleanup() {
  docker compose --env-file "$env_file" -p "$project" -f docker-compose.prod.yml down -v --remove-orphans >/dev/null 2>&1 || true
  rm -f "$env_file"
}
trap cleanup EXIT

# `just` exports the repo-root .env. Those values override --env-file, so drop them.
smoke_names=$(bash scripts/smoke-env.sh "$env_file")
# shellcheck disable=SC2086
unset $smoke_names || true
compose=(docker compose --env-file "$env_file" -p "$project" -f docker-compose.prod.yml)
"${compose[@]}" up -d --wait postgres
"${compose[@]}" build
"${compose[@]}" run --rm migrate
# `up --build` can interpolate the repo-root .env instead of --env-file. Build first.
if ! "${compose[@]}" up -d --no-build --wait --wait-timeout 180 --remove-orphans; then
  "${compose[@]}" ps || true
  "${compose[@]}" logs --no-color api worker scheduler | python3 -c '
import sys
text = sys.stdin.read()
lines = [line for line in text.splitlines() if any(word in line.lower() for word in ("error", "refusing", "traceback", "exception"))]
sys.stdout.write("\n".join(lines[-50:]))
'
  exit 1
fi
# The smoke site is http://localhost. Caddy answers another Host with an empty 200.
proxy=(curl -sS -H "Host: localhost")
live=$("${proxy[@]}" -f http://127.0.0.1:18080/live)
python3 -c 'import json,sys; body=json.loads(sys.argv[1]); assert body.get("status")=="ok", body' "$live"
echo "proxy /live $live"
for path in ready health metrics; do
  status=$("${proxy[@]}" -o /dev/null -w '%{http_code}' "http://127.0.0.1:18080/$path")
  [[ "$status" == 404 ]] || { echo "error: the proxy publishes /$path ($status)" >&2; exit 1; }
done
sign_in=$("${proxy[@]}" -f -D - -o /dev/null http://127.0.0.1:18080/sign-in)
grep -qi "^content-security-policy: .*'nonce-" <<<"$sign_in" \
  || { echo "error: /sign-in has no nonce-based CSP" >&2; exit 1; }
"${compose[@]}" exec -T api python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/ready", timeout=3)'
# The runtime role reads and writes rows and cannot change the schema.
"${compose[@]}" exec -T api python -c '
from sqlalchemy import text
from costura.db import get_engine
with get_engine().connect() as conn:
    user = conn.execute(text("SELECT current_user")).scalar_one()
    create = conn.execute(
        text("SELECT has_schema_privilege(current_user, :schema, :privilege)"),
        {"schema": "public", "privilege": "CREATE"},
    ).scalar_one()
    assert user == "costura_app", user
    assert create is False, "runtime role can create tables"
print("runtime role ok")
'
"${compose[@]}" exec -T api python -m costura.ops.heartbeat --role worker --max-age 45
"${compose[@]}" exec -T api python -m costura.ops.heartbeat --role scheduler --max-age 45
# The write paths a worker and the sample refresh take, as the runtime role.
"${compose[@]}" exec -T api python -m costura.ops.worker --once
"${compose[@]}" exec -T api python -m costura.ops.demo_seed seed
"${compose[@]}" exec -T api python -m costura.ops.demo_seed status
# The backup and restore recipes themselves, against this project.
export COSTURA_COMPOSE="${compose[*]}" COSTURA_ENV_FILE="$env_file" COSTURA_ASSUME_YES=1
dump_dir=$(mktemp -d)
just --dotenv-path "$env_file" prod::backup "$dump_dir/smoke.dump"
[[ -s "$dump_dir/smoke.dump" && -s "$dump_dir/smoke.dump.version" ]] \
  || { echo "error: the backup left no dump or no version sidecar" >&2; exit 1; }
just --dotenv-path "$env_file" prod::restore "$dump_dir/smoke.dump"
# The encrypted round trip: an age recipient on the way out, the identity on the way back.
if ! command -v age >/dev/null && command -v mise >/dev/null; then
  PATH="$(dirname "$(mise which age)"):$PATH"
fi
command -v age >/dev/null || { echo "error: age is not installed; run: mise install" >&2; exit 1; }
age-keygen -o "$dump_dir/identity.txt" 2>/dev/null
COSTURA_BACKUP_AGE_RECIPIENT=$(age-keygen -y "$dump_dir/identity.txt") \
  just --dotenv-path "$env_file" prod::backup "$dump_dir/smoke.dump.age"
[[ "$(head -c 5 "$dump_dir/smoke.dump.age")" != PGDMP && -s "$dump_dir/smoke.dump.age.version" ]] \
  || { echo "error: the encrypted backup is plaintext or has no version sidecar" >&2; exit 1; }
COSTURA_BACKUP_AGE_IDENTITY="$dump_dir/identity.txt" \
  just --dotenv-path "$env_file" prod::restore "$dump_dir/smoke.dump.age"
rm -rf "$dump_dir"
echo "prod smoke ok"
