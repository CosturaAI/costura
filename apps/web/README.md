# Costura web

Next.js 16 application for Costura. Server-component pages read the Costura API
(`COSTURA_API_URL`, default `http://127.0.0.1:8000`) during rendering, carrying the bearer
token of the `costura_session` cookie. A 401 sends the browser to `/sign-in`; the public sample
organization `demo` renders without a session, with "Sign in" in the sidebar footer.

Per organization, time range and provider scope (`anthropic`, `claude_ai`, `codex`, `copilot`,
`cursor`, `openai`, `openrouter`, or `all` for every provider together, the default) the app shows:

- Overview: headline figures, the spend chart (with a provider share strip under `all`),
  the share of the month's spend that counts under a person, and one driver list. Top accounts, what changed, anomalies, budgets and the model
  breakdown sit under “More on this period”.
- Analyze (`/explore`): a day/week/month chart and attribution table. The first controls are
  group-by, active filters, Add filter, Copy and Export. Add filter opens the editor.
  Repeatable `f=<dimension>:<op>:<value>[,<value>]` clauses (`is`, `is_not`, `one_of`,
  `not_one_of`, `contains`, `not_contains`, `exists`, `not_exists`) stay. Row limits, display,
  chart axis and linear projection sit under View options. A period comparison the table does
  not render is ignored. CSV export goes through a signed-in same-origin route.
- Guardrails: anomalies (`/anomalies`) and budgets (`/budgets`). Each anomaly is listed once.
  Anomaly filters sit under Filters; the detail page keeps the summary, owner, status action
  and chart visible, and the checks, baseline, day and supporting tables under Evidence.
  Adding or editing a budget opens a sheet. Budget progress is the row, not a second section.
- Data health: reconciliation (`/reconcile`), with sync status and run history (`/runs`) as
  tabs beside it. A passing reconciliation check is one line. Run history filters by one job
  selector; window, duration, pages and raw results sit under Telemetry. Resources
  (`/inventory`) has no menu item; search offers it when nothing matches, and the sample organization's
  settings link to it. It lists
  API keys, workspaces / projects, and people and services, current rows by default, with
  dates under Details. Search in the header (Ctrl+K or Cmd+K) finds current
  people, services, API keys and workspaces in the active organization and provider. The
  browser calls `/api/inventory/search`; the organization, provider and session stay on the
  server. A result for a key, service or workspace opens its entity page with the provider
  and provider account, so a repeated id opens that row. `/inventory` stays the full list, including missing rows.
- One detail page per key, account, workspace, model and person. Identity, spend, the chart,
  one breakdown and alerts are on the page. Facts, extra figures, the budget and further
  breakdowns sit under Details and Further breakdowns.
- Each page sets its tab title (`metadata.title`, shown as `Title · Costura`).
- The error boundary names the data service when the error says the API did not answer (a
  network failure or a 5xx). Production redacts server errors, so those read "This page could
  not load", say the data service may be unreachable, and show the Next.js digest under
  Technical details. Retry refreshes the route and resets the boundary.
- Settings: organization, connections, sync, anomalies, members, teams, audit (owners),
  advanced (owners) and account. The sample organization shows how it is configured,
  connections, sync and anomalies, read-only.

Under `all` every row carries a provider badge and links to its entity under its own provider.
A provider holds several accounts: rows of a named account carry "Provider -
Account", Explore groups by `provider_account` and Reconcile narrows to one account.

The view (organization, the month a link without dates opens, provider scope, dates and interval) lives in the
`costura_view` cookie, not in the URL: pages have fixed addresses and `/o/{slug}`
activates an organization (`?from=&to=&time_frame=` carry the dates across a scope change).
An Analyze link that carries `from` and `to` different from the view goes through
`/o/{slug}`, which writes them into the cookie and comes back without them, so the header
picker and the page read one range. The web view keeps ranges inside the API's bounds
(2000-2099, at most 3660 days, 400 on the sample organization).
Every page reads its data for the time frame in the scope bar; budgets stay
monthly and name the month they show. Before the shell: `/sign-in` (Google when
configured; a local e-mail form only in development/test), `/new`, `/join`, `/join/{token}`
and `/welcome` (connect the first provider key).

Theme and brand are host configuration (`src/lib/theme.ts`): `COSTURA_THEME` picks a token file
in `src/themes/` (`costura` by default), `COSTURA_COLOR_SCHEME` is `light`, `dark` or `system`
and becomes `data-theme` on `<html>`, and `COSTURA_BRAND_NAME` names the product. `src/app/layout.tsx` points the tab icon at `public/brand/favicon.svg` (a filled tile of the `logo.svg` mark, legible at 16px and on dark tabs) with `public/favicon.ico` (16, 32 and 48px, rendered from it) for browsers that request `/favicon.ico`, and the home-screen icon at the pre-rendered `public/apple-touch-icon.png` (iOS does not rasterize SVG icons). Tailwind's
`dark:` variant follows `data-theme`. The sidebar labels those routes Overview, Analyze,
Anomalies and Budgets (under Guardrails), Reconciliation and Settings; sync status and run
history are tabs on Reconciliation. The routes stay `/overview`, `/explore`, `/anomalies`, `/budgets`, `/reconcile`,
`/inventory`, `/runs`, `/review` and `/settings`. What each area shows first is
`docs/product/screens.md`.

