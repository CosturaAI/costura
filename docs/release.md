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
[`skills/costura/SKILL.md`](../skills/costura/SKILL.md), and [`CHANGELOG.md`](../CHANGELOG.md).
Nobody edits those versions or the changelog by hand. Before the first release they read
`0.0.0`; the first `feat:` on `main` makes the release pull request for `0.1.0`.

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
     just prod::backup "costura-$(date -u +%Y%m%dT%H%M%SZ).dump"
     COSTURA_VERSION=X.Y.Z just prod::up
     ```

     The backup line is step 1 of [upgrade.md](operations/upgrade.md); the second line is
     its last step with the version filled in.
3. Merge it. release-please tags `vX.Y.Z` and creates the GitHub Release.
4. [`.github/workflows/publish-images.yml`](../.github/workflows/publish-images.yml) builds
   and pushes `ghcr.io/costuraai/costura-{api,web,proxy}:X.Y.Z` (and `:latest`) with SBOM
   and provenance. Pull-request image scans are a different workflow,
   [`.github/workflows/images.yml`](../.github/workflows/images.yml): they run on `main`,
   weekly, and on pull requests that touch `apps/api/**`, `apps/web/**`, `deploy/**`,
   `docker-compose.prod.yml`, the mise pins, the production smoke scripts, or
   `.just/prod.just`. A change to `COSTURA_DEMO_REFRESH` in that compose file is already
   on this path list. The variable defaults to `false` and is forwarded to the scheduler.
5. [`.github/workflows/post-release.yml`](../.github/workflows/post-release.yml) runs when
   Publish images completes with success (or by hand with a `version` input). It checks out
   the release, pulls `ghcr.io/costuraai/costura-{api,web,proxy}:X.Y.Z` from GHCR, starts
   the production Compose stack on the runner with `just prod::up` and a synthetic env file
   from `scripts/smoke-env.sh`, reads `/live` through the proxy, and removes the stack. It
   builds nothing: a red run means the published images do not start together. Rerun it
   from the Actions tab after a GHCR outage; a failure that reproduces is a reason to pull
   the Release and the tags before announcing them.

## Release notes

release-please writes the Release body and the `CHANGELOG.md` section from the squash
commit titles, grouped by Conventional Commit type.

Before `1.0.0`, `feat` commits bump the minor version and `fix` commits bump the patch
(`bump-minor-pre-major` / `bump-patch-for-minor-pre-major` in
[`release-please-config.json`](../release-please-config.json)).

## Bumps Dependabot does not make

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

Dependabot updates the `FROM` digests in [`deploy/proxy.Dockerfile`](../deploy/proxy.Dockerfile),
not the arguments of its `xcaddy build` line. When Caddy or `golang.org/x/net` ships a
release, or the image scan names one of them, bump `v2.11.7` (and the matching
`caddy:<version>-builder-alpine` and `caddy:<version>-alpine` tags) and the `x/net` version in
that line by hand. `gh api repos/caddyserver/caddy/releases/latest --jq .tag_name` and
`curl -s https://proxy.golang.org/golang.org/x/net/@latest` print the newest versions.
