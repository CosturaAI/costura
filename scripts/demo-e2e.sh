#!/usr/bin/env bash
# Browser suite of the public sample organization against the real stack: a disposable
# PostgreSQL, migrations, the sample built as of a fixed day, the API and the production
# Next build. `just web::test-e2e-demo` builds the web app and runs this; extra arguments go to
# Playwright (`--update-snapshots`, `--grep`). The mock-API suite (`just web::test-e2e`) stays
# separate. The database is the Compose project `costura-demo-e2e` on 127.0.0.1:5434, removed
# on exit with the API and web processes.
set -euo pipefail
set -m

root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"

api_port="${COSTURA_DEMO_E2E_API_PORT:-18100}"
web_port="${COSTURA_DEMO_E2E_WEB_PORT:-13100}"
db_port="${COSTURA_DEMO_E2E_DB_PORT:-5434}"
# The day the sample is built as of: fixed, so amounts, anomalies and snapshots repeat.
today="${COSTURA_DEMO_E2E_TODAY:-2026-09-15}"
api_url="http://127.0.0.1:${api_port}"
web_url="http://127.0.0.1:${web_port}"

for tool in docker just uv pnpm python3 curl; do
  command -v "$tool" >/dev/null || { echo "error: $tool is not installed" >&2; exit 1; }
done
[[ -f "$root/apps/web/.next/BUILD_ID" ]] || {
  echo "error: no production build in apps/web/.next; run just web::test-e2e-demo" >&2
  exit 1
}

port_busy() {
  python3 - "$1" <<'PY'
import socket, sys
with socket.socket() as sock:
    sock.settimeout(1)
    sys.exit(0 if sock.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PY
}

for port in "$api_port" "$web_port" "$db_port"; do
  if port_busy "$port"; then
    echo "error: port $port is already in use" >&2
    exit 1
  fi
done

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
    container_name: costura-demo-e2e-postgres
    ports: !override
      - "127.0.0.1:${db_port}:5432"
EOF

compose() {
  docker compose -p costura-demo-e2e -f "$root/docker-compose.yml" -f "$override" "$@"
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
(cd "$root/apps/api" && uv run python -m costura.ops.demo_seed seed --today "$today")

(
  cd "$root/apps/api"
  exec uv run uvicorn costura.main:app --host 127.0.0.1 --port "$api_port"
) >"$log_dir/api.log" 2>&1 &
api_pid=$!

(
  cd "$root/apps/web"
  exec pnpm start --hostname 127.0.0.1 --port "$web_port"
) >"$log_dir/web.log" 2>&1 &
web_pid=$!

wait_http() {
  local url=$1
  local i
  for ((i = 1; i <= 60; i++)); do
    if curl --fail --silent --max-time 5 "$url" >/dev/null; then
      return 0
    fi
    sleep 2
  done
  echo "error: timed out waiting for $url" >&2
  return 1
}

wait_http "$api_url/ready"
wait_http "$web_url/sign-in"

cd "$root/apps/web"
if [[ -n "${COSTURA_PLAYWRIGHT_DOCKER_IMAGE:-}" && "$(uname -s)" == "Linux" ]]; then
  docker run --rm --network host --user "$(id -u):$(id -g)" \
    -v "$root:/work" -w /work/apps/web \
    -e PLAYWRIGHT_BASE_URL="$web_url" \
    -e COSTURA_DEMO_E2E_API="$api_url" \
    -e HOME=/tmp -e CI \
    "$COSTURA_PLAYWRIGHT_DOCKER_IMAGE" \
    npx playwright test --config playwright.demo.config.ts "$@"
elif [[ -n "${COSTURA_PLAYWRIGHT_DOCKER_IMAGE:-}" ]]; then
  docker run --rm \
    --add-host=host.docker.internal:host-gateway \
    -v "$root:/work" -w /work/apps/web \
    -e PLAYWRIGHT_BASE_URL="$web_url" \
    -e COSTURA_DEMO_E2E_API="$api_url" \
    -e HOME=/tmp -e CI \
    "$COSTURA_PLAYWRIGHT_DOCKER_IMAGE" \
    bash -c 'node -e "
      const net = require(\"net\");
      for (const port of process.argv.slice(1)) {
        net.createServer((client) => {
          const upstream = net.connect(port, \"host.docker.internal\");
          client.pipe(upstream).pipe(client);
          upstream.on(\"error\", () => client.destroy());
          client.on(\"error\", () => upstream.destroy());
        }).listen(port, \"127.0.0.1\");
      }
    " "$0" "$1" & exec npx playwright test --config playwright.demo.config.ts "${@:2}"' \
    "$web_port" "$api_port" "$@"
else
  PLAYWRIGHT_BASE_URL="$web_url" COSTURA_DEMO_E2E_API="$api_url" \
    pnpm exec playwright test --config playwright.demo.config.ts "$@"
fi
