---
name: costura
description: Use when installing, running, operating or querying Costura, the self-hosted AI spend attribution service (Anthropic, Claude.ai, OpenAI, Codex, OpenRouter, Cursor, GitHub Copilot). Covers the just recipes, the production Compose stack, the /api/v1 spend query model with f= filter clauses, the tie-out report and where the documentation lives.
license: Apache-2.0
metadata:
  author: Caue Braz
  version: "0.2.1" # x-release-please-version
  source: https://github.com/CosturaAI/costura
---

# Costura

Self-hosted AI spend attribution. Costura imports read-only billing data from AI providers,
normalizes it into a daily ledger, attributes each dollar to a key, workspace or person, and
checks the totals against each provider's own report. One person is one e-mail across
providers. Costura alerts on budgets and never blocks spend. There is no hosted service and
no telemetry; the only outbound calls are the provider reads, optional Google sign-in and
an optional signal webhook.

Repository: https://github.com/CosturaAI/costura. Interfaces can change before 1.0.

## Install and run

Development stack (needs [mise](https://mise.jdx.dev), activated in the shell, and Docker
Compose v2):

```
mise install
just dev
```

`just dev` runs `just setup` (copies `.env.example` to `.env` when missing, generates
`COSTURA_SECRET_KEY` when empty, installs dependencies), then `just doctor`, which stops on a
tool at another version than `mise.toml`, Docker down, port 8000, 3000 or 5432 taken, or a
running `next dev` from the same checkout. It then starts PostgreSQL, migrates, seeds the
read-only `demo` organization and serves the API at `http://127.0.0.1:8000` and the web app at
`http://127.0.0.1:3000`. On a local stack `/sign-in` accepts any e-mail. Without mise
activated in the shell, run `mise exec -- just dev`.

Production is `docker-compose.prod.yml`: Postgres, a one-shot migration, API, worker,
scheduler, web and Caddy, one replica each. `COSTURA_VERSION` in `.env` names the release.

```
just prod::init --email you@example.com --host costura.example.com
just prod::doctor
just prod::up
```

`just prod::doctor` prints one line per host or `.env` problem (Docker, ports 80 and 443,
DNS, release, URLs, sign-in, passwords, API settings) and changes nothing.

Without `just`: `docker compose -f docker-compose.prod.yml pull`, then
`up -d --wait postgres`, `run --rm migrate`, `up -d --wait`. The web app refuses to create
the `COSTURA_ORG` organization; the operator does it with
`just prod::claim-owner <slug> <email> --create`. Install, configuration, upgrade, backup,
monitoring and troubleshooting are in `docs/operations/`.

## Recipes an agent uses

`just --list --list-submodules` prints every recipe. These are the ones that matter when
operating or changing Costura:

| Recipe | Does |
| --- | --- |
| `just check` | Workflow lint, ruff, ty, ESLint, Prettier, TypeScript, generated API types, secret scan |
| `just test`, `just coverage-core` | Every suite; the suites with the coverage floors CI enforces |
| `just smoke` | Disposable PostgreSQL, migrations, demo seed, API and Next, HTTP checks |
| `just fix` | Apply the formatters |
| `just api::test-unit`, `just api::test-integration` | Fast API tests; PostgreSQL and provider tests |
| `just api::lint`, `just api::typecheck`, `just api::format-check` | Ruff, ty, Ruff format |
| `just api::openapi` | Rewrite the OpenAPI snapshot; then `just web::api-types` |
| `just api::revision "message"`, `just api::migration-check` | New Alembic revision; one base and one head |
| `just api::migrate`, `just api::db-current` | Apply migrations; print the current revision |
| `just api::worker --once`, `just api::scheduler --once` | Drain queued syncs; enqueue the daily cycle and drain |
| `just api::purge` | One retention pass over raw pages and finished runs |
| `just api::demo-seed`, `just api::demo-status`, `just api::demo-refresh` | Publish, check or rebuild the sample organization |
| `just api::tieout-report --org <slug> --months 3` | Reconciliation verdicts as percentages, no amounts |
| `just api::secret-generate`, `just api::operator-secret`, `just api::secret-rotate` | Keys for `.env`; re-encrypt stored secrets |
| `just api::claim-owner <slug> <email>` | First owner of an organization with no members |
| `just db::up`, `just db::down`, `just db::psql`, `just db::reset` | Local PostgreSQL |
| `just web::lint`, `just web::typecheck`, `just web::test` | ESLint and palette check; tsc; Vitest |
| `just web::test-e2e-docker`, `just web::test-e2e-demo-docker` | Playwright suites in the pinned image, as CI runs them |
| `just web::screens` | Recapture the product screens of `docs/product/screens.md` from a running `just dev` |
| `just prod::up`, `just prod::down`, `just prod::logs`, `just prod::ps` | The production stack |
| `just prod::doctor`, `just prod::upgrade` | Check the host and `.env` without changes; back up and move to the checked-out release |
| `just prod::backup <dest>`, `just prod::restore <dump>` | Dump with a `.version` file; replace the database in one transaction |
| `just prod::purge`, `just prod::secret-rotate`, `just prod::secret-check` | Retention pass; key rotation; decrypt count |
| `just prod::tieout-report --org <slug>` | The tie-out report against the production database |
| `just prod::smoke` | Build the production stack with synthetic credentials, check it, delete it |
| `just docs::llms`, `just docs::check-llms` | Rewrite `llms.txt`; fail when it is stale |
| `just quality::workflows`, `just quality::secrets`, `just quality::vulnerabilities` | actionlint; betterleaks; Trivy |

Never run more than one replica of the API, the worker or the scheduler.

## API query model

Every route is under `/api/v1`. The OpenAPI document is `GET /openapi.json` and the
reference is `GET /docs`. Authentication is a session bearer from `POST /auth/dev-sign-in`
(development) or `POST /auth/google/callback`; the web app stores it in an `HttpOnly`
cookie. Reads need membership in the organization; writes need `owner` or `member`.
The sample organization `demo` is readable without a session and refuses every write.

The spend query is `GET /orgs/{org}/query`:

- `start` and `end` (inclusive dates, at most 3660 days), `measure` (default `billed_usd`;
  also `byok_usd`, `tokens_total`, `tokens_input`, `tokens_output`, `tokens_cache_read`,
  `tokens_cache_write`, `requests_web_search`, `requests`), `format=json|csv`.
- `dimensions`: up to 3 of `api_key`, `account`, `creator`, `workspace`, `model`,
  `provider`, `origin`, `provider_account`, `person`, `team`, `model_brand`,
  `model_family`, `model_name`, `model_channel`, `model_lifecycle`, `token_type`,
  `cost_type`; `interval=day|week|month`; `top` (at most 200);
  `compare=none|previous_period|previous_year`; `projection=none|linear` with `lookback`
  and `horizon`.
- Filters: plain parameters `api_key`, `account`, `workspace`, `model`, `provider`,
  `person`, `provider_account` mean `is`. Repeatable `f=dimension:op:value[,value]`
  clauses add any of `is`, `is_not`, `one_of`, `not_one_of`, `contains`, `not_contains`,
  `exists`, `not_exists` (the last two take no value). At most 20 filters, 20 values per
  clause, 200 characters per value, one clause per dimension.

```
GET /api/v1/orgs/demo/query?start=2026-09-01&end=2026-09-30&dimensions=person,provider&interval=month&f=model_family:contains:claude&f=person:exists:
```

`GET /orgs/{org}/queries` takes `measures=a,b` and returns one result per measure with
the same grouping and filters. Per provider and month: `GET
/orgs/{org}/providers/{provider}/months/{month}/summary`, `.../usage?by=`,
`.../series?by=`, `.../movers`, `.../reconcile`, `.../anomalies`, `.../budgets`,
`.../invoices`, `.../projection`, `.../people/{email}`; `provider` may be `all`.
Inventory: `GET /orgs/{org}/providers/{provider}/inventory/api-keys`, `.../inventory/users`,
`.../inventory/search`. Signals: `GET /orgs/{org}/providers/{provider}/signals` and
`GET /orgs/{org}/signals/history`. Owners read the audit trail at `GET /orgs/{org}/audit`.
Errors come back as `{"detail": "...", "code": "..."}` with the HTTP status; the codes are
listed in `docs/operations/errors.md`.

## Tie-out report

```
just api::tieout-report --org <slug> --months 3
```

Prints pass or fail and the percent delta per provider and month for the same checks the
Reconciliation page runs: stored rows against the provider's report, attribution against
cost, Costura's total against the provider's control total and against the invoice total an
owner typed in. No amount, key, workspace or e-mail appears, so the output can be pasted
into a public issue. `just prod::tieout-report --org <slug>` runs it against the production
database.

## Where the documentation lives

- `README.md`: what Costura is, quickstart, telemetry stance, checks.
- `docs/operations/`: install, configuration, upgrade, backup and restore, monitoring,
  troubleshooting, errors, webhooks, repository settings.
- `docs/architecture/overview.md`: the one-diagram overview.
- `docs/product/screens.md`: every screen with its behavior.
- `docs/security/threat-model.md` and `docs/security/provider-keys.md`.
- `apps/api/README.md` and `apps/web/README.md`: the two applications.
- `AGENTS.md` and `CONTRIBUTING.md` for changes to the code; `llms.txt` lists every page.
