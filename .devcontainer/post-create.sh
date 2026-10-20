#!/usr/bin/env bash
# Install the mise.toml toolchain and run just setup once, when the container is created.
set -euo pipefail
cd "$(dirname "$0")/.."
mise trust --yes
mise install
mise exec -- just setup
echo "ready: run just dev"