## Themes

Colors live in `src/themes/`. `costura.css` and `costura-dark.css` are the default.
Components use semantic classes (`bg-background`, `text-muted-foreground`, `text-critical`).
A new theme is a CSS file in that directory plus `COSTURA_THEME`. Do not add raw palette
classes (`text-gray-500`, `bg-brand-600`) outside `themes/` and `components/ui/`.

## Run

From the repository root with `just`:

- `just web::dev` starts Next.js on `http://127.0.0.1:3000` (`just dev` starts the API and the worker too).
- `just web::test` runs Vitest once: unit tests next to their module in `src/lib` and
  `src/components`, server-action tests next to each `*-actions.ts`, and render tests per
  page area in `src/app/pages-*.test.tsx`.
- `just web::coverage` runs Vitest with V8 coverage and fails under the floors in
  `vitest.config.mts` (92% lines, 90% statements, 82% branches, 88% functions);
  interactive UI wrappers are included, while only explicit declarative wrappers are
  excluded. Root `just coverage-core` rejects missing and stale LCOV records;
  `just web::diff-coverage` then requires 90% of the lines changed since `origin/main`.
- `just web::test-e2e` builds the production app, installs the Chromium revision pinned by
  `@playwright/test` and runs `e2e/smoke.spec.ts`, the visual suite in `e2e/visual.spec.ts`
  and the axe WCAG 2.2 AA suite in `e2e/a11y.spec.ts`.
  Without `PLAYWRIGHT_BASE_URL`, `playwright.config.ts` starts the mock API (`e2e/mock-api.mjs`)
  on `127.0.0.1:3200` and the production server on `127.0.0.1:3100`; set it to run the specs
  against a running stack. When the pinned browser download is unavailable, run `pnpm test:e2e`
  with `PLAYWRIGHT_EXECUTABLE_PATH` set to an installed Chromium-compatible browser. Specs run
  sequentially because their writes share the mock server's in-memory records.
- `just web::test-visual` runs only `e2e/visual.spec.ts`. It checks viewport screenshots for
  the main pages in light and dark, at desktop, tablet and phone widths, and asserts that the
  page does not scroll sideways, that `#main` exists, that the provider control stays visible
  and that the sidebar appears at 1024px. Snapshots live next to the spec and omit the OS name
  so CI (Linux Chromium) and a local run share one set; a small pixel ratio absorbs font
  rasterization. Review a layout change with `just web::snapshots` (Linux Chromium in Docker),
  look at the PNGs, and commit only the ones that match the intended layout. Do not put
  alert, invite or pricing mutations in a capture. CI uploads `apps/web/test-results` on
  failure, which includes the screenshot diffs.
- `just web::test-e2e-demo` builds the production app and runs `e2e-demo/demo.spec.ts`
  against PostgreSQL, the API and a sample built as of 2026-09-15 (`scripts/demo-e2e.sh`,
  needs Docker). It walks the anonymous journey and the sample notice, exports CSV, opens a key and
  an anomaly, and checks Reconcile, Runs, Settings and the absence of write controls.
  Screenshots cover desktop and phone, light and dark, and live next to the spec. Pass
  `--update-snapshots` to replace them. CI uploads `apps/web/test-results-demo` on failure.
- `just web::snapshots` regenerates every committed screenshot (`e2e/visual.spec.ts` and
  `e2e-demo/demo.spec.ts`) from the pinned `mcr.microsoft.com/playwright` image instead of the
  host's own Chromium, so the pixels match CI regardless of the host OS. It sets
  `COSTURA_PLAYWRIGHT_DOCKER_IMAGE` for `scripts/demo-e2e.sh`, which then runs the demo suite's
  Playwright step in that container against the host-run API and web servers, forwarded to the
  container's `127.0.0.1`, instead of `pnpm exec playwright`. It rewrites every image, not only
  the failing ones (`--update-snapshots=all`). Needs Docker.
- `just web::test-e2e-docker` and `just web::test-e2e-demo-docker` run the same two suites
  with the browser inside that pinned image, so they compare against the committed
  screenshots with the pixels that wrote them. CI runs these two. The demo suite shares the
  host network on Linux and uses the forwarder elsewhere. Needs Docker.
- `just web::build` runs `next build`. The production image uses `output: "standalone"`
  (`apps/web/Dockerfile`).
