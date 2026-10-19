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
  command -v "$tool" >/dev/null 2>&1 || note "$tool is not on PATH; run: mise install, then activate mise in your shell (eval \"\$(mise activate zsh)\" or bash)"
done
if command -v node >/dev/null 2>&1; then
  want=$(pinned node)
  have=$(node --version | sed 's/^v//')
  if [[ -n "$want" && "$have" != "$want" ]]; then
    note "node is $have, mise.toml pins $want; activate mise in your shell (eval \"\$(mise activate zsh)\" or bash)"
  fi
fi

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
if docker info >/dev/null 2>&1 && listening 5432; then
  if ! docker compose ps --status running --services 2>/dev/null | grep -qx postgres; then
    note "port 5432 is in use by another PostgreSQL; stop it before just dev"
  fi
fi

if [[ ! -f .env ]]; then
  note "no .env: run just setup"
else
  uv run --project apps/api python - <<'PY' || fail=1
import sys

from cryptography.fernet import Fernet
from costura.config import get_settings

secret = get_settings().costura_secret_key
if secret is None or not secret.get_secret_value().strip():
    print("warning: COSTURA_SECRET_KEY is empty; just dev runs, saving a provider key needs one: just api::secret-generate")
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
