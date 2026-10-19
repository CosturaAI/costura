#!/usr/bin/env bash
# Write a synthetic production env file for the smoke scripts and print the variables to unset.
# `just` exports the repo-root .env, which overrides --env-file, so callers drop those values.
set -euo pipefail

target="${1:?usage: smoke-env.sh <env-file>}"
key=$(uv run --project apps/api python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode("ascii"))')

cat > "$target" <<EOF
POSTGRES_DB=costura
POSTGRES_USER=costura
POSTGRES_PASSWORD=smoke-password
POSTGRES_APP_USER=costura_app
POSTGRES_APP_PASSWORD=smoke-app-password
COSTURA_SECRET_KEY=$key
COSTURA_OPERATOR_EMAIL=smoke@example.com
COSTURA_OPERATOR_SECRET=smoke-operator-secret-24
COSTURA_SITE_ADDRESS=http://localhost
COSTURA_WEB_ORIGIN=http://127.0.0.1:18080
COSTURA_WEB_PUBLIC_URL=http://127.0.0.1:18080
COSTURA_HTTP_PORT=18080
COSTURA_HTTPS_PORT=18443
COSTURA_VERSION=smoke
EOF

# Names the caller must unset so the synthetic file wins over the exported repo .env.
cat <<'EOF'
POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD POSTGRES_APP_USER POSTGRES_APP_PASSWORD COSTURA_SECRET_KEY COSTURA_OPERATOR_EMAIL COSTURA_OPERATOR_SECRET COSTURA_SITE_ADDRESS COSTURA_WEB_ORIGIN COSTURA_WEB_PUBLIC_URL COSTURA_HTTP_PORT COSTURA_HTTPS_PORT COSTURA_VERSION
EOF
