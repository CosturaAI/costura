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
the git hooks. `just doctor` reports a tool that resolves to another version. Then:

```
mise install
just doctor
just setup
just dev
```

`just setup` also installs the pre-commit hooks (`just quality::pre-commit` runs them on
every file). `just dev` migrates the database, seeds the `demo` organization, and starts
the API, the worker, and the web app. Sign in at `http://127.0.0.1:3000/sign-in` with any
e-mail on a local stack.

Fork the repository, branch from `main`, and rebase on `main` before asking for review.
One pull request is one change.

## Checks

```
just check
just coverage-core
just smoke
```

`just check` is actionlint, ruff, `ty`, ESLint, Prettier, TypeScript, the generated OpenAPI
types, and the secret scan. `just coverage-core` starts PostgreSQL and runs `just test` with the coverage floors CI
enforces; `just quality::vulnerabilities` is the CI filesystem scan. `just api::test-unit` runs the fast API layer,
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
templates) runs the quality, secret, title and dependency checks; the test, build, scan and
CodeQL jobs report as skipped (`scripts/ci-changes.sh`).

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
| `just coverage`                                                            | Coverage plus changed-line coverage against `origin/main`                            |
| `just api::openapi`                                                        | Rewrite the OpenAPI snapshot; then `just web::api-types-check`                       |
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

## Decisions

A change that binds the next design states the decision and what it costs in the pull
request description. [docs/architecture/overview.md](docs/architecture/overview.md) draws
the services it touches.
