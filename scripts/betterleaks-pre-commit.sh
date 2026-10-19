#!/usr/bin/env bash
set -euo pipefail

if ! command -v betterleaks >/dev/null 2>&1; then
  echo >&2 "warning: betterleaks is not on PATH, staged files were not scanned; activate mise (mise activate) or run: mise install"
  echo >&2 "CI runs the same scan on every pull request (just quality::secrets)."
  exit 0
fi

betterleaks --no-banner --redact git . --pre-commit --staged
