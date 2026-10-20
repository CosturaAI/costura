#!/usr/bin/env bash
# One short line per problem. Does not print secret values.
# Exits 1 on any error; a warning does not change the exit code.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"
fail=0

note() {
  echo "error: $*"
  fail=1
}

warn() {
  echo "warning: $*"
}

activate_hint='activate mise in your shell (eval "$(mise activate zsh)" or bash), or run: mise exec -- just dev'

listening() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
  else
    python3 -c 'import socket,sys; s=socket.socket(); s.settimeout(0.5); sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)' "$1"
  fi
}

pinned() {
  sed -n "s/^$1 = \"\\(.*\\)\"$/\\1/p" mise.toml
}

if ! command -v mise >/dev/null 2>&1; then
  note "mise is not installed: https://mise.jdx.dev/getting-started.html"
fi
for tool in just uv pnpm node; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    note "$tool is not on PATH; run: mise install, then $activate_hint"
    continue
  fi
  want=$(pinned "$tool")
  have=$("$tool" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1 || true)
  if [[ -n "$want" && "$have" != "$want" ]]; then
    if [[ "$tool" == just ]]; then
      warn "just is $have, mise.toml pins $want; $activate_hint"
    else
      note "$tool is $have, mise.toml pins $want; $activate_hint"
    fi
  fi
done

if ! command -v docker >/dev/null 2>&1; then
  note "Docker is not installed"
elif ! docker info >/dev/null 2>&1; then
  note "the Docker daemon is not running"
elif ! docker compose version >/dev/null 2>&1; then
  note "Docker Compose v2 is not installed (docker compose version)"
fi

for port in 8000 3000; do
  if listening "$port"; then
    note "port $port is already in use"
  fi
done
lock=apps/web/.next/dev/lock
if [[ -s "$lock" ]] && command -v node >/dev/null 2>&1; then
  read -r pid url < <(node -e 'try { const i = JSON.parse(require("fs").readFileSync(process.argv[1], "utf8")); console.log(`${i.pid ?? ""} ${i.appUrl ?? ""}`); } catch { console.log(""); }' "$lock") || true
  if [[ -n "${pid:-}" ]] && ps -p "$pid" -o command= 2>/dev/null | grep -q next; then
    note "a next dev server from this checkout is running at ${url:-an unknown URL} (pid $pid); stop it with: kill $pid"
  fi
fi
db_port=${COSTURA_DEV_DB_PORT:-5432}
for name in DATABASE_URL TEST_DATABASE_URL; do
  url=${!name:-}
  if [[ "$url" =~ @(localhost|127\.0\.0\.1):([0-9]+)/ && "${BASH_REMATCH[2]}" != "$db_port" ]]; then
    note "$name uses port ${BASH_REMATCH[2]}, the development PostgreSQL listens on $db_port (COSTURA_DEV_DB_PORT)"
  fi
done
if docker info >/dev/null 2>&1 && listening "$db_port"; then
  if ! docker compose ps --status running --services 2>/dev/null | grep -qx postgres; then
    holder=$(docker ps --filter publish="$db_port" --format '{{.Names}} {{.Label "com.docker.compose.project.working_dir"}}' 2>/dev/null | head -n 1)
    if [[ -n "$holder" ]]; then
      name=${holder%% *}
      note "port $db_port is held by the container $name (started from ${holder#* }); stop it with: docker stop $name, or set COSTURA_DEV_DB_PORT (.env.example)"
    else
      note "port $db_port is in use by another PostgreSQL; stop it, or set COSTURA_DEV_DB_PORT (.env.example)"
    fi
  fi
fi

if [[ ! -f .env ]]; then
  warn "no .env yet; just dev or just setup creates it"
elif command -v uv >/dev/null 2>&1; then
  uv run --project apps/api python - <<'PY' || fail=1
import sys

from cryptography.fernet import Fernet
from costura.config import get_settings

secret = get_settings().costura_secret_key
if secret is None or not secret.get_secret_value().strip():
    print("warning: COSTURA_SECRET_KEY is empty; just setup generates one")
    sys.exit(0)
try:
    Fernet(secret.get_secret_value().encode("ascii"))
except (ValueError, TypeError):
    sys.exit("error: COSTURA_SECRET_KEY is not a valid Fernet key; run `just api::secret-generate`")
PY
fi

if [[ $fail -ne 0 ]]; then
  exit 1
fi
echo "doctor ok"
