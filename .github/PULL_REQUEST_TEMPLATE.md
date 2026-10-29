<!-- Title must be a Conventional Commit: feat:, fix:, docs:, refactor:, perf:, test:, build:, ci:, chore:, revert: -->

## What changed

## Why

Do not paste provider keys, session cookies, `COSTURA_SECRET_KEY`, or `.env`.

## How to verify

CI runs the full suite. Locally, the checks your change needs ("Pick the smallest path" in CONTRIBUTING.md):

- [ ] `just check`
- [ ] `just docs::check-llms` after a documentation edit
- [ ] The tests of the files you changed (`just api::test-unit`, `just api::test`, `just web::test`)
- [ ] Optional before review: `just coverage upstream/main` (Docker), which CI also runs
- [ ] After a change to a screen: the reviewed PNGs from `just web::snapshots`, or from the failing CI job's `playwright-traces` artifact
