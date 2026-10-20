#!/usr/bin/env bash
# Package what a Docker-only install needs: scripts/release-bundle.sh <version> <out-dir>
#
# Writes <out-dir>/costura-<version>.tar.gz (one costura-<version>/ directory with the
# production compose file, .env.example, LICENSE and the prod init, doctor and password
# scripts) and its .sha256. The images come from the registry, so no source is included.
set -euo pipefail

version=${1:?usage: release-bundle.sh <version> <out-dir>}
out=${2:?usage: release-bundle.sh <version> <out-dir>}
root=$(cd "$(dirname "$0")/.." && pwd)
name="costura-$version"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/$name/scripts" "$out"
cp "$root/docker-compose.prod.yml" "$root/.env.example" "$root/LICENSE" "$work/$name/"
for script in prod-init.sh prod-password.sh prod-doctor.sh prod-doctor-env.py; do
  cp "$root/scripts/$script" "$work/$name/scripts/"
done
grep -q "^COSTURA_VERSION=$version\$" "$work/$name/.env.example" \
  || { echo "error: .env.example does not name COSTURA_VERSION=$version" >&2; exit 1; }

tar -C "$work" -czf "$out/$name.tar.gz" "$name"
(cd "$out" && sha256sum "$name.tar.gz" > "$name.tar.gz.sha256" 2>/dev/null \
  || shasum -a 256 "$name.tar.gz" > "$name.tar.gz.sha256")
echo "$out/$name.tar.gz"
