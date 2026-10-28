#!/usr/bin/env bash
# Prove a local install: Postgres, migrations, the public demo organization,
# the API, and the Next.js sign-in page that reads that organization.
# `just smoke` runs this. The database is a disposable Compose project
# (`costura-smoke`) on 127.0.0.1:5433 so it does not take the dev container
# name or port. It is removed on exit. The API and web processes stop too.
set -euo pipefail
set -m

root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"

api_port="${COSTURA_SMOKE_API_PORT:-18000}"
web_port="${COSTURA_SMOKE_WEB_PORT:-13000}"
db_port="${COSTURA_SMOKE_DB_PORT:-5433}"
api_url="http://127.0.0.1:${api_port}"
web_url="http://127.0.0.1:${web_port}"

for tool in docker just uv pnpm python3 curl; do
  command -v "$tool" >/dev/null || { echo "error: $tool is not installed" >&2; exit 1; }
done

port_busy() {
  python3 - "$1" <<'PY'
import socket, sys
with socket.socket() as sock:
    sock.settimeout(1)
    sys.exit(0 if sock.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PY
}

for pair in "COSTURA_SMOKE_API_PORT:$api_port" "COSTURA_SMOKE_WEB_PORT:$web_port" "COSTURA_SMOKE_DB_PORT:$db_port"; do
  if port_busy "${pair#*:}"; then
    echo "error: port ${pair#*:} is already in use; set ${pair%%:*} to a free port" >&2
    exit 1
  fi
done

# Disposable database, independent of a developer .env and of `just db::up`.
export COSTURA_ENV=development
export POSTGRES_DB=costura
export POSTGRES_USER=costura
export POSTGRES_PASSWORD=costura
export DATABASE_URL="postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${db_port}/${POSTGRES_DB}"
export COSTURA_API_URL="$api_url"
export COSTURA_WEB_ORIGIN="$web_url"

override=$(mktemp)
log_dir=$(mktemp -d)
api_pid=""
web_pid=""
cat >"$override" <<EOF
services:
  postgres:
    container_name: costura-smoke-postgres
    ports: !override
      - "127.0.0.1:${db_port}:5432"
EOF

compose() {
  docker compose -p costura-smoke -f "$root/docker-compose.yml" -f "$override" "$@"
}

stop_pid() {
  local pid=$1
  [[ -n "$pid" ]] || return 0
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
}

cleanup() {
  local status=$?
  trap - EXIT
  stop_pid "$api_pid"
  stop_pid "$web_pid"
  wait 2>/dev/null || true
  if [[ $status -ne 0 ]]; then
    echo "--- api log ---" >&2
    tail -n 80 "$log_dir/api.log" >&2 || true
    echo "--- web log ---" >&2
    tail -n 80 "$log_dir/web.log" >&2 || true
  fi
  compose down -v --remove-orphans
  rm -f "$override"
  rm -rf "$log_dir"
  exit "$status"
}
trap cleanup EXIT

compose up -d --wait postgres
just api::migrate
just api::demo-seed

(
  cd "$root/apps/api"
  exec uv run uvicorn costura.main:app --host 127.0.0.1 --port "$api_port"
) >"$log_dir/api.log" 2>&1 &
api_pid=$!

[[ -n "${COSTURA_WEB_PREBUILT:-}" ]] || (cd "$root/apps/web" && pnpm build) >"$log_dir/web-build.log" 2>&1 || {
  tail -n 80 "$log_dir/web-build.log" >&2
  exit 1
}

(
  cd "$root/apps/web"
  exec pnpm start --hostname 127.0.0.1 --port "$web_port"
) >"$log_dir/web.log" 2>&1 &
web_pid=$!

wait_http() {
  local url=$1
  local tries=$2
  local i
  for ((i = 1; i <= tries; i++)); do
    if curl --fail --silent --max-time 5 "$url" >/dev/null; then
      return 0
    fi
    if ! kill -0 "$api_pid" 2>/dev/null; then
      echo "error: API process exited before $url answered" >&2
      return 1
    fi
    sleep 2
  done
  echo "error: timed out waiting for $url" >&2
  return 1
}

wait_http "$api_url/live" 45
ready=$(curl --fail --silent --show-error --max-time 10 "$api_url/ready")
python3 -c 'import json,sys; body=json.loads(sys.argv[1]); assert body=={"status":"ok","database":"ok"}, body' "$ready"
echo "ready $ready"

month=$(date -u +%Y-%m)
org=$(curl --fail --silent --show-error --max-time 15 "$api_url/api/v1/orgs/demo")
python3 -c 'import json,sys; body=json.loads(sys.argv[1]); assert body["slug"]=="demo" and body["is_demo"] is True, body' "$org"

overview=$(curl --fail --silent --show-error --max-time 30 \
  "$api_url/api/v1/orgs/demo/providers/all/months/${month}/summary")
python3 -c 'import json,sys; body=json.loads(sys.argv[1]); assert body["month"]==sys.argv[2], body; total=body["total"]; assert total not in ("", "0.00"), body; print("demo overview", body["month"], total)' "$overview" "$month"

sign_in=""
for ((i = 1; i <= 90; i++)); do
  if ! kill -0 "$web_pid" 2>/dev/null; then
    echo "error: web process exited" >&2
    exit 1
  fi
  if sign_in=$(curl --fail --silent --max-time 60 "$web_url/sign-in"); then
    if grep -q '/o/demo' <<<"$sign_in" && grep -q 'Explore the sample organization' <<<"$sign_in"; then
      echo "sign-in page loaded the demo organization through Next"
      echo "smoke ok: $api_url and $web_url"
      exit 0
    fi
  fi
  sleep 2
done
echo "error: sign-in page did not render the demo organization link" >&2
exit 1
