#!/usr/bin/env bash
# Shared helpers for the production recipes. Destructive recipes ask once, and
# COSTURA_ASSUME_YES=1 answers yes for every one of them.

# Ask before a destructive step. Exits when the answer is not yes.
confirm_or_exit() {
  local prompt="$1"
  if [[ "${COSTURA_ASSUME_YES:-}" == "1" ]]; then
    return 0
  fi
  local answer
  read -r -p "$prompt [y/N] " answer
  [[ "$answer" == "y" || "$answer" == "Y" ]] || exit 1
}
