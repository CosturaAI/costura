#!/usr/bin/env bash
# Check a production host and its .env before `just prod::up`, without printing a secret.
# One line per problem; exits 1 on any error, a warning does not change the exit code.
# COSTURA_COMPOSE and COSTURA_ENV_FILE select another project, as in the prod recipes.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"
compose=${COSTURA_COMPOSE:-docker compose -f docker-compose.prod.yml}
env_file=${COSTURA_ENV_FILE:-.env}
fail=0

note() {
  echo "error: $*"
  fail=1
}

listening() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
  else
    python3 -c 'import socket,sys; s=socket.socket(); s.settimeout(0.5); sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)' "$1"
  fi
}

command -v python3 >/dev/null 2>&1 || note "python3 is not installed; the prod scripts need it"

docker_ok=0
if ! command -v docker >/dev/null 2>&1; then
  note "Docker is not installed"
elif ! docker info >/dev/null 2>&1; then
  note "the Docker daemon is not running"
elif ! docker compose version >/dev/null 2>&1; then
  note "Docker Compose v2 is not installed (docker compose version)"
else
  docker_ok=1
  memory=$(docker info --format '{{.MemTotal}}' 2>/dev/null || echo 0)
  if [[ "$memory" =~ ^[0-9]+$ ]] && ((memory > 0 && memory < 3800000000)); then
    echo "warning: Docker has $((memory / 1000000)) MB of memory; the stack wants at least 4 GB"
  fi
fi

if [[ ! -f "$env_file" ]]; then
  note "$env_file does not exist; write it with just prod::init"
  exit 1
fi

python3 scripts/prod-doctor-env.py "$env_file" || fail=1
bash scripts/prod-password.sh || fail=1

if [[ $docker_ok -eq 1 ]]; then
  if ! problem=$($compose config -q 2>&1); then
    note "docker compose config: $(printf '%s' "$problem" | tail -n 1)"
  fi
  running=$($compose ps --status running --services 2>/dev/null || true)
  if ! grep -qx proxy <<<"$running"; then
    from_env() { sed -n "s/^$1=//p" "$env_file" | tail -n 1; }
    http_port=${COSTURA_HTTP_PORT:-$(from_env COSTURA_HTTP_PORT)}
    https_port=${COSTURA_HTTPS_PORT:-$(from_env COSTURA_HTTPS_PORT)}
    for port in "${http_port:-80}" "${https_port:-443}"; do
      if listening "$port"; then
        note "port $port is already in use; Caddy publishes it"
      fi
    done
  fi
  version=$(sed -n 's/^COSTURA_VERSION=//p' "$env_file" | tail -n 1)
  image="ghcr.io/costuraai/costura-api:${version}"
  if [[ -n "$version" ]] && docker image inspect "$image" >/dev/null 2>&1; then
    docker run --rm --network none --read-only --env-file "$env_file" -e COSTURA_ENV=production \
      "$image" python -c '
import os
import sys
os.environ["DATABASE_URL"] = "postgresql+psycopg://{}:{}@postgres/{}".format(
    os.environ.get("POSTGRES_APP_USER", ""),
    os.environ.get("POSTGRES_APP_PASSWORD", ""),
    os.environ.get("POSTGRES_DB", ""),
)
from costura.config import get_settings, production_startup_errors, production_warnings
try:
    settings = get_settings()
except Exception as exc:
    sys.exit(f"error: {str(exc).splitlines()[0]}")
for line in production_warnings(settings):
    print(f"warning: {line}")
errors = production_startup_errors(settings)
for line in errors:
    print(f"error: {line}")
sys.exit(1 if errors else 0)
' || fail=1
  elif [[ -n "$version" ]]; then
    echo "warning: $image is not pulled yet, so the API settings were not checked; just prod::up pulls it"
  fi
fi

if [[ $fail -ne 0 ]]; then
  exit 1
fi
echo "prod doctor ok"
