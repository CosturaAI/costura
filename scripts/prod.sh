#!/usr/bin/env bash
# Shared helpers for the production recipes. Destructive recipes ask once, and
# COSTURA_ASSUME_YES=1 answers yes for every one of them. Without a terminal and without
# that variable, confirm_or_exit prints why and exits 1.
# env_value NAME prints NAME from the environment, else its last line in COSTURA_ENV_FILE
# (default .env). external_database succeeds when COSTURA_DATABASE_HOST names a server other
# than the bundled postgres service.

# Ask before a destructive step. Exits when the answer is not yes.
confirm_or_exit() {
  local prompt="$1"
  if [[ "${COSTURA_ASSUME_YES:-}" == "1" ]]; then
    return 0
  fi
  if [[ ! -t 0 ]]; then
    echo "error: $prompt needs a terminal; set COSTURA_ASSUME_YES=1 to answer yes" >&2
    exit 1
  fi
  local answer=""
  read -r -p "$prompt [y/N] " answer || true
  [[ "$answer" == "y" || "$answer" == "Y" ]] || exit 1
}

env_value() {
  local name="$1"
  local file="${COSTURA_ENV_FILE:-.env}"
  if [[ -n "${!name:-}" ]]; then
    printf '%s\n' "${!name}"
  elif [[ -f "$file" ]]; then
    sed -n "s/^$name=//p" "$file" | tail -n 1
  fi
}

external_database() {
  local host
  host=$(env_value COSTURA_DATABASE_HOST)
  [[ -n "$host" && "$host" != "postgres" ]]
}
