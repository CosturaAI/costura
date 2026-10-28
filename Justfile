set dotenv-load := true
set shell := ["bash", "-euo", "pipefail", "-c"]

mod api ".just/api.just"
mod web ".just/web.just"
mod db ".just/db.just"
mod quality ".just/quality.just"
mod prod ".just/prod.just"
mod docs ".just/docs.just"

_root := justfile_directory()

# List recipes, including modules.
default:
    @just --list --list-submodules

# Check required tools, create .env with a COSTURA_SECRET_KEY, install dependencies and pre-commit.
setup:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{_root}}"
    just _require-tools
    if [[ ! -f .env ]]; then
      cp .env.example .env
      echo "created .env from .env.example"
    fi
    just api::setup
    just web::setup
    if grep -qx 'COSTURA_SECRET_KEY=' .env; then
      key=$(uv run --project apps/api python -m costura.ops.secret generate)
      sed -i.bak "s|^COSTURA_SECRET_KEY=\$|COSTURA_SECRET_KEY=${key}|" .env
      rm -f .env.bak
      echo "generated COSTURA_SECRET_KEY in .env"
    fi
    uv run --project apps/api pre-commit install
    echo "setup complete"

# COSTURA_DEV_SCHEDULER=1 also starts the scheduler.
# Run setup and doctor, then PostgreSQL, migrations, the demo seed, the API (:8000), worker, and web app (:3000).
dev:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{_root}}"
    if [[ ! -f .env ]]; then
      just setup
      COSTURA_DEV_SET_UP=1 exec just dev
    fi
    [[ -n "${COSTURA_DEV_SET_UP:-}" ]] || just setup
    [[ -n "${COSTURA_SECRET_KEY:-}" ]] || unset COSTURA_SECRET_KEY
    bash scripts/doctor.sh
    just db::up
    just api::migrate
    just api::demo-seed || echo "warning: demo seed failed; the sample organization is unavailable"
    api_pid=""
    web_pid=""
    worker_pid=""
    sched_pid=""
    ready_pid=""
    stop() {
      trap - EXIT INT TERM
      kill -TERM $api_pid $web_pid $worker_pid $sched_pid $ready_pid 2>/dev/null || true
      sleep 1
      # Ports were free at start, so anything still listening belongs to this run.
      for port in 8000 3000; do
        lsof -t -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | xargs kill -TERM 2>/dev/null || true
      done
      wait 2>/dev/null || true
    }
    trap stop EXIT
    trap 'stop; exit 0' INT TERM
    (cd apps/api && exec uv run uvicorn costura.main:app --reload --host 127.0.0.1 --port 8000) &
    api_pid=$!
    (cd apps/web && exec pnpm exec next dev --hostname 127.0.0.1 --port 3000) &
    web_pid=$!
    (cd apps/api && exec uv run python -m costura.ops.worker) &
    worker_pid=$!
    if [ "${COSTURA_DEV_SCHEDULER:-0}" = "1" ]; then
      (cd apps/api && exec uv run python -m costura.ops.scheduler) &
      sched_pid=$!
    fi
    if command -v curl >/dev/null 2>&1; then
      (
        for _ in $(seq 1 180); do
          if curl -fsS -o /dev/null http://127.0.0.1:8000/live 2>/dev/null &&
            curl -fsS -o /dev/null http://127.0.0.1:3000/sign-in 2>/dev/null; then
            printf '\nCostura is running\n'
            printf '  web   http://127.0.0.1:3000 (sign in with any e-mail, or open the sample organization)\n'
            printf '  api   http://127.0.0.1:8000/docs\n'
            printf '  stop  Ctrl-C\n\n'
            exit 0
          fi
          sleep 1
        done
      ) &
      ready_pid=$!
    fi
    # Stop the stack when the API, web app, or worker exits (bash 3.2 has no wait -n).
    while kill -0 "$api_pid" 2>/dev/null && kill -0 "$web_pid" 2>/dev/null && kill -0 "$worker_pid" 2>/dev/null; do
      sleep 1
    done
    dead=""
    kill -0 "$api_pid" 2>/dev/null || dead="api"
    kill -0 "$web_pid" 2>/dev/null || dead="${dead:+$dead, }web"
    kill -0 "$worker_pid" 2>/dev/null || dead="${dead:+$dead, }worker"
    echo "error: the $dead process exited; its output is above. Stopping the stack." >&2
    exit 1

# Check that the required tools are installed, the ports are free, and the local .env is usable, without printing secrets.
doctor:
    bash "{{_root}}/scripts/doctor.sh"

# Fail early when docker, uv or pnpm is missing.
_require-tools:
    #!/usr/bin/env bash
    set -euo pipefail
    missing=0
    for tool in docker uv pnpm; do
      command -v "$tool" >/dev/null || { echo "error: $tool is not installed"; missing=1; }
    done
    if [[ $missing -ne 0 ]]; then
      echo "  install the pinned toolchain with: mise install"
      echo "  install mise from https://mise.jdx.dev/getting-started.html"
    fi
    exit $missing

# Run all tests: API (starts PostgreSQL first), then web.
test:
    just db::up
    just api::test
    just web::test

# Postgres, migrations, demo seed, API and Next, then HTTP checks.
smoke:
    bash "{{_root}}/scripts/smoke-install.sh"

# Run the API and web suites with their coverage floors.
coverage-core:
    just db::up
    just api::coverage
    just web::coverage
    uv run --project "{{_root}}/apps/api" python "{{_root}}/scripts/check-coverage.py"

# Run all tests with coverage floors, then the 90% gate on lines changed since `base`.
coverage base="origin/main":
    just db::up
    just coverage-core
    just api::diff-coverage {{base}}
    just web::diff-coverage {{base}}

# Run every lint, format and type check.
check: (quality::check)

# Fix lint and formatting issues in API and web code.
fix:
    just api::fix
    just web::fix
