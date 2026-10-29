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
| `just api::capture-fixtures <provider> <out_dir>` | Write the stored provider pages of the newest run per endpoint as redacted fixtures; no provider call ([tests/fixtures/README.md](tests/fixtures/README.md)) |

Tests may be marked `unit` or `integration`. A test that requests the database
(`db_session`, `client`, or any fixture built on `migrated_database`) is marked `integration`
at collection, so the unit recipe never needs PostgreSQL. `just api::coverage` enforces line and branch
measurement, while root `just coverage-core` also rejects missing or stale report entries.

One file or one test: `just api::test tests/test_config.py -k secret`.

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
Anonymous reads of the sample are served from memory per dataset, members and UTC day
(`costura/api/demo_cache.py`, `COSTURA_DEMO_CACHE_MB`); with `COSTURA_DEMO_WARM_URL` the API
renders the sample's pages through the web app to fill that cache before the first visitor.

## Boundaries

| Package | |
| --- | --- |
| `costura/api/routers/` | One `APIRouter` per slice of `/api/v1`; `costura/api/routes.py` composes them |
| `costura/api/deps.py`, `guard.py` | The request session, the signed-in user and the organization dependencies; the write guard |
| `costura/api/presenters/` | Turn rows and `costura.spend` results into response objects; the webhook delivery reuses them |
| `costura/api/schemas/` | Pydantic response shapes, the source of `tests/snapshots/openapi.json` |
| `costura/api/access.py`, `ratelimit.py`, `demo_cache.py` | Request id and access log, per-client limits, the sample organization's read cache |
| `costura/providers/` | One read-only connector per provider, registered in `registry.py`; shared paging, upsert and run records |
| `costura/spend/` | Provider-independent rules: ledger, allocation, anomalies, budgets, projections, queries |
| `costura/models/` | Tables; importing the package registers each one on `Base.metadata` |
| `costura/ops/` | Processes `just` starts outside a signed-in session (`python -m costura.ops.<name>`) |
| `costura/demo/` | The synthetic sample organization and the fake provider clients that build it |
| `costura/legal/` | License texts shipped inside the wheel |

The modules directly under `costura/` are the services between the routers and the rules:

| Module | |
| --- | --- |
| `config`, `db`, `errors`, `secrets`, `telemetry` | Settings, the engine and session, the `DomainError` base, credential encryption, logging; every layer imports them |
| `main` | `create_app()`: mounts `/api/v1`, the technical routes and the one `DomainError` handler |
| `orgs`, `members`, `auth`, `google_oidc`, `identity_policy` | Organizations, membership and invitations, users and sessions, Google sign-in, who may sign up |
| `accounts`, `credentials`, `connections`, `account_settings`, `credit_prices`, `entities` | Provider accounts, their stored keys, connecting and queueing a sync, per-account settings, Codex credit prices, which account an id belongs to |
| `setup_state`, `run_state`, `signal_history`, `audit` | The getting-started card, the latest runs per provider, signal open and close history, security events |
| `scheduler`, `scheduler_queue`, `scheduler_lock`, `sync_cycle` | The worker side: the daily enqueue, the queue, per-organization locks, one sync cycle step by step |
| `delivery`, `digest`, `metrics` | Webhook delivery, the scheduled summary, the `/metrics` text |

A request travels `costura.main` -> `costura/api/routes.py` -> a router in
`costura/api/routers/` -> its dependencies (`SessionDep`, `OrgDep` or a stricter organization
dependency, and `VerifiedWriteDep` on a write) -> a service module or `costura.spend` -> a
presenter that builds a `costura/api/schemas` object. `get_session` commits once when the
route returns, and a `DomainError` raised anywhere below becomes the HTTP error in
`costura.main`. A sync never runs in a request: the route inserts a `queued`
`scheduler_runs` row, and `costura.ops.worker` runs `costura.sync_cycle` on it.

`tests/test_architecture.py` enforces the direction of those arrows:

- `costura/models` imports only models; `costura/spend` and `costura/providers` import each
  other and models. None of the three imports a service module, a presenter or a router.
  The foundation modules are open to every layer.
- A presenter or schema never imports a router, `deps`, `guard`, `ratelimit` or `access`.
- A router neither catches `ValueError` nor commits; a domain refusal is a `DomainError`
  subclass.
- A module a route imports does not commit, except the functions listed in
  `REQUEST_PATH_COMMITS`; a route never calls a function in `WORKER_STEPS`.
- Outside `costura/providers` and `costura/demo`, code never compares a connector name; it
  reads a `ProviderSpec` flag (`costura/providers/spec.py`).

Connectors: `anthropic`, `claude_ai`, `codex`, `cursor`, `openai`, `openrouter`, and
`copilot` (experimental).
There is no command-line client; `tieout-report` and `demo-status` take `--json` so a
script or an agent parses their output. The architecture is one diagram:
[docs/architecture/overview.md](../../docs/architecture/overview.md).

## Migrations

Checked migration inventory, 2 revisions in base-to-head order.

<!-- migration-inventory:start -->

- `7ed3e699f8bc_baseline`
- `1e0cf1dde539_index_sync_run_references_for_retention`

<!-- migration-inventory:end -->