- `just web::lint`, `just web::format-check` and `just web::typecheck` run ESLint (plus the
  palette and contrast checks), Prettier and `tsc`.
  ESLint stays on 9.x and TypeScript on 6.x until `eslint-config-next`'s plugins support
  ESLint 10 and TypeScript 7.

## Structure

```
apps/web/
|-- e2e/                       # smoke, visual and a11y specs against mock-api.mjs
|-- e2e/capture-screens.mjs    # `just web::screens`: the images of docs/product/screens.md
|-- e2e-demo/                  # the sample organization against the real API (scripts/demo-e2e.sh)
|-- vitest.config.mts          # jsdom, coverage floors
`-- src/
    |-- proxy.ts               # Next middleware: one CSP nonce per request, both policy headers
    |-- themes/                # token files selected by COSTURA_THEME (costura.css, costura-dark.css)
    |-- actions/               # server actions shared by several routes: view, sign-out, alerts
    |                          # (the bell), keys (mark a key as one person's), reconcile
    |                          # (invoice totals), welcome
    |-- app/
    |   |-- layout.tsx, globals.css, error.tsx, not-found.tsx, page.tsx (landing redirect)
    |   |-- sign-in/, new/, join/, join/[token]/, welcome/, o/[org]/, o/-missing/
    |   |-- api/auth/google/   # start and callback route handlers
    |   |-- api/exports/query/ # same-origin CSV stream of the range query
    |   |-- api/inventory/search/, api/review/, api/csp-report/
    |   |-- pages-*.test.tsx   # render tests per area (welcome, shell, overview, explore, anomalies,
    |   |                      # budgets, settings, data, entities) on the shared page harness
    |   |-- server-actions.test.ts, route-conventions.test.tsx, no-cli.test.tsx
    |   `-- (app)/             # the shell: sidebar, scope bar, freshness pill, banners
    |       |-- overview/, explore/, anomalies/, anomalies/[id]/, budgets/, reconcile/,
    |       |   inventory/, runs/, review/
    |       |-- keys/[id]/, accounts/[id]/, workspaces/[id]/, models/[id]/, people/[email]/
    |       |-- overview/actions.ts, anomalies/actions.ts, budgets/actions.ts
    |       `-- settings/      # one route per section (organization, connections, sync, anomalies,
    |                          # members, teams, audit, advanced, account, sample); data.ts loads
    |                          # what the layout needs; *-actions.ts are the server actions behind
    |                          # the forms (connection, member, organization, team, webhook)
    |-- components/
    |   |-- ui/                # shadcn primitives; colors only through tokens
    |   |-- charts/            # spend-rows.ts (pure row building), daily-spend-chart.tsx,
    |   |                      # anomaly-series-chart.tsx, sparkline.tsx, palette.ts
    |   |-- entity/            # the pieces of the key, account, workspace, model and person pages
    |   `-- *.tsx              # shell, cards, tables, forms and banners shared by the pages
    |-- lib/
    |   |-- api/               # server-only client: transport.ts (bearer, query encoding, 401 detour),
    |   |                      # generated.ts from the OpenAPI snapshot, and one module per domain
    |   |                      # (session, organizations, connections, spend, inventory, anomalies,
    |   |                      # budgets, teams, webhooks); index.ts builds `api`
    |   |-- api-error.ts       # ApiError, importable by client forms
    |   |-- spend-query.ts     # range-query adapters shared by Overview, Explore and entity pages
    |   |-- overview.ts, explore.ts, entity.ts, review.ts   # page loaders
    |   |-- view.ts            # resolves the view cookie against the API
    |   |-- theme.ts           # brand name, color scheme and theme file from the environment
    |   `-- ...                # formatting, dimensions, anomalies, budgets, setup, roles
    `-- test/
        |-- fixtures/          # API payloads per domain behind index.ts (`import * as fx`)
        `-- page-harness.ts    # shared mocks for the page render tests
```

`src/lib/api/contract.test.ts` checks every client method against
`apps/api/tests/snapshots/openapi.json` (paths, methods, and the response fields Overview
and Explore read), so a drift from the API fails here too. Explore loads its measures with
`GET /orgs/{org}/queries`.

Environment: `COSTURA_API_URL`, plus the optional `COSTURA_THEME`, `COSTURA_COLOR_SCHEME`,
`COSTURA_BRAND_NAME` and `COSTURA_PUBLIC_DEMO_HOME`. Google sign-in additionally needs
`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `COSTURA_WEB_PUBLIC_URL` on the API; the web
callback is `/api/auth/google/callback`. The web app reads no `COSTURA_ORG`: the root redirect
follows the session and the view cookie, and without a session it opens `/sign-in`, or
`/o/demo` when `COSTURA_PUBLIC_DEMO_HOME=true`.
