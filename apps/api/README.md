# Costura API

FastAPI service that imports AI provider spend, stores it per organization, and serves
`/api/v1`. Run it from the [repository README](../../README.md). With the API up,
`GET /docs` is the route reference.

## Commands

From the repository root:

| Command | |
| --- | --- |
| `just api::dev` | Reload on `http://127.0.0.1:8000` |
| `just api::test` | pytest. Start PostgreSQL with `just db::up` first |
| `just api::test-unit` | Tests that need no PostgreSQL (about 370, under three seconds) |
| `just api::test-integration` | PostgreSQL, provider sync, scheduler, and multi-component tests |
| `just api::migrate` | Apply Alembic migrations |
| `just api::worker` | Run queued syncs (long-running; also purges about once an hour) |
| `just api::worker --once` | Drain what is claimable now; does not purge |
| `just api::scheduler` | Enqueue the daily cycle. It does not run the syncs |
| `just api::purge` | One retention pass |
| `just api::demo-seed` | Publish the synthetic read-only `demo` organization when it is missing or from another dataset version |
| `just api::demo-refresh` | Rebuild it through today and swap it in; a failed build leaves the published sample |
| `just api::demo-status` | Print the dataset version and freshness; exits 1 when a refresh would change it. `--json` prints one JSON object with the same fields and exit code |
| `just api::tieout-report --org <slug>` | Pass or fail and percent deltas per provider and month, no amounts. `--json` prints the same rows as one JSON object |

Tests may be marked `unit`, `integration`, or `contract`. A test that requests the database
(`db_session`, `client`, or any fixture built on `migrated_database`) is marked `integration`
at collection, so the unit recipe never needs PostgreSQL. `just api::coverage` enforces line and branch
measurement, while root `just coverage-core` also rejects missing or stale report entries.

`just --list` shows the rest (lint, typecheck, coverage, secrets). `just prod::up` is the
single-node install (Postgres, migration, API, worker, scheduler, web, Caddy). Install,
upgrade, and backup steps are in [docs/operations](../../docs/operations/install.md).
Do not run more than one replica of any unit.

`just dev` starts the worker. `COSTURA_DEV_SCHEDULER=1` also starts the scheduler.

The sample organization is generated, not imported from a provider. It stores no key.
`COSTURA_DEMO_REFRESH=true` makes the long-running scheduler rebuild it when it is missing,
built from another version, or not generated through yesterday. `python -m costura.ops.demo_seed`
accepts `--today YYYY-MM-DD` to build or check it as of another day. An organization already
named `demo` that is not the sample is left alone.

## Boundaries

| Package | |
| --- | --- |
| `costura/api/` | Routers, schemas, and access checks |
| `costura/providers/` | One read-only connector per provider, registered in one place |
| `costura/spend/` | Ledger, allocation, anomalies, and queries |
| `costura/ops/` | Processes `just` starts outside a signed-in session |
| `costura/models/` | Tables |

Connectors: `anthropic`, `claude_ai`, `codex`, `cursor`, `openai`, `openrouter`, and
`copilot` (experimental).
There is no command-line client; `tieout-report` and `demo-status` take `--json` so a
script or an agent parses their output. The architecture is one diagram:
[docs/architecture/overview.md](../../docs/architecture/overview.md).

## Migrations

Checked migration inventory, 1 revision in base-to-head order.

<!-- migration-inventory:start -->

- `7ed3e699f8bc_baseline`

<!-- migration-inventory:end -->
