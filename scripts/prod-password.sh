#!/usr/bin/env bash
# Refuse the example database passwords and characters that break the URL or the shell.
# Checks the schema owner (POSTGRES_PASSWORD) and the runtime role (POSTGRES_APP_USER,
# POSTGRES_APP_PASSWORD). Prints one line and never prints a password.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"

env_file="${COSTURA_ENV_FILE:-.env}"
if [[ ! -f "$env_file" ]]; then
  echo "error: copy .env.example to .env before production commands" >&2
  exit 1
fi
export COSTURA_PASSWORD_ENV_FILE="$env_file"

python3 - <<'PY'
import os
import re
from pathlib import Path

values = {}
for line in Path(os.environ["COSTURA_PASSWORD_ENV_FILE"]).read_text().splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        name, value = line.split("=", 1)
        values.setdefault(name.strip(), value)

unsafe = set(" \t\r\n'\"\\$:@/%?#")


def check(name: str, minimum: int) -> str:
    password = values.get(name, "")
    if not password:
        raise SystemExit(f"error: set {name} in .env")
    if password == "costura":
        raise SystemExit(f"error: {name} is the example value; choose another")
    if any(character in unsafe or ord(character) < 32 for character in password):
        raise SystemExit(
            f"error: {name} contains a character that breaks the database URL; "
            "use letters, digits, and _-."
        )
    if len(password) < minimum:
        raise SystemExit(f"error: {name} must be at least {minimum} characters")
    return password


owner = check("POSTGRES_PASSWORD", 1)
app = check("POSTGRES_APP_PASSWORD", 12)
if app == owner:
    raise SystemExit("error: POSTGRES_APP_PASSWORD must differ from POSTGRES_PASSWORD")
app_user = values.get("POSTGRES_APP_USER", "")
if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
    raise SystemExit("error: POSTGRES_APP_USER must be lowercase letters, digits and _")
if app_user == values.get("POSTGRES_USER", ""):
    raise SystemExit("error: POSTGRES_APP_USER must differ from POSTGRES_USER")
PY
