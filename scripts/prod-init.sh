#!/usr/bin/env bash
# Write a production .env from .env.example with generated secrets, so the first
# `just prod::up` needs only an operator e-mail and, for a public host, its name.
#
#   scripts/prod-init.sh                      # http://localhost trial, prompts for the e-mail
#   scripts/prod-init.sh --email you@example.com --host costura.example.com
#
# Generates COSTURA_SECRET_KEY, POSTGRES_PASSWORD, POSTGRES_APP_PASSWORD and
# COSTURA_OPERATOR_SECRET, and sets the three URL variables consistently. Refuses to
# overwrite an existing .env. Prints the operator secret once; nothing else is printed.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"

email=""
host=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --email) email="${2:-}"; shift 2 ;;
    --host) host="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "error: unknown argument $1" >&2; exit 2 ;;
  esac
done

if [[ -f .env ]]; then
  echo "error: .env already exists; move it away to start over" >&2
  exit 1
fi
if [[ -z "$email" ]]; then
  read -r -p "Operator e-mail (first sign-in): " email
fi
if [[ "$email" != *@*.* ]]; then
  echo "error: the operator e-mail must look like you@example.com" >&2
  exit 1
fi
if [[ -n "$host" && ! "$host" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "error: --host is a bare hostname such as costura.example.com, without a scheme" >&2
  exit 1
fi

python3 - "$email" "$host" <<'PY'
import base64
import secrets
import sys
from pathlib import Path

email, host = sys.argv[1], sys.argv[2]
site = host or "http://localhost"
origin = f"https://{host}" if host else "http://localhost"
operator_secret = secrets.token_urlsafe(32)
values = {
    "COSTURA_ENV": "production",
    "POSTGRES_PASSWORD": secrets.token_hex(16),
    "POSTGRES_APP_PASSWORD": secrets.token_hex(16),
    "COSTURA_SECRET_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    "COSTURA_OPERATOR_EMAIL": email,
    "COSTURA_OPERATOR_SECRET": operator_secret,
    "COSTURA_WEB_ORIGIN": origin,
    "COSTURA_WEB_PUBLIC_URL": origin,
    "COSTURA_SITE_ADDRESS": site,
}
lines = []
seen = set()
for line in Path(".env.example").read_text().splitlines():
    name = line.split("=", 1)[0].lstrip("# ").strip()
    if name in values and "=" in line and name not in seen:
        lines.append(f"{name}={values[name]}")
        seen.add(name)
    else:
        lines.append(line)
for name, value in values.items():
    if name not in seen:
        lines.append(f"{name}={value}")
env = Path(".env")
env.write_text("\n".join(lines) + "\n")
env.chmod(0o600)
print(f"wrote .env for {origin} (mode 600)")
print(f"operator secret for {email}: {operator_secret}")
print("keep a copy of COSTURA_SECRET_KEY outside this host; next: just prod::up")
PY

bash scripts/prod-password.sh
