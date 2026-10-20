# Web app conventions

Read these before changing `apps/web`. The Next.js block below is generated; leave it in place.

## Data

- The API client (`src/lib/api/`) runs on the server only: pages, route handlers and server
  actions call it; client components receive data as props or call a server action.
- Response types come from `src/lib/api/generated.ts` through `Schema<"...Out">`. Narrow a
  `string` field to a literal union with `Omit<Schema<...>, "field"> & { field: Union }`;
  do not restate a schema by hand. Regenerate with `just web::api-types` after `just api::openapi`.
- Independent reads of one render start together (`Promise.all`, `settledRecord` in
  `src/lib/loaders.ts`). `transport.ts` dedupes identical GETs per render, so two callers that
  need the same rows must ask with the same URL.

## Writes

- A server action validates its form with `parseForm(form, schema)` (`src/lib/form.ts`,
  zod) and reads the organization from the session cookie (`requireActiveOrg`), never from an
  argument the client sends.
- A server action wraps the API call in `runMutation(work, routes)` with a route list from
  `src/lib/mutations.ts`; `EVERY_PAGE` is for writes that change what every page shows.
- Submit controls use `SubmitButton` or `ConfirmSubmit`, which set `aria-disabled` while
  pending so focus stays on the control.

## Components

- Selects are `NativeSelect` (`src/components/ui/native-select.tsx`).
- A layout that differs between phone and desktop uses CSS breakpoints (`hidden md:block`).
  `useMinWidth` is only for behavior that markup cannot express (chart sizing, row counts).
- Field errors use `FieldError` with `aria-describedby`; information lives in visible text or
  `MethodHint`, not in a `title` attribute. `src/test/title-attributes.test.ts` pins the
  remaining `title` attributes per file (they repeat visible text or an id hint), so a new
  one fails the run.

## Checks

- `just web::lint`, `just web::format-check`, `just web::typecheck`, `just web::test` from the
  repository root. `src/lib/api/contract.test.ts` matches every client method to an OpenAPI
  route, and `src/test/mock-api-contract.test.ts` checks the e2e mock against the schemas.
- A visible change: `just web::snapshots` regenerates the Playwright screenshots in the pinned
  image, and `just web::screens` on a running `just dev` recaptures
  `docs/assets/screens/` for `docs/product/screens.md`.

<!-- BEGIN:nextjs-agent-rules -->

## This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
