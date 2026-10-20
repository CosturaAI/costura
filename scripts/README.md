# scripts

Operational scripts that span the API and the web app.

- `smoke-install.sh` (`just smoke`) starts a disposable PostgreSQL (Compose project
  `costura-smoke` on `127.0.0.1:5433`), applies migrations, seeds the `demo`
  organization, starts the API and the web app on ports 18000 and 13000, and checks
  `/live`, `/ready`, the current month's demo summary (`GET .../months/{month}/summary`,
  non-zero `total`), and the sign-in page that loads that organization through Next.js. `COSTURA_SMOKE_DB_PORT`, `COSTURA_SMOKE_API_PORT` and
  `COSTURA_SMOKE_WEB_PORT` change the ports. The smoke database is removed on exit
  and is not the database from `just db::up`.
- `demo-e2e.sh` (`just web::test-e2e-demo`) starts a disposable PostgreSQL (Compose project
  `costura-demo-e2e` on `127.0.0.1:5434`), applies migrations, seeds the sample as of
  `2026-09-15` (`COSTURA_DEMO_E2E_TODAY` changes the day), and runs the Playwright suite in
  `apps/web/e2e-demo` against the API on port 18100 and the production web build on port 13100.
  `COSTURA_DEMO_E2E_DB_PORT`, `COSTURA_DEMO_E2E_API_PORT` and `COSTURA_DEMO_E2E_WEB_PORT` change
  the ports. The database is removed on exit. The web app must already be built; the Just
  recipe builds it first. When `COSTURA_PLAYWRIGHT_DOCKER_IMAGE` is set (`just web::snapshots`),
  the Playwright step runs inside that image against the host-run API and web servers instead
  of `pnpm exec playwright` directly, so the screenshots are the same Linux Chromium pixels on
  every host. CI sets it through `just web::test-e2e-demo-docker`. On Linux the container
  shares the host network. Elsewhere a small Node forwarder inside the container serves the
  host's ports on `127.0.0.1`. Either way the browser keeps the localhost cookie names
  (`__Host-` cookies need HTTPS).
- `smoke-prod.sh` (`just prod::smoke`) builds `docker-compose.prod.yml` from the synthetic
  env `smoke-env.sh` writes (`COSTURA_VERSION=smoke`), instead of pulling the published
  GHCR tags. It waits until migrate, API, worker, scheduler, web and proxy are up, checks
  `/live` through the proxy (with `Host: localhost`), that the proxy answers 404 on `/ready`,
  `/health` and `/metrics`, that `/sign-in` sends a nonce-based CSP, `/ready` inside the API
  container, that
  the API connects as the restricted `costura_app` role without `CREATE` on the schema, the
  worker and scheduler heartbeats, a `worker --once` pass and the sample publication as that
  role, and a `just prod::backup` then `just prod::restore` round trip against the smoke
  project, then removes the stack. It points the production recipes at its own project with
  `COSTURA_COMPOSE` and `COSTURA_ENV_FILE` (also read by `prod-password.sh`) and
  `just --dotenv-path`. `COSTURA_SUBNET` moves the network when `172.28.0.0/24` is taken. `smoke-env.sh` also prints the
  variable names the caller unsets so the repo-root `.env` does not override that file.
- `prod-password.sh` runs before the production recipes. It refuses the example database
  passwords, a runtime role password shorter than 12 characters or equal to the owner's,
  and characters that break the database URL.
- `prod-init.sh` (`just prod::init [--email you@example.com] [--host costura.example.com]
  [--google-client-id <id>]`) writes a production `.env` from `.env.example` with mode 600:
  generated `COSTURA_SECRET_KEY`, database passwords and operator secret, the operator
  e-mail, one consistent origin for `COSTURA_SITE_ADDRESS`, `COSTURA_WEB_ORIGIN` and
  `COSTURA_WEB_PUBLIC_URL`, and the Google client when asked (the secret from
  `GOOGLE_CLIENT_SECRET` or a hidden prompt). The variables the compose file sets
  (`COSTURA_ENV`, `DATABASE_URL`, `TEST_DATABASE_URL`, `COSTURA_API_URL`) stay commented out.
  It refuses to overwrite `.env`, prints the operator secret once, then runs
  `prod-password.sh`.
- `smoke-external-db.sh` (`just prod::smoke-external-db`) builds the production stack against
  a second PostgreSQL with a one-day generated CA: migrate, API, worker and scheduler connect
  over verified TLS as the restricted role, the bundled database stays empty, the worker runs
  once, the secret check passes, then the project and its volumes are deleted.
- `prod.sh` holds `confirm_or_exit` for the destructive production recipes;
  `COSTURA_ASSUME_YES=1` answers yes for scripts.
- `betterleaks-pre-commit.sh` is the pre-commit hook that scans staged files with betterleaks.
  Without betterleaks on `PATH` it warns and lets the commit through; `just check` runs the
  same scan in CI.
- `doctor.sh` (`just doctor`, and the first step of `just dev`) checks that `just`, `uv`,
  `pnpm` and Node.js are on `PATH` at the `mise.toml` versions (a different `just` is a
  warning), the Docker daemon answers, ports 8000 and 3000 are free, port 5432 is free or
  held by this checkout's PostgreSQL, no `next dev` from this checkout holds
  `apps/web/.next/dev/lock`, and the `.env` key is a Fernet key when set, without printing a
  secret. A missing `.env` or an empty key is a warning.
- `check-coverage.py` (`just coverage-core`) enforces the branch-coverage floors and fails on
  source files missing from the coverage reports.
- `check-api-package.py` (`just api::package-check`) installs the built wheel in a clean
  environment and imports it outside the source tree.
- `update-migration-inventory.py` (`just api::revision`) rewrites the Alembic revision lists
  in the READMEs between their marker comments.
- `build-llms-txt.py` (`just docs::llms`) writes `llms.txt` at the repository root from the
  first heading and first paragraph of every `docs/**/*.md` page plus `README.md`,
  `CONTRIBUTING.md`, `SECURITY.md` and `SUPPORT.md`, grouped by directory, in the
  [llms.txt](https://llmstxt.org) format. `--check` exits 1 when the committed file differs
  (`just docs::check-llms`; CI runs it in the "Application quality" job). Standard library
  only.
- `ci-changes.sh` runs in the "Changed files" job of `ci.yml` and `codeql.yml`. It writes
  `code=false` to `$GITHUB_OUTPUT` when every file a pull request or push changes is
  documentation (`docs/**`, `llms.txt`, the `.github` issue and discussion templates, and
  Markdown outside `apps/`), and `code=true` otherwise, on any other event, or when the
  changed files cannot be listed. The test, build and scan jobs, and the CodeQL steps, run
  only when it is `true`; a skipped job satisfies a required check.
