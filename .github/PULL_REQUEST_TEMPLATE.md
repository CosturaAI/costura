<!-- Title must be a Conventional Commit: feat:, fix:, docs:, refactor:, perf:, test:, build:, ci:, chore:, revert: -->

## What changed

## Why

Do not paste provider keys, session cookies, `COSTURA_SECRET_KEY`, or `.env`.

## How to verify

- [ ] `just check`
- [ ] `just docs::check-llms` after a documentation edit
- [ ] `just coverage upstream/main` after a code change (`just coverage` outside a fork): the coverage floors and 90% of the changed lines
- [ ] `just web::snapshots`, with the reviewed PNGs committed, after a change to a screen
