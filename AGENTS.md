# Agents

Work from the repository root. Setup, commit titles, and the narrower test recipes
are in [CONTRIBUTING.md](CONTRIBUTING.md).

## Finish

`just check` from the repository root exits 0, and the tree is unchanged after that
run. It is workflow lint, lint, types, generated API types, and the secret scan. It does
not boot the stack. A behavior change also passes `just coverage-core`, the test gate CI
runs (`just test` plus the coverage floors). `just quality::vulnerabilities` is the CI
security scan.

[skills/costura/SKILL.md](skills/costura/SKILL.md) is the skill an agent that operates or
queries a Costura install loads (`npx skills add CosturaAI/costura`); it names the recipes,
the API query model and the tie-out report. `apps/api/tests/test_documentation.py` checks
that it cites only recipes and paths that exist.

## Reach these when the change matches

- The API import direction and the pinned tool versions:
  `apps/api/tests/test_architecture.py` and `mise.toml`.
- Trust boundaries, credentials, sessions, backups, or
  [docker-compose.prod.yml](docker-compose.prod.yml):
  [docs/security/threat-model.md](docs/security/threat-model.md).
- The web app: [apps/web/AGENTS.md](apps/web/AGENTS.md), then the Next.js docs it names.
- A screen of the web app, its copy or its behavior: the section and image in
  [docs/product/screens.md](docs/product/screens.md). Recapture with `just web::screens`
  on a running `just dev` and commit the images under `docs/assets/screens/`. The product
  behavior each screen states there is the behavior the change must leave true.
- A schema change: a new revision under `apps/api/alembic/versions` that extends the
  single chain (`just api::revision "message"`). A revision already in that directory
  stays as applied databases recorded it. `just api::migration-check` requires one
  base and one head. The revision recipe rewrites the inventory in
  [apps/api/README.md](apps/api/README.md).
