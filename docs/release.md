# Releasing

Costura releases with [release-please](https://github.com/googleapis/release-please).
Squash-merged pull requests whose titles follow Conventional Commits
(`feat:`, `fix:`, `docs:`, …) accumulate on `main`. release-please opens (or updates) a
pull request titled `chore(main): release X.Y.Z` that bumps
[`version.txt`](../version.txt), the `version` field of
[`apps/api/pyproject.toml`](../apps/api/pyproject.toml),
[`apps/web/package.json`](../apps/web/package.json), the `costura-api` entry of
[`apps/api/uv.lock`](../apps/api/uv.lock),
[`.release-please-manifest.json`](../.release-please-manifest.json), `COSTURA_VERSION` in
[`.env.example`](../.env.example), the skill version in
[`skills/costura/SKILL.md`](../skills/costura/SKILL.md), the release between the
`x-release-please-start-version` markers in
[`docs/operations/install.md`](operations/install.md) and
[`docs/operations/upgrade.md`](operations/upgrade.md), and [`CHANGELOG.md`](../CHANGELOG.md).
Nobody edits those versions or the changelog by hand. Before the first release they read
`0.0.0` and `CHANGELOG.md` is empty; `initial-version` in
[`release-please-config.json`](../release-please-config.json) makes the first release `0.1.0`,
and release-please writes the changelog heading with that first section.

## Cut a release

1. Confirm CI is green on `main`.
2. Review the release-please pull request: version bump, changelog section, and the two
   package manifests. Edit the notes in the pull request body when needed; release-please
   reads the edited body back into `CHANGELOG.md` and the GitHub Release on merge.
   - When a commit in the release carries `!` (a breaking change), write one paragraph
     titled "Who is affected" above the list: which installs see the change, what breaks
     without action, and the step that fixes it.
   - Put the upgrade commands at the top of the notes, so the Release body starts with
     them:

     ```
     git fetch --tags && git checkout vX.Y.Z
     just prod::upgrade
     ```

     These are the two commands at the top of [upgrade.md](operations/upgrade.md), with the
     version filled in. `just prod::upgrade` takes the backup, writes `COSTURA_VERSION` to
     `.env` and migrates; a `COSTURA_VERSION=X.Y.Z` prefix on `just prod::up` would do
     neither, because `.env` keeps the old release.
3. Merge it. release-please tags `vX.Y.Z` and creates the GitHub Release.
4. [`.github/workflows/publish-images.yml`](../.github/workflows/publish-images.yml) builds
   and pushes `ghcr.io/costuraai/costura-{api,web,proxy}:sha-<commit>` with SBOM and
   provenance, smokes them (step 5), and only then tags them `X.Y.Z` and `latest` in the
   "Promote the release tags" job. Pull-request image scans are a different workflow,
   [`.github/workflows/images.yml`](../.github/workflows/images.yml): they run weekly, and
   on pushes to `main` and pull requests that touch `apps/api/**`, `apps/web/**`,
   `deploy/**`, `docker-compose.prod.yml`, the mise pins, the production smoke scripts, the
   `scripts/prod*` scripts, the `Justfile`, or `.just/prod.just`. A change to `COSTURA_DEMO_REFRESH` in that compose file is already
   on this path list. The variable defaults to `false` and is forwarded to the scheduler.
5. The "Release candidate smoke" job of Publish images runs after every image is built,
   scanned and attested, and before the tags move. It checks out the release tag, pulls
   `ghcr.io/costuraai/costura-{api,web,proxy}:sha-<commit>` from GHCR, starts the production
   Compose stack on the runner with `just prod::up` and a synthetic env file from
   `scripts/smoke-env.sh` (`COSTURA_VERSION=sha-<commit>`), reads `/live` through the proxy,
   and removes the stack. It builds nothing: a red run means the candidate images do not
   start together, and `X.Y.Z` and `latest` stay where they were. Rerun that job from the
   Actions tab after a GHCR outage; the promote job runs when it passes. A failure that
   reproduces is a reason to pull the Release before announcing it.
6. The "Attach the Docker-only bundle" job runs after the promote job. It packs
   `costura-X.Y.Z.tar.gz` with `scripts/release-bundle.sh` (the production compose file,
   `.env.example`, `LICENSE` and the prod init, doctor and password scripts) and uploads it
   and its `.sha256` to the Release, for the
   [Docker-only install](operations/install.md#docker-only).

## Release notes

release-please writes the Release body and the `CHANGELOG.md` section from the squash
commit titles, grouped by Conventional Commit type.

Before `1.0.0`, `feat` commits bump the minor version, `fix` commits bump the patch, and a
breaking change bumps the minor (`bump-minor-pre-major` in
[`release-please-config.json`](../release-please-config.json)). While the project is in beta,
`prerelease` in that file marks every GitHub Release as a pre-release; delete it for `1.0.0`.
A pre-release still fires `release: published`, so the images publish the same way, but
GitHub does not show it as the latest release.

## Bumps Dependabot does not make

[`.github/dependabot.yml`](../.github/dependabot.yml) skips TypeScript 6.1 and later:
typescript-eslint, which `eslint-config-next` uses, accepts TypeScript below 6.1.0. Remove that
`ignore` entry when `npm view typescript-eslint peerDependencies` allows the newer version.

Dependabot has no `mise` ecosystem, so the tool versions in [`mise.toml`](../mise.toml) and
[`mise.lock`](../mise.lock) (Python, Node.js, pnpm, uv, just, actionlint, trivy, and the
rest) move only by hand. Once a month, run `mise upgrade --bump`, which rewrites both files
to the newest versions, then `just check` and `just coverage-core`, and open one `chore:`
pull request with the result. `--bump` crosses major and minor lines, so compare the new
`python` and `node` lines with the base images in `apps/api/Dockerfile` and
`apps/web/Dockerfile` before merging; a new Python or Node minor is a separate change. The
Images workflow runs on that pull request because the two files are on its path list.

The web runtime image runs `apt-get upgrade` on top of a digest-pinned Debian base
([`apps/web/Dockerfile`](../apps/web/Dockerfile)). A rebuild therefore picks up Debian
security updates published after that digest; the weekly Images run and every Dependabot
digest bump rebuild it, and Trivy scans the result. A release image is reproducible from its
published digest, not from the Dockerfile alone.

The devcontainer installs mise from a release binary checked against a SHA-256 in
[`.devcontainer/Dockerfile`](../.devcontainer/Dockerfile). Dependabot updates that file's
`FROM` digest and the Docker-in-Docker feature digest in `devcontainer.json`, not
`MISE_VERSION`: bump it and both checksums by hand from the release's `SHASUMS256.txt`
(`gh api repos/jdx/mise/releases/latest --jq .tag_name`).

Dependabot updates the `FROM` digests in [`deploy/proxy.Dockerfile`](../deploy/proxy.Dockerfile),
not the arguments of its `xcaddy build` line. When Caddy, `golang.org/x/net` or
`github.com/go-jose/go-jose/v4` ships a release, or the image scan names one of them, bump
`v2.11.7` (and the matching `caddy:<version>-builder-alpine` and `caddy:<version>-alpine` tags)
and the `--replace` versions in that line by hand.
`gh api repos/caddyserver/caddy/releases/latest --jq .tag_name`,
`curl -s https://proxy.golang.org/golang.org/x/net/@latest` and
`gh api repos/go-jose/go-jose/releases/latest --jq .tag_name` print the newest versions. The
API and proxy runtime stages upgrade the base image's system packages at build time, as the
web image does, so a fixed Debian or Alpine package reaches the image before its base is
rebuilt.
