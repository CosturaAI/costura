# Contributing

Contributions of code, docs, tests, and bug reports are welcome. Issues labeled
[`good first issue`](https://github.com/CosturaAI/costura/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
and [`help wanted`](https://github.com/CosturaAI/costura/issues?q=is%3Aissue+is%3Aopen+label%3A%22help+wanted%22)
are a place to start. [GOVERNANCE.md](GOVERNANCE.md) describes how someone becomes a
maintainer. Questions about using a deployment go to [SUPPORT.md](SUPPORT.md).

Contributions are licensed under the Apache License, Version 2.0 ([LICENSE](LICENSE)).
There is no CLA and no DCO sign-off. Opening a pull request submits the change under that
license. The project name and mark follow [TRADEMARK.md](TRADEMARK.md).

## Setup

Install [mise](https://mise.jdx.dev/getting-started.html) and Docker Compose v2. mise pins
Python, Node.js, pnpm, uv, just and the lint tools to the versions in `mise.toml`, so every
contributor and CI run the same ones.
Without mise, install those versions by hand; the `just` recipes are the same.
[Activate mise](https://mise.jdx.dev/getting-started.html#activate-mise) in your shell
(`eval "$(mise activate zsh)"`, or `bash`) so those versions are on `PATH`, including for
the git hooks; otherwise run `mise exec -- just dev`. Then:

```
mise install
just dev
```

`just dev` runs `just setup` (`.env` from `.env.example`, a generated `COSTURA_SECRET_KEY`
when empty, the dependencies and the pre-commit hooks; `just quality::pre-commit` runs them on
every file), then `just doctor`, which stops the run on a tool at another version than
`mise.toml`, a stopped Docker daemon, port 8000, 3000 or 5432 in use, or a `next dev` from
this checkout still running. It then migrates the database, seeds the `demo` organization,
starts the API, the worker, and the web app, and prints the addresses once they answer.
Sign in at `http://127.0.0.1:3000/sign-in` with any e-mail on a local stack.
[Troubleshooting](docs/operations/troubleshooting.md#local-development) covers each doctor
message.

`.devcontainer/` is the same setup with nothing installed on the host: VS Code Dev
Containers or GitHub Codespaces build it (Ubuntu 24.04, Docker in Docker, mise), run
`mise install` and `just setup`, and forward ports 3000 and 8000; then run `just dev` in its
terminal.

Fork the repository, branch from `main`, and rebase on `main` before asking for review.
One pull request is one change. Add the main repository as `upstream` so the rebase and the
changed-line coverage compare against it, not against your fork's copy of `main`:

```
git remote add upstream https://github.com/CosturaAI/costura.git
git fetch upstream
git rebase upstream/main
```

## Checks

These are the commands the required CI checks run on a pull request:

```
just check
just docs::check-llms
just coverage upstream/main
```

`just check` is actionlint, ruff, `ty`, ESLint, Prettier, TypeScript, the generated OpenAPI
types, and the secret scan. It needs no Docker and takes about 25 seconds on a laptop.
`just docs::check-llms` fails when a documentation edit left `llms.txt` stale; `just
docs::llms` rewrites it. `just coverage upstream/main` needs Docker for PostgreSQL and takes
about 5 minutes: it runs `just coverage-core` (`just test` with the coverage floors CI
enforces) and then requires 90% coverage of the lines changed since `upstream/main`. `just
smoke` boots the stack and checks it over HTTP, as the "Install smoke" job does.
`just quality::vulnerabilities` is the CI filesystem scan.

One test while iterating:

```
just api::test tests/test_config.py -k secret
just web::test src/lib/format.test.ts
```

`just api::test-unit` runs the fast API layer,
`just api::test-integration` runs tests marked for PostgreSQL/provider integration, and
`just api::test` plus `just web::test` run the complete suites. `just web::test-e2e-docker` runs the
Playwright smoke and visual suites, and `just web::test-e2e-demo-docker` runs the sample
organization against PostgreSQL; both run the browser in the pinned Playwright image, as CI
does, so they match the committed screenshots on any host. `just web::test-e2e` and
`just web::test-e2e-demo` use the host's Chromium and match those screenshots only on Linux.
Update the screenshots with `just web::snapshots`, which runs both suites in Docker, and
commit only reviewed PNGs.
`just coverage-core` also
checks branch coverage and rejects source files missing from the reports. `just fix` applies
the formatters. A pull request also needs the CI checks in `.github/workflows/` to pass. Do not add a secret, a
private URL, or a workflow that calls a private service. A pull request that changes only
documentation (`docs/`, `llms.txt`, Markdown outside `apps/`, the issue and discussion
templates) runs the quality, secret, title and dependency checks; the CI test, build and
scan jobs report as skipped, and the CodeQL jobs pass with their analysis steps skipped
(`scripts/ci-changes.sh`).

Without Docker, the screenshots cannot be regenerated locally. Push the change: a failing
"Playwright browser tests" job uploads the `playwright-traces` artifact with the new
screenshots and their diffs, and a reviewer can run `just web::snapshots` and push the
reviewed PNGs to the branch.

## Issues

Before a bug report, run `just doctor` and test the latest release; a bug fixed on `main`
is closed with a link to the commit. Usage questions go to
[GitHub Discussions](https://github.com/CosturaAI/costura/discussions), not to an issue.
A sync or reconciliation bug needs the output of `just api::tieout-report --org <slug>` (no
amount, key or e-mail in it) and redacted logs: no provider key, session cookie,
`COSTURA_SECRET_KEY` or `.env` content. Every bug needs a reproduction: the exact steps on a
`just dev` stack or on `docker-compose.prod.yml`, with `COSTURA_VERSION`.

Other recipes (`just --list` prints all of them):

| Recipe                                                                     | Does                                                                                 |
| -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| `just coverage [base]`                                                     | Coverage plus changed-line coverage against `base` (default `origin/main`)           |
| `just api::openapi`                                                        | Rewrite the OpenAPI snapshot; then `just web::api-types`                             |
| `just api::revision "message"`                                             | New Alembic revision on the single chain                                             |
| `just api::db-current`, `just api::migration-check`                        | Current revision; one base and one head                                              |
| `just db::up`, `db::down`, `db::logs`, `db::psql`, `db::reset`             | Local PostgreSQL                                                                     |
| `just web::snapshots`                                                      | Regenerate the Playwright screenshots on Linux Chromium in Docker                    |
| `just web::screens`                                                        | Recapture the product screens of `docs/product/screens.md` from a running `just dev` |
| `just web::test-e2e-docker`, `web::test-e2e-demo-docker`                   | Browser suites in the pinned Playwright image, as CI runs them                       |
| `just prod::up`, `prod::down`, `prod::logs`, `prod::ps`                    | Production Compose stack                                                             |
| `just prod::backup`, `prod::restore`, `prod::purge`, `prod::secret-rotate` | Production operations ([docs/operations](docs/operations/install.md))                |

## Pull requests

Use a Conventional Commit title. Squash merge turns that title into the commit on `main`,
and [release-please](docs/release.md) builds the changelog from it.

| Type        | Use when                                  |
| ----------- | ----------------------------------------- |
| `feat:`     | A user-visible capability                 |
| `fix:`      | A bug fix                                 |
| `docs:`     | Documentation only                        |
| `refactor:` | A change with no intended behavior change |
| `perf:`     | A performance improvement                 |
| `test:`     | Tests only                                |
| `build:`    | Packaging, Docker, compose                |
| `ci:`       | Workflows and Actions                     |
| `chore:`    | Maintenance that is none of the above     |
| `revert:`   | A revert of a previous change             |

Examples: `feat: add openrouter credit prices`, `fix: reject empty operator secret`.

On a first pull request to this repository, the workflows wait until a maintainer approves
the run; after the first merged pull request they start on every push. A pull request
merges only when its branch contains the latest `main`, so rebase on `upstream/main` and
push again when the checks report the branch as out of date.

A small bug fix goes straight to a pull request. A change that adds surface (a new
provider, a new route, or a new table) starts with an issue so the scope is agreed before
the code.

A pull request or issue produced with a coding agent carries the `agent-assisted` label, so
reviewers know to read it as such; the author still answers for every line.

Pull request workflows read no secret. If one is ever needed, the step reads it through
the fork-safe form, which yields an empty string on a pull request from a fork:

```
${{ (github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository) && secrets.X || '' }}
```

## Adding a provider

A new connector starts with an issue. Then, in one pull request:

1. `apps/api/costura/providers/<name>/` with its client, normalization, sync and a
   `spec.py` that builds the `ProviderSpec` (`apps/api/costura/providers/spec.py`), plus one
   entry in `PROVIDERS` in `apps/api/costura/providers/registry.py`.
2. The settings an environment key or base URL needs in `apps/api/costura/config.py`, with
   the commented lines in `.env.example` and the rows in
   [docs/operations/configuration.md](docs/operations/configuration.md).
3. A `<name>_client` fixture in `apps/api/tests/conftest.py` and the provider in `FIXTURED`
   (`apps/api/tests/test_provider_contract.py`), which runs the second-sync idempotency
   check; the name in `provider_names()` (`apps/api/tests/test_registry.py`) and in
   `CONNECTORS` (`apps/api/tests/test_architecture.py`).
4. An account for it in the sample organization (`apps/api/costura/demo/`);
   `apps/api/tests/test_demo.py` requires one per provider.
5. A `## <Provider>` section in [docs/security/provider-keys.md](docs/security/provider-keys.md)
   with every request the client sends, and the name in `SECTIONS`
   (`apps/api/tests/test_provider_keys_doc.py`).
6. The web tables `PROVIDER_LABELS` (`apps/web/src/lib/providers.ts`) and `KEY_HINTS` and
   `KEY_ACCESS` (`apps/web/src/lib/setup.ts`); `apps/api/tests/test_provider_checklist.py`
   fails until each one names the provider.
7. The connector list in [README.md](README.md) and [apps/api/README.md](apps/api/README.md),
   and `just api::openapi` plus `just web::api-types` when a response shape changed.

## Decisions

A change that binds the next design states the decision and what it costs in the pull
request description. [docs/architecture/overview.md](docs/architecture/overview.md) draws
the services it touches.
